# provider_meteomatics.py
import json
from datetime import datetime, timedelta, timezone
import math
import traceback
import aiohttp

from weather_provider_base import WeatherProvider, parse_iso_time, HourlyDataPoint, DailyDataPoint

# --- Meteomatics SYMBOL Mappings ---
METEOMATICS_TO_OWM_ICON = {
    1: '01d', 101: '01n', # Clear sky
    2: '02d', 102: '02n', # Light clouds
    3: '03d', 103: '03n', # Partly Cloudy
    4: '04d', 104: '04n', # Cloudy
    5: '09d', 105: '09n', # Rain
    6: '09d', 106: '09n', # Sleet
    7: '13d', 107: '13n', # Snow
    8: '10d', 108: '10n', # Rain Shower
    9: '13d', 109: '13n', # Snow Shower
    10: '10d', 110: '10n', # Sleet Shower
    11: '50d', 111: '50n', # Light Fog
    12: '50d', 112: '50n', # Dense Fog
    13: '13d', 113: '13n', # Freezing Rain
    14: '11d', 114: '11n', # Thunderstorm
    15: '09d', 115: '09n', # Drizzle
    16: '50d', 116: '50n', # Sandstorm
    0: 'na',
}
METEOMATICS_SYMBOL_DESC = {
    1: 'Clear sky', 101: 'Clear sky',
    2: 'Light clouds', 102: 'Light clouds',
    3: 'Partly cloudy', 103: 'Partly cloudy',
    4: 'Cloudy', 104: 'Cloudy',
    5: 'Rain', 105: 'Rain',
    6: 'Sleet', 106: 'Sleet',
    7: 'Snow', 107: 'Snow',
    8: 'Rain Shower', 108: 'Rain Shower',
    9: 'Snow Shower', 109: 'Snow Shower',
    10: 'Sleet Shower', 110: 'Sleet Shower',
    11: 'Light Fog', 111: 'Light Fog',
    12: 'Dense Fog', 112:'Dense Fog',
    13: 'Freezing rain', 113: 'Freezing rain',
    14: 'Thunderstorm', 114: 'Thunderstorm',
    15: 'Drizzle', 1015: 'Drizzle',
    16: 'Sandstorm', 1016: 'Sandstorm',
    0: 'Unknown',
}

def transform_meteomatics_data(meteomatics_json, lat, lon):
    from collections import defaultdict # Keep import local if only used here
    from dataclasses import asdict # For converting dataclass to dict for 'current'
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

    temp_param = 't_2m:C'
    wind_speed_param = 'wind_speed_10m:ms'
    precip_1h_param = 'precip_1h:mm'
    symbol_1h_param = 'weather_symbol_1h:idx'
    uv_param = 'uv:idx'
    temp_max_24h_param = 't_max_2m_24h:C'
    temp_min_24h_param = 't_min_2m_24h:C'
    precip_24h_param = 'precip_24h:mm'
    symbol_24h_param = 'weather_symbol_24h:idx'
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
        if temp_val is None:
            continue

        symbol_idx = int(get_value_at_ts(symbol_1h_param, ts_dt, 0))
        owm_icon = METEOMATICS_TO_OWM_ICON.get(symbol_idx, 'na')
        description = METEOMATICS_SYMBOL_DESC.get(symbol_idx, 'Unknown')

        hourly_point = HourlyDataPoint(
            dt=int(ts_dt.timestamp()),
            temp=float(temp_val),
            feels_like=float(temp_val), # Meteomatics basic doesn't provide feels_like per hour
            pressure=1013.0, # Placeholder
            humidity=50, # Placeholder
            dew_point=0.0, # Placeholder
            uvi=float(get_value_at_ts(uv_param, ts_dt, 0.0)),
            clouds=50, # Placeholder
            visibility=10000, # Placeholder
            wind_speed=float(get_value_at_ts(wind_speed_param, ts_dt, 0.0)),
            wind_deg=0, # Placeholder
            wind_gust=float(get_value_at_ts(wind_gust_24h_param, ts_dt, 0.0)), # Using 24h gust for hourly as approximation
            weather_id=symbol_idx,
            weather_main=description.split()[0] if description else "Unknown",
            weather_description=description,
            weather_icon=owm_icon,
            rain_1h=float(get_value_at_ts(precip_1h_param, ts_dt, 0.0))
        )
        hourly_list.append(hourly_point)

    if hourly_list:
        first_hour_dp = hourly_list[0]
        # Construct 'current' as a dictionary, similar to OWM structure
        transformed_data['current'] = {
            'dt': first_hour_dp.dt,
            'temp': first_hour_dp.temp,
            'feels_like': first_hour_dp.feels_like,
            'pressure': first_hour_dp.pressure,
            'humidity': first_hour_dp.humidity,
            'dew_point': first_hour_dp.dew_point,
            'uvi': first_hour_dp.uvi,
            'clouds': first_hour_dp.clouds,
            'visibility': first_hour_dp.visibility,
            'wind_speed': first_hour_dp.wind_speed,
            'wind_deg': first_hour_dp.wind_deg,
            'wind_gust': first_hour_dp.wind_gust,
            'weather': [{
                'id': first_hour_dp.weather_id,
                'main': first_hour_dp.weather_main,
                'description': first_hour_dp.weather_description,
                'icon': first_hour_dp.weather_icon
            }],
            'rain': {'1h': first_hour_dp.rain_1h} if first_hour_dp.rain_1h is not None else None,
            'snow': {'1h': first_hour_dp.snow_1h} if first_hour_dp.snow_1h is not None else None,
            'pop': first_hour_dp.pop,
            'sunrise': 0, # Placeholder, Meteomatics basic doesn't provide this directly
            'sunset': 0   # Placeholder
        }
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
            day_start_ts = int((datetime.fromtimestamp(hour.dt, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).timestamp())
            if hour.wind_speed is not None: hourly_agg_by_day_start[day_start_ts]['winds'].append(hour.wind_speed)
            if hour.uvi is not None: hourly_agg_by_day_start[day_start_ts]['uvis'].append(hour.uvi)

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

        daily_point = DailyDataPoint(
            dt=day_ts,
            summary=daily_desc,
            temp_day=temp_day_approx,
            temp_min=temp_min,
            temp_max=temp_max,
            temp_night=temp_min, # Approximation
            temp_eve=temp_min,   # Approximation
            temp_morn=temp_min,  # Approximation
            feels_like_day=temp_day_approx, # Approximation
            feels_like_night=temp_min,      # Approximation
            pressure=1013.0, # Placeholder
            humidity=50,    # Placeholder
            wind_speed=sum(hourly_agg['winds']) / len(hourly_agg['winds']) if hourly_agg['winds'] else 0.0,
            wind_gust=day_data.get(wind_gust_24h_param, 0.0),
            weather_id=symbol_24h,
            weather_main=daily_desc.split()[0] if daily_desc else "Unknown",
            weather_description=daily_desc,
            weather_icon=daily_icon,
            rain=day_data.get(precip_24h_param, 0.0),
            uvi=max(hourly_agg['uvis']) if hourly_agg['uvis'] else 0.0
            # pop, clouds, dew_point, sunrise/sunset etc. are not directly available from basic Meteomatics
        )
        transformed_data['daily'].append(daily_point)
    transformed_data['daily'] = transformed_data['daily'][:8]
    return transformed_data

class MeteomaticsProvider(WeatherProvider):
    def __init__(self, username, password, lat, lon, **kwargs):
        provider_id = kwargs.pop("provider_id_for_cache", "meteomatics") # Default if somehow missing
        super().__init__(lat, lon, provider_id_for_cache=provider_id, **kwargs)
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