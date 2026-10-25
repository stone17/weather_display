import unittest
import os
import sys
from datetime import datetime, timezone, timedelta

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TEST_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from weather_provider_base import get_weather_provider
from providers.provider_metno import (
    MetNoProvider,
    transform_metno_data,
    get_owm_icon_from_metno_symbol,
    get_metno_description,
    strip_metno_symbol
)
from weather_data_parser import WeatherData


class TestMetNoProvider(unittest.TestCase):
    def test_symbol_mappings(self):
        self.assertEqual(strip_metno_symbol("clearsky_day"), "clearsky")
        self.assertEqual(strip_metno_symbol("partlycloudy_night"), "partlycloudy")
        self.assertEqual(strip_metno_symbol("fair_polar_twilight"), "fair")
        self.assertEqual(strip_metno_symbol("rain"), "rain")

        self.assertEqual(get_owm_icon_from_metno_symbol("clearsky_day"), "01d")
        self.assertEqual(get_owm_icon_from_metno_symbol("clearsky_night"), "01n")
        self.assertEqual(get_owm_icon_from_metno_symbol("heavyrainandthunder"), "11d")
        self.assertEqual(get_owm_icon_from_metno_symbol("lightsnow_night"), "13n")
        self.assertEqual(get_owm_icon_from_metno_symbol("fog"), "50d")
        self.assertEqual(get_owm_icon_from_metno_symbol("unknown_code"), "na")

        self.assertEqual(get_metno_description("partlycloudy_day"), "Partly cloudy")
        self.assertEqual(get_metno_description("rainshowers_night"), "Rain showers")

    def test_factory_registration(self):
        cfg = {
            "weather_provider": "metno",
            "latitude": 59.9139,
            "longitude": 10.7522,
            "supplemental_providers": []
        }
        provider = get_weather_provider(cfg, PROJECT_ROOT)
        self.assertIsNotNone(provider)
        self.assertIsInstance(provider, MetNoProvider)
        self.assertEqual(provider.provider_name, "MET Norway")

    def test_transform_metno_data_and_weather_data_parser(self):
        now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        timeseries = []
        for h in range(48):
            dt = now_utc + timedelta(hours=h)
            time_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            is_day = 6 <= dt.hour < 18
            symbol = "partlycloudy_day" if is_day else "clearsky_night"
            timeseries.append({
                "time": time_iso,
                "data": {
                    "instant": {
                        "details": {
                            "air_pressure_at_sea_level": 1015.2,
                            "air_temperature": 12.5 + (h % 5),
                            "cloud_area_fraction": 40.0,
                            "dew_point_temperature": 5.0,
                            "relative_humidity": 65.4,
                            "ultraviolet_index_clear_sky": 3.2 if is_day else 0.0,
                            "wind_from_direction": 180.0,
                            "wind_speed": 4.2,
                            "wind_speed_of_gust": 7.5
                        }
                    },
                    "next_1_hours": {
                        "summary": {"symbol_code": symbol},
                        "details": {
                            "precipitation_amount": 0.4 if h % 6 == 0 else 0.0,
                            "probability_of_precipitation": 30.0
                        }
                    },
                    "next_6_hours": {
                        "summary": {"symbol_code": symbol},
                        "details": {
                            "air_temperature_max": 18.0,
                            "air_temperature_min": 10.0,
                            "precipitation_amount": 1.2,
                            "probability_of_precipitation": 40.0
                        }
                    }
                }
            })

        sample_json = {
            "type": "Feature",
            "properties": {
                "timeseries": timeseries
            }
        }

        transformed = transform_metno_data(sample_json, 59.9139, 10.7522)
        self.assertIsNotNone(transformed)
        self.assertIn("current", transformed)
        self.assertTrue(len(transformed["hourly"]) >= 24)
        self.assertTrue(len(transformed["daily"]) >= 2)

        # Verify daily day/night icons
        day0 = transformed["daily"][0]
        self.assertTrue(day0.weather_icon_day.endswith("d"))
        self.assertTrue(day0.weather_icon_night.endswith("n"))
        self.assertEqual(day0.temp_max, 18.0)
        self.assertEqual(day0.temp_min, 10.0)

        # Verify integration with WeatherData parser
        wdata = WeatherData(
            transformed["current"],
            transformed["hourly"],
            transformed["daily"],
            "C",
            lat=59.9139,
            lon=10.7522
        )
        self.assertTrue(wdata.has_sufficient_data())
        self.assertIn("°C", wdata.current["temp_display"])


if __name__ == "__main__":
    unittest.main()
