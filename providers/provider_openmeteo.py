# provider_openmeteo.py
import json
from datetime import datetime, timezone
import traceback
import aiohttp

from weather_provider_base import WeatherProvider, parse_iso_time, HourlyDataPoint, DailyDataPoint

# --- Open-Meteo WMO CODE Mappings ---
WMO_CODE_TO_OWM_ICON = {
    0: '01d', 1: '02d', 2: '03d', 3: '04d', 45: '50d', 48: '50d', 51: '10d',
    53: '10d', 55: '09d', 56: '10d', 57: '09d', 61: '10d', 63: '09d', 65: '09d',
    66: '10d', 67: '09d', 71: '13d', 73: '13d', 75: '13d', 77: '13d', 80: '09d',
    81: '09d', 82: '09d', 85: '13d', 86: '13d', 95: '11d', 96: '11d', 99: '11d',
    1000: '01n', 1001: '02n', 1002: '03n', 1003: '04n', 1045: '50n', 1048: '50n',
    1051: '10n', 1053: '10n', 1055: '09n', 1056: '10n', 1057: '09n', 1061: '10n',
    1063: '09n', 1065: '09n', 1066: '10n', 1067: '09n', 1071: '13n', 1073: '13n',
    1075: '13n', 1077: '13n', 1080: '09n', 1081: '09n', 1082: '09n', 1085: '13n',
    1086: '13n', 1095: '11n', 1096: '11n', 1099: '11n',
}
WMO_CODE_DESC = {
    0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Depositing rime fog', 51: 'Light drizzle', 53: 'Drizzle',
    55: 'Dense drizzle', 56: 'Light freezing drizzle', 57: 'Freezing drizzle',
    61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Light freezing rain',
    67: 'Freezing rain', 71: 'Light snow', 73: 'Snow', 75: 'Heavy snow',
    77: 'Snow grains', 80: 'Light showers', 81: 'Showers', 82: 'Heavy showers',
    85: 'Light snow showers', 86: 'Snow showers', 95: 'Thunderstorm',
    96: 'Thunderstorm, light hail', 99: 'Thunderstorm, heavy hail',
}

def get_wmo_code_description(code):
    return WMO_CODE_DESC.get(code, 'Unknown')

def get_owm_icon_from_wmo_code(code, is_day=1):
    icon = WMO_CODE_TO_OWM_ICON.get(code, 'na')
    if icon != 'na': icon = icon.replace('d' if is_day == 0 else 'n', 'n' if is_day == 0 else 'd')
    return icon

def transform_open_meteo_data(om_json, lat, lon):
    if not om_json: return None
    tz_offset = om_json.get('utc_offset_seconds', 0)
    tz_name = om_json.get('timezone', 'UTC')
    transformed_data = {'lat': lat, 'lon': lon, 'timezone': tz_name, 'timezone_offset': tz_offset,
                        'current': {}, 'hourly': [], 'daily': []}
    current = om_json.get('current_weather')
    if current:
        current_ts = parse_iso_time(current.get('time'))
        current_temp = current.get('temperature')
        current_icon = get_owm_icon_from_wmo_code(current.get('weather_code', 0), current.get('is_day', 1))
        current_desc = get_wmo_code_description(current.get('weather_code', 0))
        transformed_data['current'] = {
            'dt': current_ts, 'sunrise': 0, 'sunset': 0, 'temp': current_temp,
            'feels_like': current.get('apparent_temperature', current_temp),
            'pressure': current.get('pressure_msl', 1013), 'humidity': current.get('relative_humidity_2m', 50),
            'dew_point': 0, 'uvi': 0, 'clouds': current.get('cloud_cover', 50), 'visibility': 10000,
            'wind_speed': current.get('wind_speed_10m', 0), 'wind_deg': current.get('wind_direction_10m', 0),
            'wind_gust': current.get('wind_gusts_10m', 0),
            'weather': [{'id': current.get('weather_code', 0), 'main': current_desc.split()[0], 'description': current_desc, 'icon': current_icon}],
            'rain': {'1h': current.get('rain', 0.0)}, 'snow': {'1h': current.get('snowfall', 0.0)}
        }
    hourly = om_json.get('hourly')
    if hourly and 'time' in hourly:
        num_hours = len(hourly['time'])
        def get_hourly_val(key, idx, default=None):
            val = hourly.get(key, [])[idx] if idx < len(hourly.get(key, [])) else default
            if val is None: return default
            if isinstance(default, int) and isinstance(val, float): return int(val)
            return val
        for i in range(num_hours):
            ts = parse_iso_time(hourly['time'][i])
            if ts == 0: continue
            temp = get_hourly_val('temperature_2m', i, 0.0)
            weather_code = get_hourly_val('weather_code', i, 0)
            is_day = get_hourly_val('is_day', i, 1 if 6 <= datetime.fromtimestamp(ts, tz=timezone.utc).hour < 18 else 0)
            icon = get_owm_icon_from_wmo_code(weather_code, is_day)
            description = get_wmo_code_description(weather_code)
            pop_val = get_hourly_val('precipitation_probability', i)
            pop = pop_val / 100.0 if pop_val is not None else None

            hourly_point = HourlyDataPoint(
                dt=ts,
                temp=temp,
                feels_like=get_hourly_val('apparent_temperature', i, temp),
                pressure=get_hourly_val('pressure_msl', i, 1013.0),
                humidity=get_hourly_val('relative_humidity_2m', i, 50),
                # dew_point not directly requested/available
                uvi=get_hourly_val('uv_index', i, 0.0),
                clouds=get_hourly_val('cloud_cover', i, 50),
                visibility=get_hourly_val('visibility', i, 10000),
                wind_speed=get_hourly_val('wind_speed_10m', i, 0.0),
                wind_deg=get_hourly_val('wind_direction_10m', i, 0),
                wind_gust=get_hourly_val('wind_gusts_10m', i, 0.0),
                weather_id=weather_code,
                weather_main=description.split()[0] if description else "Unknown",
                weather_description=description,
                weather_icon=icon,
                pop=pop,
                rain_1h=get_hourly_val('rain', i, 0.0) or get_hourly_val('precipitation', i, 0.0),
                snow_1h=get_hourly_val('snowfall', i, 0.0)
            )
            transformed_data['hourly'].append(hourly_point)
        if transformed_data['hourly'] and transformed_data['current'] and transformed_data['hourly'][0].uvi is not None:
             transformed_data['current']['uvi'] = transformed_data['hourly'][0].uvi
    transformed_data['hourly'] = transformed_data['hourly'][:48]
    daily = om_json.get('daily')
    if daily and 'time' in daily:
        num_days = len(daily['time'])
        def get_daily_val(key, idx, default=None):
            val = daily.get(key, [])[idx] if idx < len(daily.get(key, [])) else default
            if val is None: return default
            if isinstance(default, int) and isinstance(val, float): return int(val)
            return val
        for i in range(num_days):
            day_ts_str = daily['time'][i]
            try:
                date_part_str = day_ts_str.split('T')[0]
                year, month, day_val = map(int, date_part_str.split('-'))
                day_ts = int(datetime(year, month, day_val, 0, 0, 0, tzinfo=timezone.utc).timestamp())
            except ValueError:
                print(f"Warning: Could not parse date string '{day_ts_str}' for Open-Meteo daily dt. Skipping.")
                continue
            temp_max = get_daily_val('temperature_2m_max', i, 0.0)
            temp_min = get_daily_val('temperature_2m_min', i, 0.0)
            weather_code = get_daily_val('weather_code', i, 0)
            daily_icon = get_owm_icon_from_wmo_code(weather_code, 1)
            daily_desc = get_wmo_code_description(weather_code)
            pop_max_val = get_daily_val('precipitation_probability_max', i)

            daily_point = DailyDataPoint(
                dt=day_ts,
                sunrise=parse_iso_time(get_daily_val('sunrise', i)),
                sunset=parse_iso_time(get_daily_val('sunset', i)),
                summary=daily_desc,
                temp_day=(temp_max + temp_min) / 2 if temp_max is not None and temp_min is not None else None,
                temp_min=temp_min,
                temp_max=temp_max,
                temp_night=temp_min, # Approximation
                temp_eve=temp_min,   # Approximation
                temp_morn=temp_min,  # Approximation
                feels_like_day=get_daily_val('apparent_temperature_max', i, temp_max),
                feels_like_night=get_daily_val('apparent_temperature_min', i, temp_min),
                # pressure, humidity, dew_point not directly requested for daily
                wind_speed=get_daily_val('wind_speed_10m_max', i, 0.0),
                wind_deg=get_daily_val('wind_direction_10m_dominant', i, 0),
                wind_gust=get_daily_val('wind_gusts_10m_max', i, 0.0),
                weather_id=weather_code,
                weather_main=daily_desc.split()[0] if daily_desc else "Unknown",
                weather_description=daily_desc,
                weather_icon=daily_icon,
                # clouds not directly requested for daily
                pop=pop_max_val / 100.0 if pop_max_val is not None else None,
                rain=get_daily_val('precipitation_sum', i, 0.0),
                snow=get_daily_val('snowfall_sum', i, 0.0), # snowfall_sum is available
                uvi=get_daily_val('uv_index_max', i, 0.0)
            )
            transformed_data['daily'].append(daily_point)
            if i == 0 and transformed_data['current']:
                transformed_data['current']['sunrise'] = parse_iso_time(get_daily_val('sunrise', i))
                transformed_data['current']['sunset'] = parse_iso_time(get_daily_val('sunset', i))
    transformed_data['daily'] = transformed_data['daily'][:8]
    return transformed_data

class OpenMeteoProvider(WeatherProvider):
    def __init__(self, lat, lon, **kwargs):
        provider_id = kwargs.pop("provider_id_for_cache", "open-meteo") # Default if somehow missing
        super().__init__(lat, lon, provider_id_for_cache=provider_id, **kwargs)
        self.provider_name = "Open-Meteo"

    async def _fetch_from_api(self):
        print(f"Fetching data from {self.provider_name}...")
        base_url = "https://api.open-meteo.com/v1/forecast"
        params = { "latitude": self.lat, "longitude": self.lon, "current_weather": "true",
                   "temperature_unit": "celsius", "wind_speed_unit": "ms", "precipitation_unit": "mm",
                   "timezone": "auto", "forecast_days": 7,
                   "hourly": ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "precipitation_probability",
                              "precipitation", "rain", "snowfall", "weather_code", "pressure_msl", "cloud_cover",
                              "visibility", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "uv_index", "is_day"],
                   "daily": ["weather_code", "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
                             "apparent_temperature_min", "sunrise", "sunset", "uv_index_max", "precipitation_sum",
                             "rain_sum", "snowfall_sum", "precipitation_probability_max", "wind_speed_10m_max",
                             "wind_gusts_10m_max", "wind_direction_10m_dominant"]}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(base_url, params=params, timeout=30) as response:
                    print(f"Open-Meteo Response Status Code: {response.status}")
                    response.raise_for_status()
                    raw_data = await response.json()
                    print(f"{self.provider_name} raw data fetched successfully.")
                    return transform_open_meteo_data(raw_data, self.lat, self.lon)
            except aiohttp.ClientError as e:
                print(f"Error fetching {self.provider_name} data: {e}")
                if response is not None: print(f"Response Body: {await response.text()}")
                return None
            except json.JSONDecodeError as e:
                print(f"Error decoding {self.provider_name} JSON response: {e}")
                if response is not None: print(f"Response Text: {await response.text()}")
                return None
            except Exception as e:
                print(f"An unexpected error occurred during {self.provider_name} fetch/transform: {e}")
                traceback.print_exc()
                return None