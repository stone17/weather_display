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

    def _sanitize_config(self):
        """
        Ensures critical config values are the correct types before
        passing them to the strict provider classes.
        """
        # Fix Coordinates (Force Float)
        # This prevents "London" fallback if they are saved as strings
        for coord in ['lat', 'lon', 'latitude', 'longitude']:
            if coord in self.config and self.config[coord] is not None:
                try:
                    self.config[coord] = float(self.config[coord])
                except (ValueError, TypeError):
                    pass # Keep as is if conversion fails, let provider handle error

        # Fix Cache Duration (Force Int)
        if 'cache_duration_minutes' in self.config:
            try:
                self.config['cache_duration_minutes'] = int(self.config['cache_duration_minutes'])
            except (ValueError, TypeError):
                self.config['cache_duration_minutes'] = 60

        # Fix Graph Time Range (Force Int)
        if 'graph_24h_forecast_config' in self.config:
            g_cfg = self.config['graph_24h_forecast_config']
            if 'graph_time_range_hours' in g_cfg:
                try:
                    g_cfg['graph_time_range_hours'] = int(g_cfg['graph_time_range_hours'])
                except (ValueError, TypeError):
                    g_cfg['graph_time_range_hours'] = 24

    async def generate_image(self, width, height, color_palette):
        # 1. Sanitize Config Types (Critical for SMHI)
        self._sanitize_config()

        # 2. Fetch Data
        provider = get_weather_provider(self.config, self.root_dir)
        
        if provider is None:
            provider_name = self.config.get('weather_provider', 'UNKNOWN')
            logger.error(f"Failed to initialize weather provider '{provider_name}'. Check your configuration.")
            return None

        if not await provider.fetch_data():
            if not provider.get_current_data():
                 logger.error("Fetch failed and no cache available.")
                 return None
            logger.warning("Fetch failed, using cached data.")

        # 3. Parse Data
        graph_cfg = self.config.get("graph_24h_forecast_config", {})
        wdata = WeatherData(
            provider.get_current_data(), 
            provider.get_hourly_data(), 
            provider.get_daily_data(), 
            self.config.get("temperature_unit", "C"),
            graph_config=graph_cfg
        )
        
        # 4. Setup Icon Cache
        cache_dir = os.path.join(self.root_dir, "cache")
        icon_cache = os.path.join(cache_dir, "icon_cache")
        os.makedirs(icon_cache, exist_ok=True)
        
        # 5. Generate RGB Image
        img = generate_weather_image(
            wdata, 
            None, 
            self.config, 
            self.root_dir, 
            icon_cache_path=icon_cache,
            color_palette=color_palette
        )
        
        return img