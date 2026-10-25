import unittest
import os
import sys
from datetime import datetime, timezone, timedelta

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TEST_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from weather_provider_base import get_weather_provider, calculate_feels_like
from providers.provider_metno import (
    MetNoProvider,
    transform_metno_data,
    get_owm_icon_from_metno_symbol,
    get_metno_description,
    strip_metno_symbol
)
from providers.provider_openmeteo import transform_open_meteo_data
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

        # Verify Fahrenheit conversion includes hourly feels_like
        wdata_f = WeatherData(
            transformed["current"],
            transformed["hourly"],
            transformed["daily"],
            "F",
            lat=59.9139,
            lon=10.7522
        )
        self.assertGreater(wdata_f.hourly[0]["feels_like"], 45.0)
        self.assertLess(wdata_f.hourly[0]["feels_like"], wdata_f.hourly[0]["temp"])

    def test_calculate_feels_like(self):
        # Wind chill at 5°C with 5 m/s (18 km/h) wind (~1.3°C)
        fl_cold = calculate_feels_like(5.0, 5.0, 70.0)
        self.assertLess(fl_cold, 5.0)
        self.assertAlmostEqual(fl_cold, 1.3, places=1)

        # Smooth transition between 10°C and 20°C (e.g. 15°C with 5 m/s wind)
        fl_mild = calculate_feels_like(15.0, 5.0, 60.0)
        self.assertLess(fl_mild, 15.0)
        self.assertGreater(fl_mild, 12.0)

        # Heat index at 32°C with 70% humidity (~40.6°C)
        fl_hot = calculate_feels_like(32.0, 1.0, 70.0)
        self.assertGreater(fl_hot, 32.0)

        # Calm at 22°C -> equals air temperature
        self.assertEqual(calculate_feels_like(22.0, 1.0, 40.0), 22.0)

    def test_openmeteo_current_feels_like_and_future_hours(self):
        now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        hourly_times = [(now_utc + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(-3, 24)]
        n_hours = len(hourly_times)
        om_json = {
            "current": {
                "time": now_utc.strftime("%Y-%m-%dT%H:%M"),
                "temperature_2m": 8.0,
                "relative_humidity_2m": 75.0,
                "apparent_temperature": 5.2,
                "weather_code": 2,
                "wind_speed_10m": 4.5,
                "wind_direction_10m": 210,
                "is_day": 1
            },
            "hourly": {
                "time": hourly_times,
                "temperature_2m": [8.0] * n_hours,
                "relative_humidity_2m": [75.0] * n_hours,
                "dew_point_2m": [3.9] * n_hours,
                "apparent_temperature": [5.2] * n_hours,
                "precipitation_probability": [10] * n_hours,
                "precipitation": [0.0] * n_hours,
                "weather_code": [2] * n_hours,
                "pressure_msl": [1012.0] * n_hours,
                "cloud_cover": [50] * n_hours,
                "visibility": [10000] * n_hours,
                "wind_speed_10m": [4.5] * n_hours,
                "wind_direction_10m": [210] * n_hours,
                "wind_gusts_10m": [7.0] * n_hours,
                "uv_index": [2.0] * n_hours
            },
            "daily": {
                "time": [now_utc.strftime("%Y-%m-%d")],
                "weather_code": [2],
                "temperature_2m_max": [12.0],
                "temperature_2m_min": [4.0],
                "apparent_temperature_max": [9.5],
                "apparent_temperature_min": [1.2],
                "sunrise": [(now_utc - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")],
                "sunset": [(now_utc + timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M")],
                "uv_index_max": [3.0],
                "precipitation_sum": [0.0],
                "precipitation_probability_max": [10],
                "wind_speed_10m_max": [5.0],
                "wind_gusts_10m_max": [8.0],
                "wind_direction_10m_dominant": [200]
            }
        }
        transformed = transform_open_meteo_data(om_json, 59.9139, 10.7522)
        self.assertIsNotNone(transformed)
        self.assertEqual(transformed["current"]["feels_like"], 5.2)
        self.assertEqual(transformed["current"]["humidity"], 75.0)
        # Past hours before (now - 1h) should be filtered out
        self.assertGreaterEqual(transformed["hourly"][0].dt, int(now_utc.timestamp()) - 3600)


if __name__ == "__main__":
    unittest.main()
