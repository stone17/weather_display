import os
import logging
from PIL import Image

from display_drivers import SevenColorDriver, SpectraE6Driver
from dither import DitherProcessor
from create_weather_info import WeatherService
from photo_frame import PhotoFrameGenerator

logger = logging.getLogger("DisplayManager")

class DisplayOrchestrator:
    def __init__(self, config, root_dir):
        self.config = config
        self.root_dir = root_dir
        self.driver = self._init_driver()
        
    def _init_driver(self):
        hardware = self.config.get("hardware_profile", "generic")
        dither = self.config.get("dithering_method", "floyd_steinberg")
        
        if hardware == "spectra_e6":
            w, h = 800, 480
            return SpectraE6Driver(w, h, dither_method=dither)
        elif hardware == "waveshare_73":
            w, h = 800, 480
            return SevenColorDriver(w, h, dither_method=dither)
        elif hardware == "waveshare_565":
            w, h = 600, 448
            return SevenColorDriver(w, h, dither_method=dither)
        else:
            w = self.config.get("display_width", 600)
            h = self.config.get("display_height", 448)
            return SevenColorDriver(w, h, dither_method=dither)

    async def update_display(self):
        logger.info("Orchestrator: Starting update cycle...")
        
        mode = self.config.get("display_mode", "weather")
        width = self.driver.width
        height = self.driver.height
        
        img_rgb = None
        
        if mode == "photo":
            logger.info("Delegating to: PhotoFrameGenerator")
            sort_mode = self.config.get("photo_sort_order", "random")
            generator = PhotoFrameGenerator(self.root_dir)
            img_rgb = generator.generate_image(width, height, sort_mode=sort_mode)
            
        else:
            logger.info("Delegating to: WeatherService")
            colors = self.driver.get_rendering_colors()
            weather_svc = WeatherService(self.config, self.root_dir)
            img_rgb = await weather_svc.generate_image(width, height, colors)

        if not img_rgb:
            return False, "Content generation failed"

        # Save Source
        cache_dir = os.path.join(self.root_dir, "cache")
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        img_rgb.save(os.path.join(cache_dir, "latest_source.png"))

        # Dithering
        try:
            dither_method = self.config.get("dithering_method", "floyd_steinberg")
            ditherer = DitherProcessor()
            img_dithered = ditherer.process(img_rgb, dither_method)
            self._save_dithered_file(img_dithered, cache_dir)
        except Exception as e:
            return False, f"Dithering failed: {e}"

        # Server Push (Check Enabled Flag)
        if self.config.get("enable_server_push", False):
            self._handle_legacy_push(img_rgb)

        return True, "Display updated successfully"

    def _save_dithered_file(self, img, cache_dir):
        fmt = self.config.get("output_format", "png")
        for f in ["latest_dithered.png", "latest_dithered.bmp"]:
            p = os.path.join(cache_dir, f)
            if os.path.exists(p): os.remove(p)
            
        if fmt == "bmp8":
            img.save(os.path.join(cache_dir, "latest_dithered.bmp"))
        elif fmt == "bmp24":
            img.convert("RGB").save(os.path.join(cache_dir, "latest_dithered.bmp"))
        else:
            img.save(os.path.join(cache_dir, "latest_dithered.png"))

    def _handle_legacy_push(self, img_rgb):
        server_ip = self.config.get("server_ip")
        if server_ip:
            try:
                raw_data, w, h = self.driver.process_image(img_rgb)
                import upload
                logger.info(f"Pushing to {server_ip}...")
                upload.upload_processed_data(raw_data, w, h, server_ip, upload.DEFAULT_UPLOAD_URL)
            except Exception as e:
                logger.error(f"Push failed: {e}")