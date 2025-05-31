# provider_google.py
import json
from datetime import datetime, timezone
import traceback
import aiohttp

from weather_provider_base import WeatherProvider, parse_iso_time, parse_google_date, HourlyDataPoint, DailyDataPoint

# --- Google Weather Condition Mappings ---
GOOGLE_CONDITION_TO_OWM_ICON = {
    "CLEAR": "01",
    "CLOUDY": "03",
    "FOG": "50",
    "HAZE": "50",
    "HEAVY_RAIN": "09",
    "MOSTLY_CLEAR": "01",
    "PARTLY_CLOUDY": "02",
    "RAIN": "10",
    "LIGHT_RAIN": "10",
    "RAIN_SHOWERS": "09",
    "SCATTERED_SHOWERS": "09",
    "SLEET": "13",
    "SNOW": "13",
    "SNOW_LIGHT": "13",
    "SNOW_SHOWERS": "13",
    "SQUALL": "11",
    "THUNDERSTORM": "11",
    "MOSTLY_CLOUDY": "04",
    "SCATTERED_THUNDERSTORMS": "11",
    "SMOKE": "50",
    "DUST": "50",
    "WINDY": "01",
    "DRIZZLE": "10",
    "ICY": "13",
    "HAIL": "09",
    "CONDITION_UNSPECIFIED": "01",
}
GOOGLE_CONDITION_DESC = {
    "CLEAR": "Clear",
    "CLOUDY": "Cloudy",
    "FOG": "Fog",
    "HAZE": "Haze",
    "HEAVY_RAIN": "Heavy Rain",
    "MOSTLY_CLEAR": "Mostly Clear",
    "PARTLY_CLOUDY": "Partly Cloudy",
    "RAIN": "Rain",
    "LIGHT_RAIN": "Light Rain",
    "RAIN_SHOWERS": "Rain Showers",
    "SCATTERED_SHOWERS": "Scattered Showers",
    "SLEET": "Sleet",
    "SNOW": "Snow",
    "SNOW_LIGHT": "Light Snow",
    "SNOW_SHOWERS": "Snow Showers",
    "SQUALL": "Squall",
    "THUNDERSTORM": "Thunderstorm",
    "MOSTLY_CLOUDY": "Mostly Cloudy",
    "SCATTERED_THUNDERSTORMS": "Scattered T-Storms",
    "SMOKE": "Smoke",
    "DUST": "Dust",
    "WINDY": "Windy",
    "DRIZZLE": "Drizzle",
    "ICY": "Icy",
    "HAIL": "Hail",
    "CONDITION_UNSPECIFIED": "Unknown",
}

def get_owm_icon_from_google_code(code, is_day=True):
    base_icon = GOOGLE_CONDITION_TO_OWM_ICON.get(code, 'na')
    return base_icon + ('d' if is_day else 'n') if base_icon != 'na' else 'na'

def get_google_code_description(code):
    return GOOGLE_CONDITION_DESC.get(code, 'Unknown')

def transform_google_weather_data(google_raw_data, lat, lon):
    if not google_raw_data or not all(k in google_raw_data for k in ['current', 'hourly', 'daily']):
        return None
    current_raw = google_raw_data.get('current', {}); hourly_raw = google_raw_data.get('hourly', {}); daily_raw = google_raw_data.get('daily', {})
    tz_name = daily_raw.get('timeZone', {}).get('id') or current_raw.get('timeZone', {}).get('id', 'UTC')
    transformed_data = {'lat': lat, 'lon': lon, 'timezone': tz_name, 'timezone_offset': 0,
                        'current': {}, 'hourly': [], 'daily': []}
    cc = current_raw
    current_ts = parse_iso_time(cc.get('currentTime')) or int(datetime.now(timezone.utc).timestamp())
    temp = cc.get('temperature', {}).get('degrees', 0.0)
    condition_code = cc.get('weatherCondition', {}).get('type', 'CONDITION_UNSPECIFIED')
    description = cc.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
    owm_icon = get_owm_icon_from_google_code(condition_code, cc.get('isDaytime', True))
    transformed_data['current'] = {
        'dt': current_ts, 'sunrise': 0, 'sunset': 0, 'temp': temp,
        'feels_like': cc.get('feelsLikeTemperature', {}).get('degrees', temp),
        'pressure': cc.get('airPressure', {}).get('meanSeaLevelMillibars', 1013.0),
        'humidity': cc.get('relativeHumidity', 50), 'dew_point': cc.get('dewPoint', {}).get('degrees', 0.0),
        'uvi': cc.get('uvIndex', 0), 'clouds': cc.get('cloudCover', 50),
        'visibility': int(cc.get('visibility', {}).get('distance', 10.0) * 1000),
        'wind_speed': round(cc.get('wind', {}).get('speed', {}).get('value', 0.0) / 3.6, 2),
        'wind_deg': cc.get('wind', {}).get('direction', {}).get('degrees', 0),
        'wind_gust': round(cc.get('wind', {}).get('gust', {}).get('value', 0.0) / 3.6, 2),
        'weather': [{'id': 0, 'main': description.split()[0], 'description': description, 'icon': owm_icon,
                     'google_icon_uri': cc.get('weatherCondition', {}).get('iconBaseUri')}],
        'rain': {'1h': cc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0)},
        'pop': cc.get('precipitation', {}).get('probability', {}).get('percent', 0) / 100.0
    }
    for hour_fc in hourly_raw.get('forecastHours', []):
        ts_h = parse_iso_time(hour_fc.get('interval', {}).get('startTime'))
        if ts_h == 0: continue
        temp_h = hour_fc.get('temperature', {}).get('degrees', 0.0)
        condition_code_h = hour_fc.get('weatherCondition', {}).get('type', 'CONDITION_UNSPECIFIED')
        description_h = hour_fc.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
        owm_icon_h = get_owm_icon_from_google_code(condition_code_h, hour_fc.get('isDaytime', True))

        hourly_point = HourlyDataPoint(
            dt=ts_h,
            temp=temp_h,
            feels_like=hour_fc.get('feelsLikeTemperature', {}).get('degrees', temp_h),
            pressure=hour_fc.get('airPressure', {}).get('meanSeaLevelMillibars', 1013.0),
            humidity=hour_fc.get('relativeHumidity', 50),
            dew_point=hour_fc.get('dewPoint', {}).get('degrees', 0.0),
            uvi=float(hour_fc.get('uvIndex', 0)),
            clouds=hour_fc.get('cloudCover', 50),
            visibility=int(hour_fc.get('visibility', {}).get('distance', 10.0) * 1000),
            wind_speed=round(hour_fc.get('wind', {}).get('speed', {}).get('value', 0.0) / 3.6, 2),
            wind_deg=hour_fc.get('wind', {}).get('direction', {}).get('degrees', 0),
            wind_gust=round(hour_fc.get('wind', {}).get('gust', {}).get('value', 0.0) / 3.6, 2),
            weather_main=description_h.split()[0] if description_h else "Unknown",
            weather_description=description_h,
            weather_icon=owm_icon_h,
            weather_google_icon_uri=hour_fc.get('weatherCondition', {}).get('iconBaseUri'),
            rain_1h=hour_fc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0),
            pop=hour_fc.get('precipitation', {}).get('probability', {}).get('percent', 0) / 100.0
        )
        transformed_data['hourly'].append(hourly_point)
    transformed_data['hourly'] = transformed_data['hourly'][:48]
    for day_fc in daily_raw.get('forecastDays', []):
        day_ts = parse_google_date(day_fc.get('displayDate'))
        if day_ts == 0: continue
        temp_max = day_fc.get('maxTemperature', {}).get('degrees', 0.0)
        temp_min = day_fc.get('minTemperature', {}).get('degrees', 0.0)
        daytime_fc = day_fc.get('daytimeForecast', {})
        nighttime_fc = day_fc.get('nighttimeForecast', {}) # Used for precip sum
        active_fc = daytime_fc if daytime_fc else nighttime_fc # Prioritize daytime for general info
        if not active_fc: continue # Skip if no forecast data for the day

        condition_code_d = active_fc.get('weatherCondition', {}).get('type', 'CONDITION_UNSPECIFIED')
        description_d = active_fc.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
        owm_icon_d = get_owm_icon_from_google_code(condition_code_d, True) # Assume day for daily icon
        precip_total_mm = daytime_fc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0) + \
                          nighttime_fc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0)

        daily_point = DailyDataPoint(
            dt=day_ts,
            sunrise=parse_iso_time(day_fc.get('sunEvents', {}).get('sunriseTime')),
            sunset=parse_iso_time(day_fc.get('sunEvents', {}).get('sunsetTime')),
            summary=description_d,
            temp_day=(temp_max + temp_min) / 2 if temp_max is not None and temp_min is not None else None,
            temp_min=temp_min,
            temp_max=temp_max,
            temp_night=temp_min, # Approximation
            temp_eve=temp_min,   # Approximation
            temp_morn=temp_min,  # Approximation
            feels_like_day=day_fc.get('feelsLikeMaxTemperature', {}).get('degrees', temp_max),
            feels_like_night=day_fc.get('feelsLikeMinTemperature', {}).get('degrees', temp_min),
            humidity=active_fc.get('relativeHumidity', 50),
            wind_speed=round(active_fc.get('wind', {}).get('speed', {}).get('value', 0.0) / 3.6, 2),
            wind_deg=active_fc.get('wind', {}).get('direction', {}).get('degrees', 0),
            wind_gust=round(active_fc.get('wind', {}).get('gust', {}).get('value', 0.0) / 3.6, 2),
            weather_main=description_d.split()[0] if description_d else "Unknown",
            weather_description=description_d,
            weather_icon=owm_icon_d,
            weather_google_icon_uri=active_fc.get('weatherCondition', {}).get('iconBaseUri'),
            clouds=active_fc.get('cloudCover', 50),
            pop=active_fc.get('precipitation', {}).get('probability', {}).get('percent', 0) / 100.0,
            rain=precip_total_mm,
            uvi=float(active_fc.get('uvIndex', 0))
            # pressure, dew_point not directly available for daily
        )
        transformed_data['daily'].append(daily_point)
    transformed_data['daily'] = transformed_data['daily'][:8]
    if transformed_data['daily'] and transformed_data['current']:
        first_daily_dp = transformed_data['daily'][0]
        # Access attributes directly and provide a default if None
        transformed_data['current']['sunrise'] = first_daily_dp.sunrise if first_daily_dp.sunrise is not None else 0
        transformed_data['current']['sunset'] = first_daily_dp.sunset if first_daily_dp.sunset is not None else 0
        # Also, ensure UVI from daily is considered if current doesn't have it or if daily is more accurate
        if transformed_data['current'].get('uvi') == 0 and first_daily_dp.uvi is not None: # Example logic
            transformed_data['current']['uvi'] = first_daily_dp.uvi
    return transformed_data

class GoogleWeatherProvider(WeatherProvider):
    def __init__(self, api_key, lat, lon, **kwargs):
        provider_id = kwargs.pop("provider_id_for_cache", "google") # Default if somehow missing
        super().__init__(lat, lon, provider_id_for_cache=provider_id, **kwargs)
        self.api_key = api_key
        self.provider_name = "Google Weather"
        self.base_url = "https://weather.googleapis.com/v1"
        if not api_key:
            raise ValueError("Google Maps Platform API key is required.")

    async def _fetch_from_api(self):
        print(f"Fetching data from {self.provider_name}...")
        print("!!! WARNING: Google Weather API usage may incur costs. !!!")
        base_lookup_params = {"key": self.api_key, "location.latitude": self.lat, "location.longitude": self.lon}
        raw_data = {}
        endpoint_paths = {'current': '/currentConditions:lookup', 'hourly': '/forecast/hours:lookup', 'daily': '/forecast/days:lookup'}
        success = True
        async with aiohttp.ClientSession() as session:
            for key, path_suffix in endpoint_paths.items():
                url = f"{self.base_url}{path_suffix}"
                request_params = base_lookup_params.copy()
                if key == 'hourly': request_params['hours'] = 48
                elif key == 'daily': request_params['days'] = 8
                print(f"Requesting {key} data from Google: {url} with params: {request_params}")
                response = None
                try:
                    async with session.get(url, params=request_params, timeout=30) as response:
                        print(f"Google {key} Response Status Code: {response.status}")
                        response.raise_for_status()
                        raw_data[key] = await response.json()
                        print(f"Google {key} data fetched successfully.")
                except aiohttp.ClientError as e:
                    print(f"Error fetching Google {key} data: {e}")
                    if response: print(f"Response Body: {await response.text()}")
                    success = False; break
                except json.JSONDecodeError as e:
                    print(f"Error decoding Google {key} JSON response: {e}")
                    if response: print(f"Response Text: {await response.text()}")
                    success = False; break
                except Exception as e:
                    print(f"An unexpected error occurred during Google {key} fetch: {e}")
                    traceback.print_exc(); success = False; break
        if not success: return None
        if 'current' not in raw_data: print("Error: Current conditions data missing from Google response."); return None
        raw_data.setdefault('hourly', {}); raw_data.setdefault('daily', {})
        return transform_google_weather_data(raw_data, self.lat, self.lon)