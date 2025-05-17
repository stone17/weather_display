# provider_smhi.py
from datetime import datetime, timezone
import traceback
import aiohttp

from weather_provider_base import WeatherProvider, parse_iso_time

# --- SMHI SYMBOL Mappings ---
SMHI_SYMBOL_TO_OWM_ICON = {
    1: '01d', 2: '02d', 3: '03d', 4: '04d', 5: '04d', 6: '04d', 7: '50d',
    8: '09d', 9: '09d', 10: '09d', 11: '11d', 12: '13d', 13: '13d', 14: '13d',
    15: '13d', 16: '13d', 17: '13d', 18: '10d', 19: '10d', 20: '10d', 21: '11d',
    22: '13d', 23: '13d', 24: '13d', 25: '13d', 26: '13d', 27: '13d',
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

def get_owm_icon_from_smhi_code(code):
    return SMHI_SYMBOL_TO_OWM_ICON.get(code, 'na')

def transform_smhi_data(smhi_daily, smhi_hourly, lat, lon):
    if not smhi_daily and not smhi_hourly:
        print("Error: No data received from SMHI.")
        return None
    transformed_data = {'lat': lat, 'lon': lon, 'timezone': 'UTC', 'timezone_offset': 0,
                        'current': {}, 'hourly': [], 'daily': []}
    if smhi_hourly:
        for hour_fc in smhi_hourly:
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
            visibility = hour_dict.get('visibility', 10.0) * 1000
            description = SMHI_SYMBOL_DESC.get(symbol, 'Unknown')
            owm_icon = get_owm_icon_from_smhi_code(symbol)
            if thunder > 0 and 'Thunder' not in description: description += " (Thunder)"
            hour_entry = {'dt': ts, 'temp': temp, 'feels_like': temp, 'pressure': pressure,
                          'humidity': humidity, 'dew_point': 0, 'uvi': 0, 'clouds': total_cloud,
                          'visibility': visibility, 'wind_speed': wind_speed, 'wind_deg': wind_deg,
                          'wind_gust': wind_gust, 'weather': [{'id': symbol, 'main': description.split()[0],
                          'description': description, 'icon': owm_icon}],
                          'rain': {'1h': mean_precipitation}, 'pop': 0}
            transformed_data['hourly'].append(hour_entry)
    processed_dates = set()
    if smhi_daily:
        for day_fc in smhi_daily:
            day_dict = day_fc.__dict__ if hasattr(day_fc, '__dict__') else day_fc
            original_valid_time = day_dict.get('valid_time', datetime.now(timezone.utc))
            day_date_obj = original_valid_time.date()
            if day_date_obj in processed_dates: continue
            processed_dates.add(day_date_obj)
            normalized_dt_utc = datetime(day_date_obj.year, day_date_obj.month, day_date_obj.day, 0, 0, 0, tzinfo=timezone.utc)
            day_ts = int(normalized_dt_utc.timestamp())
            temp_max = day_dict.get('temperature_max', day_dict.get('temperature', 0.0))
            temp_min = day_dict.get('temperature_min', day_dict.get('temperature', 0.0))
            total_precipitation = day_dict.get('total_precipitation', 0.0)
            symbol = day_dict.get('symbol', 0)
            wind_speed = day_dict.get('wind_speed', 0.0)
            wind_gust = day_dict.get('wind_gust', 0.0)
            thunder = day_dict.get('thunder', 0)
            description = SMHI_SYMBOL_DESC.get(symbol, 'Unknown')
            owm_icon = get_owm_icon_from_smhi_code(symbol)
            if thunder > 0 and 'Thunder' not in description: description += " (Thunder)"
            day_entry = {'dt': day_ts, 'sunrise': 0, 'sunset': 0, 'moonrise': 0, 'moonset': 0, 'moon_phase': 0,
                         'summary': description, 'temp': {'day': (temp_max + temp_min) / 2, 'min': temp_min, 'max': temp_max, 'night': temp_min, 'eve': temp_min, 'morn': temp_min},
                         'feels_like': {'day': (temp_max + temp_min) / 2, 'night': temp_min, 'eve': temp_min, 'morn': temp_min},
                         'pressure': day_dict.get('pressure', 1013.0), 'humidity': day_dict.get('humidity', 50), 'dew_point': 0,
                         'wind_speed': wind_speed, 'wind_deg': day_dict.get('wind_direction', 0), 'wind_gust': wind_gust,
                         'weather': [{'id': symbol, 'main': description.split()[0], 'description': description, 'icon': owm_icon}],
                         'clouds': day_dict.get('total_cloud', 50), 'pop': 0, 'rain': total_precipitation, 'uvi': 0}
            transformed_data['daily'].append(day_entry)
    if transformed_data['hourly']:
        transformed_data['current'] = transformed_data['hourly'][0].copy()
        if transformed_data['daily']:
             transformed_data['current']['sunrise'] = transformed_data['daily'][0].get('sunrise', 0)
             transformed_data['current']['sunset'] = transformed_data['daily'][0].get('sunset', 0)
    elif transformed_data['daily']:
         first_daily = transformed_data['daily'][0]
         transformed_data['current'] = {'dt': first_daily['dt'], 'temp': first_daily['temp']['day'], 'feels_like': first_daily['feels_like']['day'],
                                        'pressure': first_daily['pressure'], 'humidity': first_daily['humidity'], 'uvi': first_daily['uvi'],
                                        'wind_speed': first_daily['wind_speed'], 'wind_deg': first_daily['wind_deg'], 'wind_gust': first_daily['wind_gust'],
                                        'weather': first_daily['weather'], 'rain': {'1h': 0}, 'pop': first_daily['pop'],
                                        'sunrise': first_daily['sunrise'], 'sunset': first_daily['sunset']}
    if not transformed_data['current']: print("ERROR: SMHI Transformation resulted in empty 'current' data.")
    return transformed_data

class SMHIProvider(WeatherProvider):
    def __init__(self, lat, lon, **kwargs):
        super().__init__(lat, lon, **kwargs)
        self.provider_name = "SMHI"
        try:
            from pysmhi import SMHIPointForecast
            self.SMHIPointForecast = SMHIPointForecast
        except ImportError:
            print("Error: pysmhi library not found. Please install it to use the SMHI provider.")
            raise

    async def _fetch_from_api(self):
        print(f"Fetching data from {self.provider_name}...")
        async with aiohttp.ClientSession() as session:
            try:
                client = self.SMHIPointForecast(str(self.lon), str(self.lat), session)
                smhi_daily_data = await client.async_get_daily_forecast()
                smhi_hourly_data = await client.async_get_hourly_forecast()
                print(f"{self.provider_name} raw data fetched successfully.")
                return transform_smhi_data(smhi_daily_data, smhi_hourly_data, self.lat, self.lon)
            except Exception as e:
                print(f"Error fetching {self.provider_name} data: {e}")
                traceback.print_exc()
                return None