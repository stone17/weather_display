import sys
import os
import yaml
import asyncio
import logging
from PIL import Image

# Ensure backend directory is in python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from weather_provider_base import get_weather_provider
from weather_data_parser import WeatherData
from display_drivers import SevenColorDriver, SpectraE6Driver
from image_generator import generate_weather_image 
from dither import DitherProcessor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("WeatherBackend")

def load_configuration(base_path, local_path):
    cfg = {}
    if os.path.exists(base_path):
        try:
            with open(base_path, 'r') as f:
                base = yaml.safe_load(f)
                if base: cfg.update(base)
        except Exception as e:
            logger.error(f"Error loading base config {base_path}: {e}")
    if os.path.exists(local_path):
        try:
            with open(local_path, 'r') as f:
                local = yaml.safe_load(f)
                if local: cfg.update(local)
        except Exception as e:
            logger.error(f"Error loading local config {local_path}: {e}")
    return cfg

class WeatherController:
    def __init__(self, config, root_dir):
        self.config = config
        self.root_dir = root_dir
        self.driver = self._init_driver()

    def _init_driver(self):
        hardware = self.config.get("hardware_profile", "generic")
        dither = self.config.get("dithering_method", "floyd_steinberg")
        
        # Resolution defaults
        if hardware == "spectra_e6":
            w, h = 800, 480
        elif hardware == "waveshare_565":
            w, h = 600, 448
        elif hardware == "waveshare_73":
            w, h = 800, 480
        else:
            w = self.config.get("display_width", 600)
            h = self.config.get("display_height", 448)

        logger.info(f"Init Driver: {hardware} ({w}x{h}), Dither: {dither}")
        
        if hardware == "spectra_e6":
            return SpectraE6Driver(w, h, dither_method=dither)
        else:
            # Default fallback for waveshare_565, waveshare_73, and generic
            # This ensures they get the Legacy Colors
            return SevenColorDriver(w, h, dither_method=dither)

    async def run_update(self):
        logger.info("Starting weather update cycle...")
        
        provider = get_weather_provider(self.config, self.root_dir)
        if not await provider.fetch_data():
            if not provider.get_current_data():
                 logger.error("Fetch failed and no cache available.")
                 return False, "Data fetch failed"
            logger.warning("Fetch failed, using cached data.")

        graph_cfg = self.config.get("graph_24h_forecast_config", {})
        wdata = WeatherData(
            provider.get_current_data(), 
            provider.get_hourly_data(), 
            provider.get_daily_data(), 
            self.config.get("temperature_unit", "C"),
            graph_config=graph_cfg
        )
        
        # --- Retrieve Hardware-Specific Color Map ---
        render_colors = self.driver.get_rendering_colors()
        
        cache_dir = os.path.join(self.root_dir, "cache")
        icon_cache = os.path.join(cache_dir, "icon_cache")
        img_source_path = os.path.join(cache_dir, "latest_source.png")
        
        os.makedirs(icon_cache, exist_ok=True)
        
        try:
            # Generate Image with injected colors
            img_rgb = generate_weather_image(
                wdata, 
                img_source_path, 
                self.config, 
                self.root_dir, 
                icon_cache_path=icon_cache,
                color_palette=render_colors 
            )
            
            if not img_rgb:
                 return False, "Image rendering returned None"
                 
            # Apply Dithering
            dither_method = self.config.get("dithering_method", "floyd_steinberg")
            ditherer = DitherProcessor()
            img_dithered = ditherer.process(img_rgb, dither_method)

            # Save Logic
            output_format = self.config.get("output_format", "png") 
            
            for f in ["latest_dithered.png", "latest_dithered.bmp"]:
                p = os.path.join(cache_dir, f)
                if os.path.exists(p): os.remove(p)
            
            if output_format == "bmp8":
                img_dithered.save(os.path.join(cache_dir, "latest_dithered.bmp"))
                logger.info("Saved 8-bit BMP")
            elif output_format == "bmp24":
                img_dithered.convert("RGB").save(os.path.join(cache_dir, "latest_dithered.bmp"))
                logger.info("Saved 24-bit BMP")
            else:
                img_dithered.save(os.path.join(cache_dir, "latest_dithered.png"))
                logger.info("Saved PNG")

        except Exception as e:
            logger.error(f"Render error: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Render error: {e}"

        try:
            # Process for Upload (Legacy Support)
            raw_data, width, height = self.driver.process_image(img_rgb)
            server_ip = self.config.get("server_ip")
            if server_ip:
                import upload
                logger.info(f"Pushing to {server_ip}...")
                upload.upload_processed_data(raw_data, width, height, server_ip, upload.DEFAULT_UPLOAD_URL)
            
        except Exception as e:
            logger.error(f"Hardware processing/upload error: {e}")
            return True, "Image generated (Upload failed)"

        return True, "Weather updated successfully"

async def generate_weather(config_path):
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base_dir = os.path.dirname(config_path)
    filename = os.path.basename(config_path)
    name, ext = os.path.splitext(filename)
    local_config_path = os.path.join(base_dir, f"{name}.local{ext}")
    config = load_configuration(config_path, local_config_path)
    controller = WeatherController(config, root_dir)
    return await controller.run_update()

if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_cfg = os.path.join(root, "config", "config.yaml")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    success, msg = loop.run_until_complete(generate_weather(default_cfg))
    print(f"Result: {success} - {msg}")