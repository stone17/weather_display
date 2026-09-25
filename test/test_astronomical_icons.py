import os
import sys
import unittest
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import sun_utils
from weather_data_parser import WeatherData
from weather_provider_base import HourlyDataPoint, DailyDataPoint

class TestAstronomicalDayNightIcons(unittest.TestCase):
    def setUp(self):
        # Stockholm coordinates
        self.lat = 59.3293
        self.lon = 18.0686

    def test_sun_utils_is_daylight_summer(self):
        # On 2026-06-21 in Stockholm:
        # Sunrise is approx 01:31 UTC (03:31 CEST)
        # Sunset is approx 20:07 UTC (22:07 CEST)
        
        # 00:00 UTC (02:00 CEST) -> Night
        dt_night_early = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(sun_utils.is_daylight(dt_night_early, self.lat, self.lon))

        # 04:00 UTC (06:00 CEST) -> Daylight (well before the old 08:00 / 06 UTC threshold!)
        dt_day_early = datetime(2026, 6, 21, 4, 0, tzinfo=timezone.utc)
        self.assertTrue(sun_utils.is_daylight(dt_day_early, self.lat, self.lon))

        # 12:00 UTC (14:00 CEST) -> Daylight
        dt_noon = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(sun_utils.is_daylight(dt_noon, self.lat, self.lon))

        # 19:30 UTC (21:30 CEST) -> Daylight (well after the old 20:00 / 18 UTC threshold!)
        dt_evening = datetime(2026, 6, 21, 19, 30, tzinfo=timezone.utc)
        self.assertTrue(sun_utils.is_daylight(dt_evening, self.lat, self.lon))

        # 21:00 UTC (23:00 CEST) -> Night
        dt_night_late = datetime(2026, 6, 21, 21, 0, tzinfo=timezone.utc)
        self.assertFalse(sun_utils.is_daylight(dt_night_late, self.lat, self.lon))

    def test_sun_utils_is_daylight_timestamp_input(self):
        dt = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        self.assertTrue(sun_utils.is_daylight(ts, self.lat, self.lon))

    def test_sun_utils_invalid_coords(self):
        self.assertIsNone(sun_utils.is_daylight(1700000000, None, None))
        self.assertIsNone(sun_utils.is_daylight(1700000000, "invalid", "coords"))

    def test_current_icon_astronomical_switch(self):
        # 04:00 UTC on June 21 in Stockholm is daytime (06:00 local)
        dt_day = datetime(2026, 6, 21, 4, 0, tzinfo=timezone.utc)
        ts_day = int(dt_day.timestamp())
        
        # Provider returns '01n' for daytime; should be converted to '01d'
        current_data = {'dt': ts_day, 'temp': 18.0, 'weather': [{'icon': '01n'}]}
        parsed = WeatherData(current_data, [], [], temp_unit_pref='C', lat=self.lat, lon=self.lon)
        self.assertEqual(parsed.current['weather_icon'], '01d')

        # 21:30 UTC on June 21 in Stockholm is nighttime (23:30 local)
        dt_night = datetime(2026, 6, 21, 21, 30, tzinfo=timezone.utc)
        ts_night = int(dt_night.timestamp())

        # Provider returns '01d' for nighttime; should be converted to '01n'
        current_data_night = {'dt': ts_night, 'temp': 12.0, 'weather': [{'icon': '01d'}]}
        parsed_night = WeatherData(current_data_night, [], [], temp_unit_pref='C', lat=self.lat, lon=self.lon)
        self.assertEqual(parsed_night.current['weather_icon'], '01n')

    def test_hourly_forecast_icons_astronomical_switch(self):
        # On 2026-06-21, sun rises ~01:31 UTC and sets ~20:07 UTC in Stockholm
        # Test hours across sunrise: 01:00 UTC (night), 02:00 UTC (day)
        # Test hours across sunset: 19:00 UTC (day), 21:00 UTC (night)
        hourly_pts = [
            HourlyDataPoint(dt=int(datetime(2026, 6, 21, 1, 0, tzinfo=timezone.utc).timestamp()), weather_icon="02d"),
            HourlyDataPoint(dt=int(datetime(2026, 6, 21, 2, 0, tzinfo=timezone.utc).timestamp()), weather_icon="02n"),
            HourlyDataPoint(dt=int(datetime(2026, 6, 21, 19, 0, tzinfo=timezone.utc).timestamp()), weather_icon="03n"),
            HourlyDataPoint(dt=int(datetime(2026, 6, 21, 21, 0, tzinfo=timezone.utc).timestamp()), weather_icon="03d"),
        ]
        
        parsed = WeatherData({'dt': hourly_pts[0].dt, 'temp': 15.0}, hourly_pts, [], temp_unit_pref='C', lat=self.lat, lon=self.lon)
        
        # Hour 1: 01:00 UTC is night -> '02d' should become '02n'
        self.assertEqual(parsed.hourly[0]['weather_icon'], '02n')
        # Hour 2: 02:00 UTC is day -> '02n' should become '02d'
        self.assertEqual(parsed.hourly[1]['weather_icon'], '02d')
        # Hour 3: 19:00 UTC is day (before sunset ~20:07 UTC) -> '03n' should become '03d'
        self.assertEqual(parsed.hourly[2]['weather_icon'], '03d')
        # Hour 4: 21:00 UTC is night (after sunset ~20:07 UTC) -> '03d' should become '03n'
        self.assertEqual(parsed.hourly[3]['weather_icon'], '03n')

if __name__ == '__main__':
    unittest.main()
