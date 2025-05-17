# provider_meteomatics.py
import json
from datetime import datetime, timedelta, timezone
import math
import traceback
import aiohttp

from ..weather_provider_base import WeatherProvider, parse_iso_time

# --- Meteomatics SYMBOL Mappings ---
METEOMATICS_TO_OWM_ICON = {
    1: '01d', 1001: '01n', 2: '02d', 1002: '02n', 3: '03d', 1003: '03n',
    4: '04d', 1004: '04n', 5: '50d', 1005: '50n', 10: '10d', 1010: '10n',
    11: '10d', 1011: '10n', 12: '09d', 1012: '09n', 13: '09d', 1013: '09n',
    14: '10d', 1014: '10n', 15: '10d', 1015: '10n', 16: '09d', 1016: '09n',
    20: '13d', 1020: '13n', 21: '13d', 1021: '13n', 22: '13d', 1022: '13n',
    23: '13d', 1023: '13n', 24: '13d', 1024: '13n', 25: '13d', 1025: '13n',
    26: '09d', 1026: '09n', 27: '09d', 1027: '09n', 28: '09d', 1028: '09n',
    30: '11d', 1030: '11n', 31: '11d', 1031: '11n', 32: '11d', 1032: '11n', 0: 'na',
}
METEOMATICS_SYMBOL_DESC = {
    1: 'Clear sky', 1001: 'Clear sky', 2: 'Partly cloudy', 1002: 'Partly cloudy',
    3: 'Cloudy', 1003: 'Cloudy', 4: 'Overcast', 1004: 'Overcast', 5: 'Fog', 1005: 'Fog',
    10: 'Light rain', 1010: 'Light rain', 11: 'Rain', 1011: 'Rain',
    12: 'Heavy rain', 1012: 'Heavy rain', 13: 'Heavy rain', 1013: 'Heavy rain',
    14: 'Light freezing rain', 1014: 'Light freezing rain', 15: 'Freezing rain', 1015: 'Freezing rain',
    16: 'Heavy freezing rain', 1016: 'Heavy freezing rain', 20: 'Light snow', 1020: 'Light snow',
    21: 'Snow', 1021: 'Snow', 22: 'Heavy snow', 1022: 'Heavy snow',
    23: 'Light sleet', 1023: 'Light sleet', 24: 'Sleet', 1024: 'Sleet',
    25: 'Heavy sleet', 1025: 'Heavy sleet', 26: 'Light hail', 1026: 'Light hail',
    27: 'Hail', 1027: 'Hail', 28: 'Heavy hail', 1028: 'Heavy hail',
    30: 'Thunderstorm', 1030: 'Thunderstorm', 31: 'Thunderstorm', 1031: 'Thunderstorm',
    32: 'Heavy thunderstorm', 1032: 'Heavy thunderstorm', 0: 'Unknown',
}

def transform_meteomatics_data(meteomatics_json, lat, lon):
    from collections import defaultdict # Keep import local if only used here
    if not meteomatics_json or 'data' not in meteomatics_json or not meteomatics_json['data']:
        print("Error: Invalid or empty data received from Meteomatics.")
        return None
    transformed_data = {'lat': lat, 'lon': lon, 'timezone': 'UTC', 'timezone_offset': 0,
                        'current': {}, 'hourly': [], 'daily': []}
    param_map = {param_data['parameter']: param_data for param_data in meteomatics_json['data']}
    all_timestamps = set()
    for param_data in meteomatics_json['data']:
        if 'coordinates' in param_data and param_data['coordinates'] and 'dates' in param_data['coordinates'][0]:
            for item in param_data['coordinates'][0]['dates']:
                if 'date' in item and item['date'] is not None:
                    all_timestamps.add(datetime.fromisoformat(item['date'].replace('Z', '+00:00')))
    if not all_timestamps: return None
    sorted_timestamps = sorted(list(all_timestamps))

    temp_param = 't_2m:C'; wind_speed_param = 'wind_speed_10m:ms'; precip_1h_param = 'precip_1h:mm'
    symbol_1h_param = 'weather_symbol_1h:idx'; uv_param = 'uv:idx'
    temp_max_24h_param = 't_max_2m_24h:C'; temp_min_24h_param = 't_min_2m_24h:C'
    precip_24h_param = 'precip_24h:mm'; symbol_24h_param = 'weather_symbol_24h:idx'
    wind_gust_24h_param = 'wind_gusts_10m_24h:ms'

    if not all(p in param_map for p in [temp_param, wind_speed_param, precip_1h_param, symbol_1h_param]):
        return None

    def get_value_at_ts(param_key, target_ts, default=None):
        if param_key not in param_map: return default
        for item in param_map[param_key]['coordinates'][0]['dates']:
            if datetime.fromisoformat(item['date'].replace('Z', '+00:00')) == target_ts:
                value = item['value']
                if isinstance(default, (int, float)) and isinstance(value, (int, float)) and math.isnan(value): return default
                return int(value) if isinstance(default, int) and isinstance(value, float) else value
        return default

    hourly_list = []
    for ts_dt in sorted_timestamps:
        temp_val = get_value_at_ts(temp_param, ts_dt)
        if temp_val is None: continue
        temp = float(temp_val)
        symbol_idx = int(get_value_at_ts(symbol_1h_param, ts_dt, 0))
        owm_icon = METEOMATICS_TO_OWM_ICON.get(symbol_idx, 'na')
        description = METEOMATICS_SYMBOL_DESC.get(symbol_idx, 'Unknown')
        hourly_list.append({
            'dt': int(ts_dt.timestamp()), 'temp': temp, 'feels_like': temp, 'pressure': 1013.0,
            'humidity': 50, 'dew_point': 0, 'uvi': float(get_value_at_ts(uv_param, ts_dt, 0.0)),
            'clouds': 50, 'visibility': 10000, 'wind_speed': float(get_value_at_ts(wind_speed_param, ts_dt, 0.0)),
            'wind_deg': 0, 'wind_gust': 0.0, 'weather': [{'id': symbol_idx, 'main': description.split()[0],
            'description': description, 'icon': owm_icon}], 'rain': {'1h': float(get_value_at_ts(precip_1h_param, ts_dt, 0.0))}
        })
    if hourly_list:
        transformed_data['current'] = hourly_list[0].copy()
        transformed_data['hourly'] = hourly_list[:48]
    else: # Fallback current
        transformed_data['current'] = {'dt': int(datetime.now(timezone.utc).timestamp()), 'temp': 0, 'feels_like': 0, 'pressure': 1013, 'humidity': 50, 'uvi': 0, 'wind_speed': 0, 'wind_deg': 0, 'weather': [{'id': 0, 'main': 'Unknown', 'description': 'Unknown', 'icon': 'na'}], 'rain': {'1h': 0}}

    daily_data_by_day_start = defaultdict(dict)
    for param_key in [temp_max_24h_param, temp_min_24h_param, precip_24h_param, symbol_24h_param, wind_gust_24h_param]:
        if param_key in param_map:
            for item in param_map[param_key]['coordinates'][0]['dates']:
                end_of_day_ts_dt = datetime.fromisoformat(item['date'].replace('Z', '+00:00'))
                start_of_day_dt = (end_of_day_ts_dt - timedelta(days=1)) if end_of_day_ts_dt.hour == 0 and end_of_day_ts_dt.minute == 0 else end_of_day_ts_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                day_start_timestamp = int(start_of_day_dt.timestamp())
                value = item['value']
                is_numeric_param = param_key in [temp_max_24h_param, temp_min_24h_param, precip_24h_param, wind_gust_24h_param]
                daily_data_by_day_start[day_start_timestamp][param_key] = (0.0 if is_numeric_param else 0) if isinstance(value, (int, float)) and math.isnan(value) else (float(value) if is_numeric_param else int(value))

    hourly_agg_by_day_start = defaultdict(lambda: {'winds': [], 'uvis': []})
    if hourly_list:
        for hour in hourly_list:
            day_start_ts = int((datetime.fromtimestamp(hour['dt'], tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).timestamp())
            hourly_agg_by_day_start[day_start_ts]['winds'].append(hour['wind_speed'])
            hourly_agg_by_day_start[day_start_ts]['uvis'].append(hour['uvi'])

    for day_ts in sorted(daily_data_by_day_start.keys()):
        day_data = daily_data_by_day_start[day_ts]
        hourly_agg = hourly_agg_by_day_start.get(day_ts, {'winds': [], 'uvis': []})
        temp_max = day_data.get(temp_max_24h_param)
        temp_min = day_data.get(temp_min_24h_param)
        if temp_max is None and temp_min is None: continue
        temp_max = temp_max if temp_max is not None else temp_min
        temp_min = temp_min if temp_min is not None else temp_max
        symbol_24h = day_data.get(symbol_24h_param, 0)
        daily_icon = METEOMATICS_TO_OWM_ICON.get(symbol_24h, 'na')
        daily_desc = METEOMATICS_SYMBOL_DESC.get(symbol_24h, 'Unknown')
        temp_day_approx = (temp_max + temp_min) / 2
        transformed_data['daily'].append({
            'dt': day_ts, 'sunrise': 0, 'sunset': 0, 'moonrise': 0, 'moonset': 0, 'moon_phase': 0,
            'summary': daily_desc,
            'temp': {'day': temp_day_approx, 'min': temp_min, 'max': temp_max, 'night': temp_min, 'eve': temp_min, 'morn': temp_min},
            'feels_like': {'day': temp_day_approx, 'night': temp_min, 'eve': temp_min, 'morn': temp_min},
            'pressure': 1013, 'humidity': 50, 'dew_point': 0,
            'wind_speed': sum(hourly_agg['winds']) / len(hourly_agg['winds']) if hourly_agg['winds'] else 0.0,
            'wind_deg': 0, 'wind_gust': day_data.get(wind_gust_24h_param, 0.0),
            'weather': [{'id': symbol_24h, 'main': daily_desc.split()[0], 'description': daily_desc, 'icon': daily_icon}],
            'clouds': 50, 'pop': 0, 'rain': day_data.get(precip_24h_param, 0.0),
            'uvi': max(hourly_agg['uvis']) if hourly_agg['uvis'] else 0.0
        })
    transformed_data['daily'] = transformed_data['daily'][:8]
    return transformed_data

class MeteomaticsProvider(WeatherProvider):
    def __init__(self, username, password, lat, lon, **kwargs):
        super().__init__(lat, lon, **kwargs)
        self.username = username
        self.password = password
        self.provider_name = "Meteomatics"
        if not username or not password:
            raise ValueError("Meteomatics username and password are required.")

    async def _fetch_from_api(self):
        print(f"Fetching data from {self.provider_name} (basic plan 10 params)...")
        base_url = "https://api.meteomatics.com"
        now = datetime.utcnow()
        start_time = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time = (now + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        parameters = ['t_2m:C', 'wind_speed_10m:ms', 'precip_1h:mm', 'weather_symbol_1h:idx', 'uv:idx',
                      't_max_2m_24h:C', 't_min_2m_24h:C', 'precip_24h:mm', 'weather_symbol_24h:idx',
                      'wind_gusts_10m_24h:ms']
        api_url = f"{base_url}/{start_time}--{end_time}:PT1H/{','.join(parameters)}/{self.lat},{self.lon}/json"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(api_url, auth=aiohttp.BasicAuth(self.username, self.password), timeout=45) as response:
                    print(f"Meteomatics Response Status Code: {response.status}")
                    response.raise_for_status()
                    raw_data = await response.json()
                    print(f"{self.provider_name} raw data fetched successfully.")
                    return transform_meteomatics_data(raw_data, self.lat, self.lon)
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