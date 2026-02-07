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

    async def update_display(self, specific_photo=None):
        logger.info("Orchestrator: Starting update cycle...")
        
        mode = self.config.get("display_mode", "weather")
        if specific_photo:
            mode = "photo"

        width = self.driver.width
        height = self.driver.height
        
        # 1. GENERATE CONTENT (RGB)
        img_rgb = None
        
        if mode == "photo":
            logger.info("Delegating to: PhotoFrameGenerator")
            sort_mode = self.config.get("photo_sort_order", "random")
            generator = PhotoFrameGenerator(self.root_dir)
            # Pass specific_filename here
            img_rgb = generator.generate_image(width, height, sort_mode=sort_mode, specific_filename=specific_photo)
            
        else:
            logger.info("Delegating to: WeatherService")
            colors = self.driver.get_rendering_colors()
            weather_svc = WeatherService(self.config, self.root_dir)
            img_rgb = await weather_svc.generate_image(width, height, colors)

        if not img_rgb:
            logger.error("Content generation failed (returned None).")
            return False, "Content generation failed"

        # 2. SAVE SOURCE (For Web Preview)
        cache_dir = os.path.join(self.root_dir, "cache")
        if not os.path.exists(cache_dir): os.makedirs(cache_dir)
        
        source_path = os.path.join(cache_dir, "latest_source.png")
        try:
            img_rgb.save(source_path)
            logger.info(f"Saved source image to {source_path}")
        except Exception as e:
            logger.error(f"Failed to save source image: {e}")

        # 3. DITHERING
        try:
            dither_method = self.config.get("dithering_method", "floyd_steinberg")
            ditherer = DitherProcessor()
            img_dithered = ditherer.process(img_rgb, dither_method)
            
            # Save Dithered Result
            self._save_dithered_file(img_dithered, cache_dir)
            
        except Exception as e:
            logger.error(f"Dithering failed: {e}")
            return False, f"Dithering failed: {e}"

        # 4. SERVER PUSH
        if self.config.get("enable_server_push", False):
            self._handle_legacy_push(img_rgb)

        return True, "Display updated successfully"

    def _save_dithered_file(self, img, cache_dir):
        fmt = self.config.get("output_format", "png")
        for f in ["latest_dithered.png", "latest_dithered.bmp"]:
            p = os.path.join(cache_dir, f)
            if os.path.exists(p): os.remove(p)
            
        save_path = ""
        if fmt == "bmp8":
            save_path = os.path.join(cache_dir, "latest_dithered.bmp")
            img.save(save_path)
        elif fmt == "bmp24":
            save_path = os.path.join(cache_dir, "latest_dithered.bmp")
            img.convert("RGB").save(save_path)
        else:
            save_path = os.path.join(cache_dir, "latest_dithered.png")
            img.save(save_path)
        
        logger.info(f"Saved dithered image ({fmt}) to {save_path}")

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