import os
import sys
import unittest
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import image_generator
from weather_provider_base import DailyDataPoint
from weather_data_parser import WeatherData
from image_generator import create_daily_forecast_display

class TestDailyForecastRendering(unittest.TestCase):
    def setUp(self):
        self.fonts = {
            'heading': ImageFont.load_default(),
            'body': ImageFont.load_default(),
            'small': ImageFont.load_default()
        }
        self.colors = {
            'text': (0, 0, 0),
            'blue': (0, 0, 200),
            'green': (0, 180, 0),
            'orange': (255, 140, 0),
            'purple': (128, 0, 128)
        }
        self.daily_pts = [
            DailyDataPoint(
                dt=1700000000 + i * 86400,
                temp_min=5.0 + i,
                temp_max=15.0 + i,
                rain=0.5 * i,
                wind_speed=3.0 + i,
                uvi=2.0 + i,
                weather_icon="01d",
                weather_icon_day="01d",
                weather_icon_night="01n"
            ) for i in range(5)
        ]
        current_pt = {'dt': 1700000000, 'temp': 12.0, 'weather': [{'icon': '01d'}]}
        self.parsed = WeatherData(current_pt, [], self.daily_pts, temp_unit_pref='C')
        self.icon_cache = os.path.join(PROJECT_ROOT, "cache", "icon_cache")
        os.makedirs(self.icon_cache, exist_ok=True)

    def test_rendering_single_and_dual_icon_modes(self):
        # 1. Standard mode
        canvas_standard = Image.new("RGBA", (800, 480), (255, 255, 255, 255))
        image_generator.image_canvas = canvas_standard
        image_generator.draw_context = ImageDraw.Draw(canvas_standard)

        config_standard = {
            'daily_forecast_day_night': False,
            'daily_forecast_display_details': ['temp', 'rain', 'wind', 'uvi']
        }
        create_daily_forecast_display(
            weather_data_daily=self.parsed.daily,
            temperature_unit_pref='C',
            project_root_path=PROJECT_ROOT,
            icon_provider_preference='open-meteo',
            app_config=config_standard,
            fonts=self.fonts,
            colors=self.colors,
            icon_cache_path=self.icon_cache
        )

        # 2. Day/Night mode
        canvas_dn = Image.new("RGBA", (800, 480), (255, 255, 255, 255))
        image_generator.image_canvas = canvas_dn
        image_generator.draw_context = ImageDraw.Draw(canvas_dn)

        config_dn = {
            'daily_forecast_day_night': True,
            'daily_forecast_display_details': ['temp', 'rain', 'wind', 'uvi']
        }
        create_daily_forecast_display(
            weather_data_daily=self.parsed.daily,
            temperature_unit_pref='C',
            project_root_path=PROJECT_ROOT,
            icon_provider_preference='open-meteo',
            app_config=config_dn,
            fonts=self.fonts,
            colors=self.colors,
            icon_cache_path=self.icon_cache
        )

        self.assertEqual(canvas_standard.size, (800, 480))
        self.assertEqual(canvas_dn.size, (800, 480))

if __name__ == '__main__':
    unittest.main()
