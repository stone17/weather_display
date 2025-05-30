# provider_owm.py
import json
import traceback
import aiohttp
from typing import Optional

from weather_provider_base import WeatherProvider, HourlyDataPoint, DailyDataPoint

def transform_owm_data(raw_json_data: dict) -> Optional[dict]:
    """Transforms raw OpenWeatherMap API response to the standardized format."""
    if not raw_json_data:
        return None

    transformed_data = {
        'lat': raw_json_data.get('lat'),
        'lon': raw_json_data.get('lon'),
        'timezone': raw_json_data.get('timezone'),
        'timezone_offset': raw_json_data.get('timezone_offset'),
        'current': raw_json_data.get('current'), # Current remains as is
        'hourly': [],
        'daily': []
    }

    # Transform hourly data
    for hour_data in raw_json_data.get('hourly', []):
        weather_info = hour_data.get('weather', [{}])[0]
        hourly_point = HourlyDataPoint(
            dt=hour_data.get('dt'),
            temp=hour_data.get('temp'),
            feels_like=hour_data.get('feels_like'),
            pressure=hour_data.get('pressure'),
            humidity=hour_data.get('humidity'),
            dew_point=hour_data.get('dew_point'),
            uvi=hour_data.get('uvi'),
            clouds=hour_data.get('clouds'),
            visibility=hour_data.get('visibility'),
            wind_speed=hour_data.get('wind_speed'),
            wind_deg=hour_data.get('wind_deg'),
            wind_gust=hour_data.get('wind_gust'),
            weather_id=weather_info.get('id'),
            weather_main=weather_info.get('main'),
            weather_description=weather_info.get('description'),
            weather_icon=weather_info.get('icon'),
            pop=hour_data.get('pop'),
            rain_1h=hour_data.get('rain', {}).get('1h'),
            snow_1h=hour_data.get('snow', {}).get('1h')
        )
        transformed_data['hourly'].append(hourly_point)

    # Transform daily data
    for day_data in raw_json_data.get('daily', []):
        weather_info = day_data.get('weather', [{}])[0]
        temp_info = day_data.get('temp', {})
        feels_like_info = day_data.get('feels_like', {})
        daily_point = DailyDataPoint(
            dt=day_data.get('dt'),
            sunrise=day_data.get('sunrise'),
            sunset=day_data.get('sunset'),
            moonrise=day_data.get('moonrise'),
            moonset=day_data.get('moonset'),
            moon_phase=day_data.get('moon_phase'),
            summary=day_data.get('summary'),
            temp_day=temp_info.get('day'),
            temp_min=temp_info.get('min'),
            temp_max=temp_info.get('max'),
            temp_night=temp_info.get('night'),
            temp_eve=temp_info.get('eve'),
            temp_morn=temp_info.get('morn'),
            feels_like_day=feels_like_info.get('day'),
            feels_like_night=feels_like_info.get('night'),
            feels_like_eve=feels_like_info.get('eve'),
            feels_like_morn=feels_like_info.get('morn'),
            pressure=day_data.get('pressure'),
            humidity=day_data.get('humidity'),
            dew_point=day_data.get('dew_point'),
            wind_speed=day_data.get('wind_speed'),
            wind_deg=day_data.get('wind_deg'),
            wind_gust=day_data.get('wind_gust'),
            weather_id=weather_info.get('id'),
            weather_main=weather_info.get('main'),
            weather_description=weather_info.get('description'),
            weather_icon=weather_info.get('icon'),
            clouds=day_data.get('clouds'),
            pop=day_data.get('pop'),
            rain=day_data.get('rain'),
            snow=day_data.get('snow'),
            uvi=day_data.get('uvi')
        )
        transformed_data['daily'].append(daily_point)

    return transformed_data

class OpenWeatherMapProvider(WeatherProvider):
    """Weather provider for OpenWeatherMap OneCall API."""
    def __init__(self, api_key, lat, lon, **kwargs):
        provider_id = kwargs.pop("provider_id_for_cache", "openweathermap") # Default if somehow missing
        super().__init__(lat, lon, provider_id_for_cache=provider_id, **kwargs)
        self.api_key = api_key
        self.provider_name = "OpenWeatherMap"
        if not api_key:
            raise ValueError("OpenWeatherMap API key is required.")

    async def _fetch_from_api(self):
        """Fetches data from OpenWeatherMap OneCall API."""
        print(f"Fetching data from {self.provider_name}...")
        url = (
            f"https://api.openweathermap.org/data/3.0/onecall"
            f"?lat={self.lat}&lon={self.lon}&appid={self.api_key}"
            f"&units=metric&exclude=minutely,alerts"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=30) as response:
                    response.raise_for_status()
                    print(f"{self.provider_name} data fetched successfully.")
                    raw_data = await response.json()
                    return transform_owm_data(raw_data)
            except aiohttp.ClientError as e:
                print(f"Error fetching {self.provider_name} data: {e} (URL: {url})")
                if response is not None: print(f"Response Body: {await response.text()}")
                return None
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                print(f"Error parsing {self.provider_name} data: {e}")
                # If raw_data was fetched, it might be useful to see it
                # if 'raw_data' in locals(): print(f"Raw data: {raw_data}")
                return None
            except Exception as e:
                 print(f"An unexpected error occurred during {self.provider_name} fetch: {e}")
                 traceback.print_exc()
                 return None