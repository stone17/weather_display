import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from weather_provider_base import DailyDataPoint, HourlyDataPoint
from weather_data_parser import WeatherData
from image_generator import DEFAULT_ICON_DISPLAY_CONFIGS

class TestDayNightIcons(unittest.TestCase):
    def test_daily_datapoint_fields(self):
        dp = DailyDataPoint(
            dt=1700000000,
            weather_icon="01d",
            weather_icon_day="01d",
            weather_icon_night="01n"
        )
        self.assertEqual(dp.weather_icon, "01d")
        self.assertEqual(dp.weather_icon_day, "01d")
        self.assertEqual(dp.weather_icon_night, "01n")

    def test_weather_data_parser_day_night_extraction(self):
        # Test with DailyDataPoint objects having day & night icons
        daily_pts = [
            DailyDataPoint(
                dt=1700000000,
                temp_min=10.0,
                temp_max=20.0,
                weather_icon="02d",
                weather_icon_day="02d",
                weather_icon_night="02n"
            ),
            DailyDataPoint(
                dt=1700086400,
                temp_min=12.0,
                temp_max=22.0,
                weather_icon="10d",
                weather_icon_day=None, # Fallback test
                weather_icon_night=None
            )
        ]
        current_pt = {'dt': 1700000000, 'temp': 15.0, 'weather': [{'icon': '01d'}]}
        parsed = WeatherData(current_pt, [], daily_pts, temp_unit_pref='C')
        daily_list = parsed.daily
        
        self.assertEqual(len(daily_list), 2)
        # Entry 1
        self.assertEqual(daily_list[0]['weather_icon'], "02d")
        self.assertEqual(daily_list[0]['weather_icon_day'], "02d")
        self.assertEqual(daily_list[0]['weather_icon_night'], "02n")

        # Entry 2 fallback derivation
        self.assertEqual(daily_list[1]['weather_icon'], "10d")
        self.assertEqual(daily_list[1]['weather_icon_day'], "10d")
        self.assertEqual(daily_list[1]['weather_icon_night'], "10n")

    def test_default_icon_display_configs(self):
        self.assertIn('daily_display_day_night', DEFAULT_ICON_DISPLAY_CONFIGS)
        dn_config = DEFAULT_ICON_DISPLAY_CONFIGS['daily_display_day_night']
        self.assertIn('default', dn_config)
        self.assertIn('x_offset_day', dn_config['default'])
        self.assertIn('x_offset_night', dn_config['default'])
        self.assertIn('width', dn_config['default'])
        self.assertIn('height', dn_config['default'])

if __name__ == '__main__':
    unittest.main()
