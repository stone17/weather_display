# provider_owm.py
import json
import traceback
import aiohttp

from weather_provider_base import WeatherProvider

class OpenWeatherMapProvider(WeatherProvider):
    """Weather provider for OpenWeatherMap OneCall API."""
    def __init__(self, api_key, lat, lon, **kwargs):
        super().__init__(lat, lon, **kwargs)
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
                    return await response.json()
            except aiohttp.ClientError as e:
                print(f"Error fetching {self.provider_name} data: {e} (URL: {url})")
                if response is not None: print(f"Response Body: {await response.text()}")
                return None
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                print(f"Error parsing {self.provider_name} data: {e}")
                return None
            except Exception as e:
                 print(f"An unexpected error occurred during {self.provider_name} fetch: {e}")
                 traceback.print_exc()
                 return None