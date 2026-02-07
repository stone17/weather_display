import sys
import os
import logging
from PIL import Image

# Ensure backend directory is in python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from weather_provider_base import get_weather_provider
from weather_data_parser import WeatherData
from image_generator import generate_weather_image 

logger = logging.getLogger("WeatherService")

class WeatherService:
    def __init__(self, config, root_dir):
        self.config = config
        self.root_dir = root_dir

    async def generate_image(self, width, height, color_palette):
        """
        Fetches data, parses it, and renders the weather image.
        Returns: PIL.Image (RGB) or None
        """
        # 1. Fetch Data
        provider = get_weather_provider(self.config, self.root_dir)
        if not await provider.fetch_data():
            if not provider.get_current_data():
                 logger.error("Fetch failed and no cache available.")
                 return None
            logger.warning("Fetch failed, using cached data.")

        # 2. Parse Data
        graph_cfg = self.config.get("graph_24h_forecast_config", {})
        wdata = WeatherData(
            provider.get_current_data(), 
            provider.get_hourly_data(), 
            provider.get_daily_data(), 
            self.config.get("temperature_unit", "C"),
            graph_config=graph_cfg
        )
        
        # 3. Setup Icon Cache
        cache_dir = os.path.join(self.root_dir, "cache")
        icon_cache = os.path.join(cache_dir, "icon_cache")
        os.makedirs(icon_cache, exist_ok=True)
        
        # 4. Generate RGB Image
        # Note: We pass None as output_path because the Orchestrator handles saving now.
        # We need to tweak image_generator slightly to allow returning without saving,
        # or we just pass a dummy path that gets overwritten later. 
        # Actually, looking at image_generator.py, it returns the object regardless.
        dummy_path = os.path.join(cache_dir, "temp_weather_gen.png")
        
        img = generate_weather_image(
            wdata, 
            dummy_path, # Legacy argument, can be ignored if we just use the return
            self.config, 
            self.root_dir, 
            icon_cache_path=icon_cache,
            color_palette=color_palette
        )
        
        return img