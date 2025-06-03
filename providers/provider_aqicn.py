# provider_aqicn.py
import json
import traceback
from datetime import datetime, timezone # Ensure datetime and timezone are imported
import aiohttp
from typing import Optional, Dict, Any

from weather_provider_base import WeatherProvider, HourlyDataPoint, DailyDataPoint # For type hinting if needed

def transform_aqicn_data(raw_json_data: Dict[str, Any], lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Transforms raw AQICN API response to the standardized format."""
    if not raw_json_data or raw_json_data.get("status") != "ok" or "data" not in raw_json_data:
        print(f"Error: Invalid or unsuccessful data received from AQICN: {raw_json_data.get('status')}")
        return None

    api_data = raw_json_data["data"]
    aqi_value = api_data.get("aqi")
    dominant_pollutant = api_data.get("dominentpol") # Note: API uses "dominentpol"
    # print(api_data) # Keep for debugging if needed
    # AQICN primarily provides current AQI. We'll populate the 'current' part.
    # Other parts (hourly, daily) will be empty unless combined with another provider.
    current_data = {
        "dt": api_data.get("time", {}).get("v", 0), # Unix timestamp if available
        "aqi": int(aqi_value) if isinstance(aqi_value, (int, float, str)) and str(aqi_value).isdigit() else None,
        "dominant_pollutant": str(dominant_pollutant) if dominant_pollutant else None,
        # Add other relevant current weather fields as None or default if AQICN is primary
        "temp": None,
        "feels_like": None,
        "pressure": None,
        "humidity": None,
        "uvi": None,
        "wind_speed": None,
        "wind_deg": None,
        "weather": [{'id': None, 'main': 'AQI', 'description': f"AQI: {aqi_value}", 'icon': 'na'}],
        "sunrise": 0, # Placeholder
        "sunset": 0   # Placeholder
    }

    transformed_data = {
        'lat': lat,
        'lon': lon,
        'timezone': api_data.get("city", {}).get("tz", "UTC"), # Or determine based on lat/lon
        'timezone_offset': 0, # AQICN doesn't directly provide this in a standard way
        'current': current_data,
        'hourly': []
    }

    # --- Add Daily AQI Forecast Parsing ---
    daily_forecasts_transformed = []
    daily_forecast_data = api_data.get("forecast", {}).get("daily", {})

    if daily_forecast_data and "pm25" in daily_forecast_data:
        for pm25_forecast_day in daily_forecast_data["pm25"]:
            day_str = pm25_forecast_day.get("day")
            avg_pm25 = pm25_forecast_day.get("avg")

            if day_str:
                try:
                    # Parse "YYYY-MM-DD" string to a datetime object at UTC midnight
                    year, month, day_val = map(int, day_str.split('-'))
                    dt_obj_utc_midnight = datetime(year, month, day_val, 0, 0, 0, tzinfo=timezone.utc)
                    day_timestamp = int(dt_obj_utc_midnight.timestamp())

                    daily_point = DailyDataPoint(
                        dt=day_timestamp,
                        aqi_pm25_avg=int(avg_pm25) if avg_pm25 is not None else None
                        # Other DailyDataPoint fields will be None or default
                    )
                    daily_forecasts_transformed.append(daily_point)
                except ValueError as e:
                    print(f"Warning: Could not parse AQICN forecast day string '{day_str}': {e}")

    transformed_data['daily'] = daily_forecasts_transformed
    return transformed_data

class AQICNProvider(WeatherProvider):
    """Weather provider for AQICN API."""
    def __init__(self, api_key: str, lat: float, lon: float, **kwargs):
        provider_id = kwargs.pop("provider_id_for_cache", "aqicn")
        super().__init__(lat, lon, provider_id_for_cache=provider_id, **kwargs)
        self.api_key = api_key
        self.provider_name = "AQICN"
        if not api_key:
            raise ValueError("AQICN API token is required.")

    async def _fetch_from_api(self) -> Optional[Dict[str, Any]]:
        """Fetches data from AQICN API."""
        print(f"Fetching data from {self.provider_name}...")
        # Geolocalized feed: https://aqicn.org/json-api/doc/#api-Geolocalized_Feed-GetGeolocFeed
        url = f"https://api.waqi.info/feed/geo:{self.lat};{self.lon}/?token={self.api_key}"

        async with aiohttp.ClientSession() as session:
            response_obj = None # To store response for logging in case of JSON error
            try:
                async with session.get(url, timeout=30) as response:
                    response_obj = response
                    response.raise_for_status()
                    print(f"{self.provider_name} data fetched successfully.")
                    raw_data = await response.json()
                    return transform_aqicn_data(raw_data, self.lat, self.lon)
            except aiohttp.ClientError as e:
                print(f"Error fetching {self.provider_name} data: {e} (URL: {url})")
                if response_obj: print(f"Response Body: {await response_obj.text()}")
                return None
            except json.JSONDecodeError as e:
                print(f"Error parsing {self.provider_name} JSON data: {e}")
                if response_obj: print(f"Response Text: {await response_obj.text()}")
                return None
            except Exception as e:
                print(f"An unexpected error occurred during {self.provider_name} fetch: {e}")
                traceback.print_exc()
                return None