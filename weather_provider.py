# weather_provider.py
import requests
import json
import os
from datetime import datetime, timedelta, timezone
from abc import ABC, abstractmethod
from requests.auth import HTTPBasicAuth
from collections import defaultdict
import math
import traceback # For detailed error logging
import asyncio # For async operations
import aiohttp # For async HTTP client

# --- Constants ---
CACHE_DURATION_MINUTES = 60
CACHE_FILE = "weather_data_cache_provider.json" # Use a dedicated cache file

# --- SMHI SYMBOL Mappings ---
# Source: https://www.smhi.se/kunskapsbanken/meteorologi/vadersymboler/
SMHI_SYMBOL_TO_OWM_ICON = {
    1: '01d',  # Clear sky
    2: '02d',  # Nearly clear sky
    3: '03d',  # Variable cloudiness
    4: '04d',  # Half clear sky
    5: '04d',  # Cloudy sky
    6: '04d',  # Overcast sky
    7: '50d',  # Fog
    8: '09d',  # Light rain showers
    9: '09d',  # Moderate rain showers
    10: '09d', # Heavy rain showers
    11: '11d', # Thunderstorm
    12: '13d', # Light sleet showers
    13: '13d', # Moderate sleet showers
    14: '13d', # Heavy sleet showers
    15: '13d', # Light snow showers
    16: '13d', # Moderate snow showers
    17: '13d', # Heavy snow showers
    18: '10d', # Light rain
    19: '10d', # Moderate rain
    20: '10d', # Heavy rain
    21: '11d', # Thunder
    22: '13d', # Light sleet
    23: '13d', # Moderate sleet
    24: '13d', # Heavy sleet
    25: '13d', # Light snow
    26: '13d', # Moderate snow
    27: '13d', # Heavy snow
    # Note: SMHI symbols don't inherently distinguish day/night. Using 'd' suffix.
}
SMHI_SYMBOL_DESC = {
    1: 'Clear sky', 2: 'Nearly clear', 3: 'Variable cloudiness', 4: 'Half clear',
    5: 'Cloudy', 6: 'Overcast', 7: 'Fog', 8: 'Light rain showers',
    9: 'Mod rain showers', 10: 'Heavy rain showers', 11: 'Thunderstorm',
    12: 'Light sleet showers', 13: 'Mod sleet showers', 14: 'Heavy sleet showers',
    15: 'Light snow showers', 16: 'Mod snow showers', 17: 'Heavy snow showers',
    18: 'Light rain', 19: 'Mod rain', 20: 'Heavy rain', 21: 'Thunder',
    22: 'Light sleet', 23: 'Mod sleet', 24: 'Heavy sleet', 25: 'Light snow',
    26: 'Mod snow', 27: 'Heavy snow',
}

# --- Meteomatics SYMBOL Mappings ---
METEOMATICS_TO_OWM_ICON = {
    1: '01d', 1001: '01n', 2: '02d', 1002: '02n', 3: '03d', 1003: '03n',
    4: '04d', 1004: '04n', 5: '50d', 1005: '50n', 10: '10d', 1010: '10n',
    11: '10d', 1011: '10n', 12: '09d', 1012: '09n', 13: '09d', 1013: '09n',
    14: '10d', 1014: '10n', 15: '10d', 1015: '10n', 16: '09d', 1016: '09n',
    20: '13d', 1020: '13n', 21: '13d', 1021: '13n', 22: '13d', 1022: '13n',
    23: '13d', 1023: '13n', 24: '13d', 1024: '13n', 25: '13d', 1025: '13n',
    26: '09d', 1026: '09n', 27: '09d', 1027: '09n', 28: '09d', 1028: '09n',
    30: '11d', 1030: '11n', 31: '11d', 1031: '11n', 32: '11d', 1032: '11n',
    0: 'na',
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

# --- Google Weather Condition Mappings ---
GOOGLE_CONDITION_TO_OWM_ICON = {
    "CLEAR": "01", "CLOUDY": "03", "FOG": "50", "HAZE": "50", "HEAVY_RAIN": "09",
    "MOSTLY_CLEAR": "01", "PARTLY_CLOUDY": "02", "RAIN": "10", "LIGHT_RAIN": "10",
    "RAIN_SHOWERS": "09", "SCATTERED_SHOWERS": "09", "SLEET": "13", "SNOW": "13",
    "SNOW_LIGHT": "13", "SNOW_SHOWERS": "13", "SQUALL": "11", "THUNDERSTORM": "11",
    "MOSTLY_CLOUDY": "04", "SCATTERED_THUNDERSTORMS": "11", "SMOKE": "50", "DUST": "50",
    "WINDY": "01", "DRIZZLE": "10", "ICY": "13", "HAIL": "09", "CONDITION_UNSPECIFIED": "01",
}
GOOGLE_CONDITION_DESC = {
    "CLEAR": "Clear", "CLOUDY": "Cloudy", "FOG": "Fog", "HAZE": "Haze",
    "HEAVY_RAIN": "Heavy Rain", "MOSTLY_CLEAR": "Mostly Clear", "PARTLY_CLOUDY": "Partly Cloudy",
    "RAIN": "Rain", "LIGHT_RAIN": "Light Rain", "RAIN_SHOWERS": "Rain Showers",
    "SCATTERED_SHOWERS": "Scattered Showers", "SLEET": "Sleet", "SNOW": "Snow",
    "SNOW_LIGHT": "Light Snow", "SNOW_SHOWERS": "Snow Showers", "SQUALL": "Squall",
    "THUNDERSTORM": "Thunderstorm", "MOSTLY_CLOUDY": "Mostly Cloudy",
    "SCATTERED_THUNDERSTORMS": "Scattered T-Storms", "SMOKE": "Smoke", "DUST": "Dust",
    "WINDY": "Windy", "DRIZZLE": "Drizzle", "ICY": "Icy", "HAIL": "Hail", "CONDITION_UNSPECIFIED": "Unknown",
}

# --- Helper Functions ---

def get_wmo_code_description(code):
    """Returns a text description for a WMO weather code."""
    return WMO_CODE_DESC.get(code, 'Unknown')

def get_owm_icon_from_wmo_code(code, is_day=1):
    """Returns an OWM icon code string from a WMO code, adjusting for day/night."""
    icon = WMO_CODE_TO_OWM_ICON.get(code, 'na')
    is_night = (is_day == 0)
    if icon != 'na':
        if is_night:
            icon = icon.replace('d', 'n')
        else: # It's day
            icon = icon.replace('n', 'd')
    return icon

def get_owm_icon_from_google_code(code, is_day=True):
    """Returns an OWM icon code string from a Google condition code, adjusting for day/night."""
    base_icon = GOOGLE_CONDITION_TO_OWM_ICON.get(code, 'na')
    if base_icon == 'na':
        return 'na'
    return base_icon + ('d' if is_day else 'n')

def get_google_code_description(code):
    """Returns a text description for a Google condition code."""
    return GOOGLE_CONDITION_DESC.get(code, 'Unknown')

def get_owm_icon_from_smhi_code(code):
    """Returns an OWM icon code string from an SMHI symbol code."""
    # SMHI symbols don't have day/night distinction, use 'd' suffix
    return SMHI_SYMBOL_TO_OWM_ICON.get(code, 'na')

def parse_iso_time(iso_time_str):
    """Parses ISO time string (UTC assumed if no offset) to Unix timestamp."""
    if not iso_time_str:
        return 0
    try:
        # Handle potential timezone variations
        if '+' not in iso_time_str and 'Z' not in iso_time_str:
            # Assume UTC if no offset provided
            iso_time_str += '+00:00'
        elif 'Z' in iso_time_str:
            # Replace Z with UTC offset
            iso_time_str = iso_time_str.replace('Z', '+00:00')

        # Handle potential fractional seconds of varying length
        if '.' in iso_time_str:
            time_part, tz_part = iso_time_str.split('+') # Assumes + separator for TZ
            base_time, fractional = time_part.split('.')
            # Truncate fractional seconds to microseconds (6 digits)
            fractional = fractional[:6]
            iso_time_str = f"{base_time}.{fractional}+{tz_part}"

        dt_obj = datetime.fromisoformat(iso_time_str)
        return int(dt_obj.timestamp())
    except (ValueError, TypeError) as e:
        print(f"Warning: Could not parse ISO time string '{iso_time_str}': {e}")
        return 0

def parse_google_date(date_obj):
    """Parses Google Date object {year, month, day} to start-of-day UTC Unix timestamp."""
    if not date_obj or not all(k in date_obj for k in ['year', 'month', 'day']):
        return 0
    try:
        dt_obj = datetime(date_obj['year'], date_obj['month'], date_obj['day'], 0, 0, 0, tzinfo=timezone.utc)
        return int(dt_obj.timestamp())
    except (ValueError, TypeError, KeyError) as e:
        print(f"Warning: Could not parse Google date object '{date_obj}': {e}")
        return 0

# --- Transformation Functions ---
def transform_smhi_data(smhi_daily, smhi_hourly, lat, lon):
    """Transforms pysmhi daily and hourly data to OWM OneCall 3.0 structure."""
    if not smhi_daily and not smhi_hourly:
        print("Error: No data received from SMHI.")
        return None

    transformed_data = {
        'lat': lat, 'lon': lon, 'timezone': 'UTC', 'timezone_offset': 0,
        'current': {}, 'hourly': [], 'daily': []
    }

    # Process Hourly
    if smhi_hourly:
        for hour_fc in smhi_hourly:
            # pysmhi returns SMHIForecast objects, convert to dict
            hour_dict = hour_fc.__dict__ if hasattr(hour_fc, '__dict__') else hour_fc

            ts = int(hour_dict.get('valid_time', datetime.now(timezone.utc)).timestamp())
            temp = hour_dict.get('temperature', 0.0)
            humidity = hour_dict.get('humidity', 50)
            pressure = hour_dict.get('pressure', 1013.0)
            wind_speed = hour_dict.get('wind_speed', 0.0)
            wind_deg = hour_dict.get('wind_direction', 0)
            wind_gust = hour_dict.get('wind_gust', 0.0)
            total_cloud = hour_dict.get('total_cloud', 50)
            symbol = hour_dict.get('symbol', 0)
            mean_precipitation = hour_dict.get('mean_precipitation', 0.0)
            thunder = hour_dict.get('thunder', 0)
            visibility = hour_dict.get('visibility', 10.0) * 1000 # Convert km to meters

            # SMHI doesn't provide feels_like, dew_point, uvi, sunrise/sunset, pop directly per hour
            # Infer description and icon from symbol
            description = SMHI_SYMBOL_DESC.get(symbol, 'Unknown')
            owm_icon = get_owm_icon_from_smhi_code(symbol)

            # Add thunder to description if present
            if thunder > 0 and 'Thunder' not in description:
                 description += " (Thunder)"

            hour_entry = {
                'dt': ts, 'temp': temp, 'feels_like': temp, # Use temp as feels_like fallback
                'pressure': pressure, 'humidity': humidity, 'dew_point': 0, # Placeholder
                'uvi': 0, # Placeholder
                'clouds': total_cloud, 'visibility': visibility,
                'wind_speed': wind_speed, 'wind_deg': wind_deg, 'wind_gust': wind_gust,
                'weather': [{
                    'id': symbol, 'main': description.split()[0], # Use first word for main
                    'description': description, 'icon': owm_icon
                }],
                'rain': {'1h': mean_precipitation},
                'pop': 0 # Placeholder
            }
            transformed_data['hourly'].append(hour_entry)

    # Process Daily
    if smhi_daily:
        for day_fc in smhi_daily:
            # pysmhi returns SMHIForecast objects, convert to dict
            day_dict = day_fc.__dict__ if hasattr(day_fc, '__dict__') else day_fc

            day_ts = int(day_dict.get('valid_time', datetime.now(timezone.utc)).timestamp())
            temp_max = day_dict.get('temperature_max', day_dict.get('temperature', 0.0))
            temp_min = day_dict.get('temperature_min', day_dict.get('temperature', 0.0))
            total_precipitation = day_dict.get('total_precipitation', 0.0)
            symbol = day_dict.get('symbol', 0)
            wind_speed = day_dict.get('wind_speed', 0.0) # SMHI daily seems to give a single wind speed
            wind_gust = day_dict.get('wind_gust', 0.0)
            thunder = day_dict.get('thunder', 0)

            description = SMHI_SYMBOL_DESC.get(symbol, 'Unknown')
            owm_icon = get_owm_icon_from_smhi_code(symbol)
            if thunder > 0 and 'Thunder' not in description:
                 description += " (Thunder)"

            day_entry = {
                'dt': day_ts, 'sunrise': 0, 'sunset': 0, 'moonrise': 0, 'moonset': 0, 'moon_phase': 0, # Placeholders
                'summary': description,
                'temp': {'day': (temp_max + temp_min) / 2, 'min': temp_min, 'max': temp_max, 'night': temp_min, 'eve': temp_min, 'morn': temp_min}, # Approximate
                'feels_like': {'day': (temp_max + temp_min) / 2, 'night': temp_min, 'eve': temp_min, 'morn': temp_min}, # Approximate
                'pressure': day_dict.get('pressure', 1013.0), 'humidity': day_dict.get('humidity', 50), 'dew_point': 0, # Placeholder
                'wind_speed': wind_speed, 'wind_deg': day_dict.get('wind_direction', 0), 'wind_gust': wind_gust,
                'weather': [{'id': symbol, 'main': description.split()[0], 'description': description, 'icon': owm_icon}],
                'clouds': day_dict.get('total_cloud', 50), 'pop': 0, 'rain': total_precipitation, 'uvi': 0 # Placeholders
            }
            transformed_data['daily'].append(day_entry)

    # Update current from the first hourly entry if available
    if transformed_data['hourly']:
        transformed_data['current'] = transformed_data['hourly'][0].copy()
        # SMHI hourly doesn't have sunrise/sunset, copy from daily if available
        if transformed_data['daily']:
             transformed_data['current']['sunrise'] = transformed_data['daily'][0].get('sunrise', 0)
             transformed_data['current']['sunset'] = transformed_data['daily'][0].get('sunset', 0)
    elif transformed_data['daily']:
         # Fallback: Create a minimal current from the first daily entry
         first_daily = transformed_data['daily'][0]
         transformed_data['current'] = {
             'dt': first_daily['dt'],
             'temp': first_daily['temp']['day'],
             'feels_like': first_daily['feels_like']['day'],
             'pressure': first_daily['pressure'],
             'humidity': first_daily['humidity'],
             'uvi': first_daily['uvi'],
             'wind_speed': first_daily['wind_speed'],
             'wind_deg': first_daily['wind_deg'],
             'wind_gust': first_daily['wind_gust'],
             'weather': first_daily['weather'],
             'rain': {'1h': 0}, # No hourly rain in daily data
             'pop': first_daily['pop'],
             'sunrise': first_daily['sunrise'],
             'sunset': first_daily['sunset']
         }

    # Final check
    if not transformed_data['current']: print("ERROR: Transformation resulted in empty 'current' data.")
    if not transformed_data['hourly']: print("Warning: Transformation resulted in empty 'hourly' data.")
    if not transformed_data['daily']: print("Warning: Transformation resulted in empty 'daily' data.")

    return transformed_data

def transform_meteomatics_data(meteomatics_json, lat, lon):
    """Transforms Meteomatics API response (basic plan 10 params) to OWM OneCall 3.0 structure."""
    if not meteomatics_json or 'data' not in meteomatics_json or not meteomatics_json['data']:
        print("Error: Invalid or empty data received from Meteomatics.")
        return None

    transformed_data = {
        'lat': lat, 'lon': lon, 'timezone': 'UTC', 'timezone_offset': 0,
        'current': {}, 'hourly': [], 'daily': []
    }
    param_map = {}
    all_timestamps = set()

    print("Meteomatics raw parameters received:")
    for i, param_data in enumerate(meteomatics_json['data']):
        param_name = param_data['parameter']
        print(f"- {param_name}")
        param_map[param_name] = param_data
        if 'coordinates' in param_data and param_data['coordinates'] and 'dates' in param_data['coordinates'][0]:
            try:
                for item in param_data['coordinates'][0]['dates']:
                    if 'date' in item and item['date'] is not None:
                        ts = datetime.fromisoformat(item['date'].replace('Z', '+00:00'))
                        all_timestamps.add(ts)
                    else:
                        print(f"Warning: Missing or null 'date' in data for parameter {param_name}")
            except (ValueError, KeyError, TypeError) as e:
                print(f"Error parsing timestamps for parameter {param_name}: {e}")

    if not all_timestamps:
        print("Error: Could not extract any valid timestamps from Meteomatics data.")
        return None

    sorted_timestamps = sorted(list(all_timestamps))

    # Define expected parameters
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

    essential_params = [temp_param, wind_speed_param, precip_1h_param, symbol_1h_param]
    missing_essential = [p for p in essential_params if p not in param_map]
    if missing_essential:
        print(f"Error: Missing essential parameters required for transformation: {missing_essential}")
        return None

    # Helper to get value for a specific timestamp
    def get_value_at_ts(param_key, target_ts, default=None):
        if param_key not in param_map:
            return default
        try:
            for item in param_map[param_key]['coordinates'][0]['dates']:
                item_ts = datetime.fromisoformat(item['date'].replace('Z', '+00:00'))
                if item_ts == target_ts:
                    value = item['value']
                    # Handle NaN specifically for numeric types expected
                    if isinstance(default, (int, float)) and isinstance(value, (int, float)) and math.isnan(value):
                        print(f"Warning: NaN value found for {param_key} at {target_ts}, using default {default}")
                        return default
                    # Handle potential type mismatches
                    if isinstance(default, int) and isinstance(value, float):
                        return int(value)
                    return value
            return default
        except (KeyError, ValueError, TypeError, IndexError) as e:
            print(f"Error accessing value for {param_key} at {target_ts}: {e}")
            return default

    # Populate Hourly
    hourly_list = []
    for ts in sorted_timestamps:
        temp_val = get_value_at_ts(temp_param, ts, None)
        if temp_val is None:
            continue # Skip if essential temp data is missing for this hour

        temp = float(temp_val)
        wind_speed = float(get_value_at_ts(wind_speed_param, ts, 0.0))
        precip_1h = float(get_value_at_ts(precip_1h_param, ts, 0.0))
        symbol_idx = int(get_value_at_ts(symbol_1h_param, ts, 0))
        uv_index = float(get_value_at_ts(uv_param, ts, 0.0))

        # Placeholders/Fallbacks
        wind_deg = 0
        wind_gust = 0.0
        pressure = 1013.0
        feels_like = temp
        humidity = 50
        dew_point = 0
        clouds = 50
        visibility = 10000

        owm_icon = METEOMATICS_TO_OWM_ICON.get(symbol_idx, 'na')
        description = METEOMATICS_SYMBOL_DESC.get(symbol_idx, 'Unknown')

        hour_entry = {
            'dt': int(ts.timestamp()), 'temp': temp, 'feels_like': feels_like,
            'pressure': pressure, 'humidity': humidity, 'dew_point': dew_point,
            'uvi': uv_index, 'clouds': clouds, 'visibility': visibility,
            'wind_speed': wind_speed, 'wind_deg': wind_deg, 'wind_gust': wind_gust,
            'weather': [{
                'id': symbol_idx, 'main': description.split()[0],
                'description': description, 'icon': owm_icon
            }],
            'rain': {'1h': precip_1h}
        }
        hourly_list.append(hour_entry)

    # Assign current/hourly data
    if hourly_list:
        transformed_data['current'] = hourly_list[0].copy()
        transformed_data['hourly'] = hourly_list[:48]
    else:
        print("Warning: No valid hourly data points could be processed for Meteomatics.")
        transformed_data['current'] = {
            'dt': int(datetime.now(timezone.utc).timestamp()), 'temp': 0, 'feels_like': 0,
            'pressure': 1013, 'humidity': 50, 'uvi': 0, 'wind_speed': 0, 'wind_deg': 0,
            'weather': [{'id': 0, 'main': 'Unknown', 'description': 'Unknown', 'icon': 'na'}],
            'rain': {'1h': 0}
        }

    # Process Daily Data
    daily_data_by_day_start = defaultdict(dict)
    daily_param_keys = [
        temp_max_24h_param, temp_min_24h_param, precip_24h_param,
        symbol_24h_param, wind_gust_24h_param
    ]

    for param_key in daily_param_keys:
        if param_key in param_map:
            try:
                for item in param_map[param_key]['coordinates'][0]['dates']:
                    end_of_day_ts_dt = datetime.fromisoformat(item['date'].replace('Z', '+00:00'))

                    # Determine start of the day this data represents
                    if end_of_day_ts_dt.hour == 0 and end_of_day_ts_dt.minute == 0:
                        start_of_day_dt = end_of_day_ts_dt - timedelta(days=1)
                    else:
                        start_of_day_dt = end_of_day_ts_dt.replace(hour=0, minute=0, second=0, microsecond=0)

                    day_start_timestamp = int(start_of_day_dt.timestamp())
                    value = item['value']

                    # Store value, handling NaN
                    if param_key in [temp_max_24h_param, temp_min_24h_param, precip_24h_param, wind_gust_24h_param]:
                        daily_data_by_day_start[day_start_timestamp][param_key] = 0.0 if isinstance(value, (int, float)) and math.isnan(value) else float(value)
                    elif param_key == symbol_24h_param:
                        daily_data_by_day_start[day_start_timestamp][param_key] = 0 if isinstance(value, (int, float)) and math.isnan(value) else int(value)
            except (KeyError, ValueError, TypeError, IndexError) as e:
                print(f"Error processing daily parameter {param_key}: {e}")
                traceback.print_exc()

    # Aggregate remaining daily fields from hourly data
    hourly_agg_by_day_start = defaultdict(lambda: {'winds': [], 'uvis': []})
    if hourly_list:
        for hour in hourly_list:
            day_start_ts = int((datetime.fromtimestamp(hour['dt'], tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).timestamp())
            hourly_agg_by_day_start[day_start_ts]['winds'].append(hour['wind_speed'])
            hourly_agg_by_day_start[day_start_ts]['uvis'].append(hour['uvi'])

    # Construct final daily entries
    sorted_day_starts = sorted(daily_data_by_day_start.keys())
    for day_ts in sorted_day_starts:
        day_data = daily_data_by_day_start[day_ts]
        hourly_agg = hourly_agg_by_day_start.get(day_ts, {'winds': [], 'uvis': []})

        temp_max = day_data.get(temp_max_24h_param)
        temp_min = day_data.get(temp_min_24h_param)
        precip_24h = day_data.get(precip_24h_param, 0.0)
        symbol_24h = day_data.get(symbol_24h_param, 0)
        wind_gust_24h = day_data.get(wind_gust_24h_param, 0.0)

        if temp_max is None and temp_min is None:
            print(f"Warning: Missing min/max temp for day {datetime.fromtimestamp(day_ts, tz=timezone.utc).date()}. Skipping day.")
            continue
        if temp_max is None: temp_max = temp_min
        if temp_min is None: temp_min = temp_max

        avg_wind = sum(hourly_agg['winds']) / len(hourly_agg['winds']) if hourly_agg['winds'] else 0.0
        max_uvi = max(hourly_agg['uvis']) if hourly_agg['uvis'] else 0.0

        daily_icon = METEOMATICS_TO_OWM_ICON.get(symbol_24h, 'na')
        daily_desc = METEOMATICS_SYMBOL_DESC.get(symbol_24h, 'Unknown')

        temp_day_approx = (temp_max + temp_min) / 2

        day_entry = {
            'dt': day_ts, 'sunrise': 0, 'sunset': 0, 'moonrise': 0, 'moonset': 0, 'moon_phase': 0,
            'summary': daily_desc,
            'temp': {'day': temp_day_approx, 'min': temp_min, 'max': temp_max, 'night': temp_min, 'eve': temp_min, 'morn': temp_min},
            'feels_like': {'day': temp_day_approx, 'night': temp_min, 'eve': temp_min, 'morn': temp_min},
            'pressure': 1013, 'humidity': 50, 'dew_point': 0,
            'wind_speed': avg_wind, 'wind_deg': 0, 'wind_gust': wind_gust_24h,
            'weather': [{'id': symbol_24h, 'main': daily_desc.split()[0], 'description': daily_desc, 'icon': daily_icon}],
            'clouds': 50, 'pop': 0, 'rain': precip_24h, 'uvi': max_uvi
        }
        transformed_data['daily'].append(day_entry)

    transformed_data['daily'] = transformed_data['daily'][:8]
    if not transformed_data['daily']:
        print("Warning: No valid daily data points could be processed for Meteomatics.")
    return transformed_data


def transform_open_meteo_data(om_json, lat, lon):
    """Transforms Open-Meteo API response to OWM OneCall 3.0 structure."""
    if not om_json:
        print("Error: No data received from Open-Meteo.")
        return None

    tz_offset = om_json.get('utc_offset_seconds', 0)
    tz_name = om_json.get('timezone', 'UTC')

    transformed_data = {
        'lat': lat, 'lon': lon, 'timezone': tz_name, 'timezone_offset': tz_offset,
        'current': {}, 'hourly': [], 'daily': []
    }
    current = om_json.get('current_weather')

    # Process Current
    if current:
        current_ts = parse_iso_time(current.get('time'))
        current_temp = current.get('temperature')
        current_feels_like = current.get('apparent_temperature', current_temp)
        current_humidity = current.get('relative_humidity_2m', 50)
        current_pressure = current.get('pressure_msl', 1013)
        current_wind_speed = current.get('wind_speed_10m', 0)
        current_wind_deg = current.get('wind_direction_10m', 0)
        current_wind_gust = current.get('wind_gusts_10m', 0)
        current_weather_code = current.get('weather_code', 0)
        current_is_day = current.get('is_day', 1)

        current_icon = get_owm_icon_from_wmo_code(current_weather_code, current_is_day)
        current_desc = get_wmo_code_description(current_weather_code)

        transformed_data['current'] = {
            'dt': current_ts, 'sunrise': 0, 'sunset': 0, 'temp': current_temp,
            'feels_like': current_feels_like, 'pressure': current_pressure, 'humidity': current_humidity,
            'dew_point': 0, 'uvi': 0, 'clouds': current.get('cloud_cover', 50), 'visibility': 10000,
            'wind_speed': current_wind_speed, 'wind_deg': current_wind_deg, 'wind_gust': current_wind_gust,
            'weather': [{'id': current_weather_code, 'main': current_desc.split()[0], 'description': current_desc, 'icon': current_icon}],
            'rain': {'1h': current.get('rain', 0.0)}, 'snow': {'1h': current.get('snowfall', 0.0)}
        }
    else:
        print("Warning: 'current_weather' data missing from Open-Meteo response.")
        transformed_data['current'] = {
            'dt': int(datetime.now(timezone.utc).timestamp()), 'temp': 0, 'feels_like': 0,
            'pressure': 1013, 'humidity': 50, 'uvi': 0, 'wind_speed': 0, 'wind_deg': 0,
            'weather': [{'id': 0, 'main': 'Unknown', 'description': 'Unknown', 'icon': 'na'}],
            'rain': {'1h': 0}
        }

    # Process Hourly
    hourly = om_json.get('hourly')
    if hourly and 'time' in hourly:
        hourly_times = hourly['time']
        num_hours = len(hourly_times)

        # Helper to get hourly value by index, with default
        def get_hourly_val(key, index, default=None):
            if key in hourly and index < len(hourly[key]):
                val = hourly[key][index]
                if val is None: return default
                if isinstance(default, int) and isinstance(val, float): return int(val)
                if isinstance(default, float) and isinstance(val, int): return float(val)
                return val
            return default

        for i in range(num_hours):
            ts = parse_iso_time(hourly_times[i])
            if ts == 0:
                continue

            temp = get_hourly_val('temperature_2m', i, 0.0)
            feels_like = get_hourly_val('apparent_temperature', i, temp)
            humidity = get_hourly_val('relative_humidity_2m', i, 50)
            pressure = get_hourly_val('pressure_msl', i, 1013.0)
            precip = get_hourly_val('precipitation', i, 0.0)
            rain = get_hourly_val('rain', i, 0.0)
            snow = get_hourly_val('snowfall', i, 0.0)
            precip_1h = rain if rain > 0.0 else (snow if snow > 0.0 else precip)
            weather_code = get_hourly_val('weather_code', i, 0)
            is_day = get_hourly_val('is_day', i, 1 if 6 <= datetime.fromtimestamp(ts, tz=timezone.utc).hour < 18 else 0)

            icon = get_owm_icon_from_wmo_code(weather_code, is_day)
            description = get_wmo_code_description(weather_code)

            pop_val = get_hourly_val('precipitation_probability', i)
            pop = pop_val / 100.0 if pop_val is not None else 0

            hour_entry = {
                'dt': ts, 'temp': temp, 'feels_like': feels_like, 'pressure': pressure,
                'humidity': humidity, 'dew_point': 0, 'uvi': get_hourly_val('uv_index', i, 0.0),
                'clouds': get_hourly_val('cloud_cover', i, 50), 'visibility': get_hourly_val('visibility', i, 10000),
                'wind_speed': get_hourly_val('wind_speed_10m', i, 0.0), 'wind_deg': get_hourly_val('wind_direction_10m', i, 0),
                'wind_gust': get_hourly_val('wind_gusts_10m', i, 0.0),
                'weather': [{'id': weather_code, 'main': description.split()[0], 'description': description, 'icon': icon}],
                'rain': {'1h': precip_1h}, 'snow': {'1h': snow}, 'pop': pop
            }
            transformed_data['hourly'].append(hour_entry)

        if transformed_data['hourly']:
            transformed_data['current']['uvi'] = transformed_data['hourly'][0].get('uvi', 0)
    else:
        print("Warning: 'hourly' data missing or invalid in Open-Meteo response.")

    transformed_data['hourly'] = transformed_data['hourly'][:48]

    # Process Daily
    daily = om_json.get('daily')
    if daily and 'time' in daily:
        daily_times = daily['time']
        num_days = len(daily_times)

        # Helper to get daily value by index, with default
        def get_daily_val(key, index, default=None):
             if key in daily and index < len(daily[key]):
                 val = daily[key][index]
                 if val is None: return default
                 if isinstance(default, int) and isinstance(val, float): return int(val)
                 if isinstance(default, float) and isinstance(val, int): return float(val)
                 return val
             return default

        for i in range(num_days):
            day_ts = parse_iso_time(daily_times[i])
            if day_ts == 0:
                continue

            temp_max = get_daily_val('temperature_2m_max', i, 0.0)
            temp_min = get_daily_val('temperature_2m_min', i, 0.0)
            apparent_max = get_daily_val('apparent_temperature_max', i, temp_max)
            apparent_min = get_daily_val('apparent_temperature_min', i, temp_min)
            sunrise_ts = parse_iso_time(get_daily_val('sunrise', i, None))
            sunset_ts = parse_iso_time(get_daily_val('sunset', i, None))
            weather_code = get_daily_val('weather_code', i, 0)

            daily_icon = get_owm_icon_from_wmo_code(weather_code, 1) # Use day icon
            daily_desc = get_wmo_code_description(weather_code)
            temp_day_approx = (temp_max + temp_min) / 2

            pop_max_val = get_daily_val('precipitation_probability_max', i)
            pop_max = pop_max_val / 100.0 if pop_max_val is not None else 0

            day_entry = {
                'dt': day_ts, 'sunrise': sunrise_ts, 'sunset': sunset_ts, 'moonrise': 0, 'moonset': 0, 'moon_phase': 0,
                'summary': daily_desc,
                'temp': {'day': temp_day_approx, 'min': temp_min, 'max': temp_max, 'night': temp_min, 'eve': temp_min, 'morn': temp_min},
                'feels_like': {'day': apparent_max, 'night': apparent_min, 'eve': apparent_min, 'morn': apparent_min},
                'pressure': 1013, 'humidity': 50, 'dew_point': 0,
                'wind_speed': get_daily_val('wind_speed_10m_max', i, 0.0), 'wind_deg': get_daily_val('wind_direction_10m_dominant', i, 0),
                'wind_gust': get_daily_val('wind_gusts_10m_max', i, 0.0),
                'weather': [{'id': weather_code, 'main': daily_desc.split()[0], 'description': daily_desc, 'icon': daily_icon}],
                'clouds': 50, 'pop': pop_max, 'rain': get_daily_val('precipitation_sum', i, 0.0),
                'uvi': get_daily_val('uv_index_max', i, 0.0)
            }
            transformed_data['daily'].append(day_entry)

            # Update current sunrise/sunset from first day
            if i == 0:
                transformed_data['current']['sunrise'] = sunrise_ts
                transformed_data['current']['sunset'] = sunset_ts
    else:
        print("Warning: 'daily' data missing or invalid in Open-Meteo response.")

    transformed_data['daily'] = transformed_data['daily'][:8]
    return transformed_data


def transform_google_weather_data(google_raw_data, lat, lon):
    """Transforms combined Google Weather API responses to OWM OneCall 3.0 structure."""
    if not google_raw_data or not all(k in google_raw_data for k in ['current', 'hourly', 'daily']):
        print("Error: Incomplete raw data received from Google Weather API calls.")
        return None

    current_raw = google_raw_data.get('current', {})
    hourly_raw = google_raw_data.get('hourly', {})
    daily_raw = google_raw_data.get('daily', {})

    # Timezone handling
    tz_offset = 0
    tz_name = daily_raw.get('timeZone', {}).get('id') or current_raw.get('timeZone', {}).get('id', 'UTC')
    print(f"Google reported Timezone ID: {tz_name}. Assuming UTC offset 0 for timestamps.")

    transformed_data = {
        'lat': lat, 'lon': lon, 'timezone': tz_name, 'timezone_offset': tz_offset,
        'current': {}, 'hourly': [], 'daily': []
    }

    # Process Current Conditions
    cc = current_raw # Data is at root of current response

    raw_dt_str = cc.get('currentTime')
    print(f"DEBUG: Raw Google current dateTime string: {raw_dt_str}")
    current_ts = parse_iso_time(raw_dt_str)

    if current_ts == 0:
        print("Warning: Using current UTC time as fallback for current conditions timestamp.")
        current_ts = int(datetime.now(timezone.utc).timestamp())

    temp = cc.get('temperature', {}).get('degrees', 0.0)
    feels_like = cc.get('feelsLikeTemperature', {}).get('degrees', temp)
    humidity = cc.get('relativeHumidity', 50)
    pressure = cc.get('airPressure', {}).get('meanSeaLevelMillibars', 1013.0)
    dew_point = cc.get('dewPoint', {}).get('degrees', 0.0)
    wind_speed_kph = cc.get('wind', {}).get('speed', {}).get('value', 0.0)
    wind_speed_mps = round(wind_speed_kph / 3.6, 2)
    wind_gust_kph = cc.get('wind', {}).get('gust', {}).get('value', 0.0)
    wind_gust_mps = round(wind_gust_kph / 3.6, 2)
    wind_deg = cc.get('wind', {}).get('direction', {}).get('degrees', 0)
    uv_index = cc.get('uvIndex', 0)
    condition_code = cc.get('weatherCondition', {}).get('type', 'CONDITION_UNSPECIFIED')
    description = cc.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
    google_icon_base_uri = cc.get('weatherCondition', {}).get('iconBaseUri')
    is_day = cc.get('isDaytime', True)
    visibility_km = cc.get('visibility', {}).get('distance', 10.0)
    visibility_m = int(visibility_km * 1000)
    cloud_cover = cc.get('cloudCover', 50)
    precip_amount = cc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0)
    precip_prob_percent = cc.get('precipitation', {}).get('probability', {}).get('percent', 0)
    precip_pop = precip_prob_percent / 100.0
    owm_icon = get_owm_icon_from_google_code(condition_code, is_day)

    transformed_data['current'] = {
        'dt': current_ts, 'sunrise': 0, 'sunset': 0, 'temp': temp, 'feels_like': feels_like,
        'pressure': pressure, 'humidity': humidity, 'dew_point': dew_point, 'uvi': uv_index,
        'clouds': cloud_cover, 'visibility': visibility_m, 'wind_speed': wind_speed_mps,
        'wind_deg': wind_deg, 'wind_gust': wind_gust_mps,
        'weather': [{
            'id': 0, 'main': description.split()[0], 'description': description,
            'icon': owm_icon, 'google_icon_uri': google_icon_base_uri
        }],
        'rain': {'1h': precip_amount}, 'pop': precip_pop
    }

    # Process Hourly Forecast
    hourly_forecasts = hourly_raw.get('forecastHours', [])
    if not hourly_forecasts:
         print("Warning: 'forecastHours' list missing or empty in Google response.")

    for hour_fc in hourly_forecasts:
        ts = parse_iso_time(hour_fc.get('interval', {}).get('startTime'))
        if ts == 0:
            print(f"Warning: Skipping hourly forecast due to failed timestamp parse: {hour_fc.get('interval', {}).get('startTime')}")
            continue

        temp = hour_fc.get('temperature', {}).get('degrees', 0.0)
        feels_like = hour_fc.get('feelsLikeTemperature', {}).get('degrees', temp)
        humidity = hour_fc.get('relativeHumidity', 50)
        pressure = hour_fc.get('airPressure', {}).get('meanSeaLevelMillibars', 1013.0)
        dew_point = hour_fc.get('dewPoint', {}).get('degrees', 0.0)
        wind_speed_kph = hour_fc.get('wind', {}).get('speed', {}).get('value', 0.0)
        wind_speed_mps = round(wind_speed_kph / 3.6, 2)
        wind_gust_kph = hour_fc.get('wind', {}).get('gust', {}).get('value', 0.0)
        wind_gust_mps = round(wind_gust_kph / 3.6, 2)
        wind_deg = hour_fc.get('wind', {}).get('direction', {}).get('degrees', 0)
        uv_index = hour_fc.get('uvIndex', 0)
        condition_code = hour_fc.get('weatherCondition', {}).get('type', 'CONDITION_UNSPECIFIED')
        description = hour_fc.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
        google_icon_base_uri = hour_fc.get('weatherCondition', {}).get('iconBaseUri')
        is_day = hour_fc.get('isDaytime', True)
        visibility_km = hour_fc.get('visibility', {}).get('distance', 10.0)
        visibility_m = int(visibility_km * 1000)
        cloud_cover = hour_fc.get('cloudCover', 50)
        precip_prob_percent = hour_fc.get('precipitation', {}).get('probability', {}).get('percent', 0)
        precip_pop = precip_prob_percent / 100.0
        precip_amount = hour_fc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0)
        owm_icon = get_owm_icon_from_google_code(condition_code, is_day)

        hour_entry = {
            'dt': ts, 'temp': temp, 'feels_like': feels_like, 'pressure': pressure,
            'humidity': humidity, 'dew_point': dew_point, 'uvi': uv_index, 'clouds': cloud_cover,
            'visibility': visibility_m, 'wind_speed': wind_speed_mps, 'wind_deg': wind_deg,
            'wind_gust': wind_gust_mps,
            'weather': [{
                'id': 0, 'main': description.split()[0], 'description': description,
                'icon': owm_icon, 'google_icon_uri': google_icon_base_uri
            }],
            'rain': {'1h': precip_amount}, 'pop': precip_pop
        }
        transformed_data['hourly'].append(hour_entry)

    transformed_data['hourly'] = transformed_data['hourly'][:48]

    # Process Daily Forecast
    daily_forecasts = daily_raw.get('forecastDays', [])
    if not daily_forecasts:
        print("Warning: 'forecastDays' list missing or empty in Google response.")

    for day_fc in daily_forecasts:
        day_ts = parse_google_date(day_fc.get('displayDate'))
        if day_ts == 0:
            print(f"Warning: Skipping daily forecast due to failed date parse: {day_fc.get('displayDate')}")
            continue

        temp_max = day_fc.get('maxTemperature', {}).get('degrees', 0.0)
        temp_min = day_fc.get('minTemperature', {}).get('degrees', 0.0)
        apparent_max = day_fc.get('feelsLikeMaxTemperature', {}).get('degrees', temp_max)
        apparent_min = day_fc.get('feelsLikeMinTemperature', {}).get('degrees', temp_min)
        sunrise_ts = parse_iso_time(day_fc.get('sunEvents', {}).get('sunriseTime'))
        sunset_ts = parse_iso_time(day_fc.get('sunEvents', {}).get('sunsetTime'))

        daytime_fc = day_fc.get('daytimeForecast', {})
        nighttime_fc = day_fc.get('nighttimeForecast', {})

        # Prioritize daytime forecast for representative values
        if daytime_fc:
            condition_code = daytime_fc.get('weatherCondition', {}).get('type', 'CONDITION_UNSPECIFIED')
            description = daytime_fc.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
            google_icon_base_uri = daytime_fc.get('weatherCondition', {}).get('iconBaseUri')
            humidity = daytime_fc.get('relativeHumidity', 50)
            uv_index = daytime_fc.get('uvIndex', 0)
            precip_prob_percent = daytime_fc.get('precipitation', {}).get('probability', {}).get('percent', 0)
            wind_speed_kph = daytime_fc.get('wind', {}).get('speed', {}).get('value', 0.0)
            wind_gust_kph = daytime_fc.get('wind', {}).get('gust', {}).get('value', 0.0)
            wind_deg = daytime_fc.get('wind', {}).get('direction', {}).get('degrees', 0)
            cloud_cover = daytime_fc.get('cloudCover', 50)
            precip_amount_day = daytime_fc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0)
            precip_amount_night = nighttime_fc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0)
        else: # Fallback if daytime is missing
            print(f"Warning: Missing 'daytimeForecast' for day {datetime.fromtimestamp(day_ts, tz=timezone.utc).date()}. Using fallbacks.")
            condition_code = nighttime_fc.get('weatherCondition', {}).get('type', 'CONDITION_UNSPECIFIED')
            description = nighttime_fc.get('weatherCondition', {}).get('description', {}).get('text', 'Unknown')
            google_icon_base_uri = nighttime_fc.get('weatherCondition', {}).get('iconBaseUri')
            humidity = nighttime_fc.get('relativeHumidity', 50)
            uv_index = 0 # Night UV
            precip_prob_percent = nighttime_fc.get('precipitation', {}).get('probability', {}).get('percent', 0)
            wind_speed_kph = nighttime_fc.get('wind', {}).get('speed', {}).get('value', 0.0)
            wind_gust_kph = nighttime_fc.get('wind', {}).get('gust', {}).get('value', 0.0)
            wind_deg = nighttime_fc.get('wind', {}).get('direction', {}).get('degrees', 0)
            cloud_cover = nighttime_fc.get('cloudCover', 50)
            precip_amount_day = 0.0
            precip_amount_night = nighttime_fc.get('precipitation', {}).get('qpf', {}).get('quantity', 0.0)

        owm_icon = get_owm_icon_from_google_code(condition_code, True)
        precip_pop = precip_prob_percent / 100.0
        precip_total_mm = precip_amount_day + precip_amount_night
        wind_speed_mps = round(wind_speed_kph / 3.6, 2)
        wind_gust_mps = round(wind_gust_kph / 3.6, 2)
        temp_day_approx = (temp_max + temp_min) / 2

        day_entry = {
            'dt': day_ts, 'sunrise': sunrise_ts, 'sunset': sunset_ts, 'moonrise': 0, 'moonset': 0, 'moon_phase': 0,
            'summary': description,
            'temp': {'day': temp_day_approx, 'min': temp_min, 'max': temp_max, 'night': temp_min, 'eve': temp_min, 'morn': temp_min},
            'feels_like': {'day': apparent_max, 'night': apparent_min, 'eve': apparent_min, 'morn': apparent_min},
            'pressure': 1013, 'humidity': humidity, 'dew_point': 0,
            'wind_speed': wind_speed_mps, 'wind_deg': wind_deg, 'wind_gust': wind_gust_mps,
            'weather': [{
                'id': 0, 'main': description.split()[0], 'description': description,
                'icon': owm_icon, 'google_icon_uri': google_icon_base_uri
            }],
            'clouds': cloud_cover, 'pop': precip_pop, 'rain': precip_total_mm, 'uvi': uv_index
        }
        transformed_data['daily'].append(day_entry)

    transformed_data['daily'] = transformed_data['daily'][:8]

    # Update current sunrise/sunset from first daily entry if available
    if transformed_data['daily']:
        transformed_data['current']['sunrise'] = transformed_data['daily'][0].get('sunrise', 0)
        transformed_data['current']['sunset'] = transformed_data['daily'][0].get('sunset', 0)

    # Final check
    if not transformed_data['current']: print("ERROR: Transformation resulted in empty 'current' data.")
    if not transformed_data['hourly']: print("Warning: Transformation resulted in empty 'hourly' data.")
    if not transformed_data['daily']: print("Warning: Transformation resulted in empty 'daily' data.")

    return transformed_data


# --- Base Class ---
class WeatherProvider(ABC):
    """Abstract base class for weather data providers."""
    def __init__(self, lat, lon, cache_file=CACHE_FILE, cache_duration=CACHE_DURATION_MINUTES):
        self.lat = lat
        self.lon = lon
        self.cache_file = cache_file
        self.cache_duration = timedelta(minutes=cache_duration)
        self._data = None
        self.provider_name = "UnknownProvider" # Default, should be overridden

    def _is_cache_valid(self):
        """Checks if the cache file exists and is recent."""
        if not os.path.exists(self.cache_file):
            return False
        try:
            modified_time = os.path.getmtime(self.cache_file)
            if datetime.now() - datetime.fromtimestamp(modified_time) < self.cache_duration:
                return True
        except OSError as e:
            print(f"Error checking cache file timestamp: {e}")
        return False

    def _load_from_cache(self):
        """Loads data from the cache file."""
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
            # Basic validation
            if isinstance(data, dict) and 'current' in data and 'hourly' in data and 'daily' in data:
                 self._data = data
                 print(f"Using cached weather data for {self.provider_name}.")
                 return True
            else:
                print(f"Cached data format invalid for {self.provider_name}.")
                return False
        except (json.JSONDecodeError, OSError, Exception) as e:
            print(f"Error loading or validating cache file {self.cache_file} for {self.provider_name}: {e}")
            return False

    def _save_to_cache(self, data_to_save):
        """Saves the current data to the cache file."""
        if data_to_save:
            try:
                with open(self.cache_file, 'w') as f:
                    json.dump(data_to_save, f, indent=4)
                print(f"Weather data for {self.provider_name} saved to cache: {self.cache_file}")
            except (OSError, TypeError) as e:
                print(f"Error saving data to cache {self.cache_file} for {self.provider_name}: {e}")
        else:
            print(f"No data to save to cache for {self.provider_name}.")

    @abstractmethod
    async def _fetch_from_api(self):
        """Abstract method to fetch data from the specific API and return structured data."""
        pass

    async def fetch_data(self):
        """Fetches data, using cache if valid, otherwise calls API."""
        if self._is_cache_valid():
            if self._load_from_cache():
                return True # Data loaded from cache
        
        print(f"Fetching new weather data from API for {self.provider_name}...")
        fetched_api_data = await self._fetch_from_api() # Call the subclass implementation

        if fetched_api_data:
            self._data = fetched_api_data # Store the successfully fetched data
            self._save_to_cache(self._data)
            return True
        else:
            print(f"Failed to fetch new data from API for {self.provider_name}.")
            # Attempt to load old cache as fallback if fetching failed
            if os.path.exists(self.cache_file):
                print(f"Attempting to use potentially outdated cache as fallback for {self.provider_name}.")
                if self._load_from_cache():
                     return True # Fallback loaded
                else:
                     return False # Fallback failed too
            return False # Indicate fetch failure

    def get_current_data(self):
        """Returns the 'current' weather data dictionary."""
        return self._data.get('current') if self._data else None

    def get_hourly_data(self):
        """Returns the 'hourly' weather data list."""
        return self._data.get('hourly') if self._data else None

    def get_daily_data(self):
        """Returns the 'daily' weather data list."""
        return self._data.get('daily') if self._data else None

    def get_all_data(self):
        """Returns the entire weather data dictionary."""
        return self._data


# --- OpenWeatherMap Subclass ---
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
        response = None
        # Use aiohttp for async fetch
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=30) as response:
                    response.raise_for_status()
                    print(f"{self.provider_name} data fetched successfully.")
                    return await response.json()
            except aiohttp.ClientError as e:
                print(f"Error fetching {self.provider_name} data: {e}")
                if response is not None:
                    try:
                        print(f"Response Body: {await response.text()}")
                    except Exception:
                        print("Could not read response body.")
                return None
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                print(f"Error parsing {self.provider_name} data: {e}")
                return None
            except Exception as e:
                 print(f"An unexpected error occurred during {self.provider_name} fetch: {e}")
                 traceback.print_exc()
                 return None


# --- Meteomatics Subclass ---
class MeteomaticsProvider(WeatherProvider):
    """Weather provider for Meteomatics API."""
    def __init__(self, username, password, lat, lon, **kwargs):
        super().__init__(lat, lon, **kwargs)
        self.username = username
        self.password = password
        self.provider_name = "Meteomatics"
        if not username or not password:
            raise ValueError("Meteomatics username and password are required.")

    async def _fetch_from_api(self):
        """Fetches data from Meteomatics API (basic plan 10 params) and transforms it."""
        print(f"Fetching data from {self.provider_name} (basic plan 10 params)...")
        base_url = "https://api.meteomatics.com"
        now = datetime.utcnow()
        start_time = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time = (now + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        parameters = [
            't_2m:C', 'wind_speed_10m:ms', 'precip_1h:mm', 'weather_symbol_1h:idx', 'uv:idx',
            't_max_2m_24h:C', 't_min_2m_24h:C', 'precip_24h:mm', 'weather_symbol_24h:idx',
            'wind_gusts_10m_24h:ms'
        ]
        parameters_str = ",".join(parameters)
        location_str = f"{self.lat},{self.lon}"
        time_interval = "PT1H"
        api_url = (
            f"{base_url}/{start_time}--{end_time}:{time_interval}/"
            f"{parameters_str}/{location_str}/json"
        )
        print(f"Requesting URL: {api_url}")
        response = None
        # Use aiohttp for async fetch
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    api_url,
                    auth=aiohttp.BasicAuth(self.username, self.password),
                    timeout=45
                ) as response:
                    print(f"Meteomatics Response Status Code: {response.status}")
                    response.raise_for_status()
                    raw_data = await response.json()
                    print(f"{self.provider_name} raw data fetched successfully.")

                    transformed_data = transform_meteomatics_data(raw_data, self.lat, self.lon)
                    if transformed_data:
                        print("Meteomatics data transformed successfully.")
                        return transformed_data
                    else:
                        print("Meteomatics data transformation failed.")
                        return None
            except aiohttp.ClientError as e:
                print(f"Error fetching {self.provider_name} data: {e}")
                response_text = await response.text() if response is not None else "No response"
                print(f"Response Body: {response_text}")
                return None
            except json.JSONDecodeError as e:
                print(f"Error decoding {self.provider_name} JSON response: {e}")
                print(f"Response Text: {await response.text() if response else 'No response'}")
                return None
            except Exception as e:
                print(f"An unexpected error occurred during {self.provider_name} fetch/transform: {e}")
                traceback.print_exc()
                return None


# --- Open-Meteo Subclass ---
class OpenMeteoProvider(WeatherProvider):
    """Weather provider for Open-Meteo API."""
    def __init__(self, lat, lon, **kwargs):
        super().__init__(lat, lon, **kwargs)
        self.provider_name = "Open-Meteo"

    async def _fetch_from_api(self):
        """Fetches data from Open-Meteo API and transforms it."""
        print(f"Fetching data from {self.provider_name}...")
        base_url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "current_weather": "true",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
            "timezone": "auto",
            "forecast_days": 7,
            "hourly": [
                "temperature_2m", "relative_humidity_2m", "apparent_temperature",
                "precipitation_probability", "precipitation", "rain", "snowfall",
                "weather_code", "pressure_msl", "cloud_cover", "visibility",
                "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
                "uv_index", "is_day"
            ],
            "daily": [
                "weather_code", "temperature_2m_max", "temperature_2m_min",
                "apparent_temperature_max", "apparent_temperature_min",
                "sunrise", "sunset", "uv_index_max", "precipitation_sum",
                "rain_sum", "snowfall_sum", "precipitation_probability_max",
                "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant"
            ]
        }
        response = None
        # Use aiohttp for async fetch
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(base_url, params=params, timeout=30) as response:
                    print(f"Open-Meteo Response Status Code: {response.status}")
                    response.raise_for_status()
                    raw_data = await response.json()
                    print(f"{self.provider_name} raw data fetched successfully.")

                    transformed_data = transform_open_meteo_data(raw_data, self.lat, self.lon)
                    if transformed_data:
                        print("Open-Meteo data transformed successfully.")
                        return transformed_data
                    else:
                        print("Open-Meteo data transformation failed.")
                        return None
            except aiohttp.ClientError as e:
                print(f"Error fetching {self.provider_name} data: {e}")
                response_text = await response.text() if response is not None else "No response"
                print(f"Response Body: {response_text}")
                return None
            except json.JSONDecodeError as e:
                print(f"Error decoding {self.provider_name} JSON response: {e}")
                print(f"Response Text: {await response.text() if response else 'No response'}")
                return None
            except Exception as e:
                print(f"An unexpected error occurred during {self.provider_name} fetch/transform: {e}")
                traceback.print_exc()
                return None


# --- Google Weather Provider Subclass ---
class GoogleWeatherProvider(WeatherProvider):
    """
    Weather provider for Google Weather API (Maps Platform).
    Requires an API key and enabled billing. Uses :lookup GET endpoints.
    """
    def __init__(self, api_key, lat, lon, **kwargs):
        super().__init__(lat, lon, **kwargs)
        self.api_key = api_key
        self.provider_name = "Google Weather"
        self.base_url = "https://weather.googleapis.com/v1"
        if not api_key:
            raise ValueError("Google Maps Platform API key is required.")

    async def _fetch_from_api(self):
        """Fetches current, hourly, and daily data from Google Weather API using GET :lookup."""
        print(f"Fetching data from {self.provider_name}...")
        print("!!! WARNING: Google Weather API usage may incur costs. !!!")

        base_lookup_params = {
            "key": self.api_key,
            "location.latitude": self.lat,
            "location.longitude": self.lon
        }

        raw_data = {}
        endpoint_paths = {
            'current': '/currentConditions:lookup',
            'hourly': '/forecast/hours:lookup',
            'daily': '/forecast/days:lookup'
        }
        success = True
        response = None

        # Use aiohttp for async fetch
        async with aiohttp.ClientSession() as session:
            for key, path_suffix in endpoint_paths.items():
                response = None # Reset response for each request
                url = f"{self.base_url}{path_suffix}"
                request_params = base_lookup_params.copy()
                if key == 'hourly':
                    request_params['hours'] = 48 # Request 48 hours
                elif key == 'daily':
                    request_params['days'] = 8 # Request 8 days

                print(f"Requesting {key} data from Google...")
                print(f"Requesting GET URL: {url} with params: {request_params}")

                try:
                    async with session.get(url, params=request_params, timeout=30) as response:
                        print(f"Google {key} Response Status Code: {response.status}")
                        response.raise_for_status()
                        raw_data[key] = await response.json()
                        print(f"Google {key} data fetched successfully.")

                except aiohttp.ClientError as e:
                    print(f"Error fetching Google {key} data: {e}")
                    response_text = await response.text() if response is not None else "No response"
                    print(f"Response Body: {response_text}")
                    success = False
                    break
                except json.JSONDecodeError as e:
                    print(f"Error decoding Google {key} JSON response: {e}")
                    print(f"Response Text: {await response.text() if response else 'No response'}")
                    success = False
                    break
                except Exception as e:
                    print(f"An unexpected error occurred during Google {key} fetch: {e}")
                    traceback.print_exc()
                    success = False
                    break

        if not success:
            return None

        # Check if essential data parts were actually received
        if 'current' not in raw_data:
            print("Error: Current conditions data missing from Google response after fetch.")
            return None # Cannot proceed without current data
        if 'hourly' not in raw_data:
            print("Warning: Hourly forecast data missing from Google response after fetch.")
            raw_data['hourly'] = {} # Provide empty dict if missing
        if 'daily' not in raw_data:
            print("Warning: Daily forecast data missing from Google response after fetch.")
            raw_data['daily'] = {} # Provide empty dict if missing

        # --- Transformation ---
        transformed_data = transform_google_weather_data(raw_data, self.lat, self.lon)
        if transformed_data:
            print("Google Weather data transformed successfully.")
            return transformed_data
        else:
            print("Google Weather data transformation failed.")
            return None


# --- SMHI Provider Subclass ---
class SMHIProvider(WeatherProvider):
    """Weather provider for SMHI (Swedish Meteorological and Hydrological Institute) using pysmhi."""
    def __init__(self, lat, lon, **kwargs):
        super().__init__(lat, lon, **kwargs)
        self.provider_name = "SMHI"
        # Ensure pysmhi is available
        try:
            from pysmhi import SMHIPointForecast
            self.SMHIPointForecast = SMHIPointForecast # Store for use in async method
        except ImportError:
            print("Error: pysmhi library not found. Please install it to use the SMHI provider.")
            raise

    async def _fetch_from_api(self):
        """Fetches data from SMHI using pysmhi and transforms it."""
        print(f"Fetching data from {self.provider_name}...")

        # pysmhi requires an aiohttp session
        async with aiohttp.ClientSession() as session:
            try:
                # SMHIPointForecast expects lon, lat order
                client = self.SMHIPointForecast(str(self.lon), str(self.lat), session)

                # Fetch both daily and hourly forecasts
                smhi_daily_data = await client.async_get_daily_forecast()
                smhi_hourly_data = await client.async_get_hourly_forecast()

                print(f"{self.provider_name} raw data fetched successfully.")

                # Transform the data
                transformed_data = transform_smhi_data(smhi_daily_data, smhi_hourly_data, self.lat, self.lon)

                if transformed_data:
                    print("SMHI data transformed successfully.")
                    return transformed_data
                else:
                    print("SMHI data transformation failed.")
                    return None

            except Exception as e:
                print(f"Error fetching {self.provider_name} data: {e}")
                traceback.print_exc()
                return None


# --- Factory Function ---
def get_weather_provider(config):
    """
    Factory function to create and return the appropriate WeatherProvider instance.
    """
    provider_name = config.get("weather_provider", "openweathermap").lower()
    lat = config.get("latitude")
    lon = config.get("longitude")

    if lat is None or lon is None:
        raise ValueError("Latitude and Longitude must be defined in config.json")

    print(f"Attempting to initialize provider: {provider_name}")

    if provider_name == "meteomatics":
        username = config.get("meteomatics_username")
        password = config.get("meteomatics_password")
        try:
            return MeteomaticsProvider(username, password, lat, lon)
        except ValueError as e:
            print(f"Configuration error for Meteomatics: {e}")
            return None
    elif provider_name == "openweathermap":
        api_key = config.get("openweathermap_api_key")
        try:
            return OpenWeatherMapProvider(api_key, lat, lon)
        except ValueError as e:
            print(f"Configuration error for OpenWeatherMap: {e}")
            return None
    elif provider_name == "open-meteo":
        try:
            return OpenMeteoProvider(lat, lon)
        except Exception as e:
            print(f"Error initializing OpenMeteoProvider: {e}")
            return None
    elif provider_name == "google":
        api_key = config.get("google_api_key")
        try:
            return GoogleWeatherProvider(api_key, lat, lon)
        except ValueError as e:
            print(f"Configuration error for Google Weather: {e}")
            return None
        except Exception as e:
             print(f"Error initializing GoogleWeatherProvider: {e}")
             return None
    elif provider_name == "smhi":
        try:
            return SMHIProvider(lat, lon)
        except ImportError: # pysmhi might not be installed
            print("Failed to initialize SMHIProvider: pysmhi library likely missing.")
            return None
        except Exception as e:
            print(f"Error initializing SMHIProvider: {e}")
            return None
    else:
        print(
            f"Error: Unknown weather_provider '{provider_name}' in config.json. "
            f"Use 'openweathermap', 'meteomatics', 'open-meteo', 'google', or 'smhi'."
        )
        return None
