# provider_smhi.py
from datetime import datetime, timezone
import traceback
import aiohttp
from aiohttp import ClientResponseError

from weather_provider_base import WeatherProvider, HourlyDataPoint, DailyDataPoint

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
        return None
    transformed_data = {'lat': lat, 'lon': lon, 'timezone': 'UTC', 'timezone_offset': 0,
                        'current': {}, 'hourly': [], 'daily': []}
    
    # --- Hourly Processing ---
    if smhi_hourly:
        for hour_fc in smhi_hourly:
            hour_dict = hour_fc.__dict__ if hasattr(hour_fc, '__dict__') else hour_fc
            ts = int(hour_dict.get('valid_time', datetime.now(timezone.utc)).timestamp())
            symbol = hour_dict.get('symbol', 0)
            description = SMHI_SYMBOL_DESC.get(symbol, 'Unknown')
            thunder = hour_dict.get('thunder', 0)
            if thunder > 0 and 'Thunder' not in description: description += " (Thunder)"

            hourly_point = HourlyDataPoint(
                dt=ts,
                temp=hour_dict.get('temperature', 0.0),
                feels_like=hour_dict.get('temperature', 0.0),
                pressure=hour_dict.get('pressure', 1013.0),
                humidity=hour_dict.get('humidity', 50),
                clouds=hour_dict.get('total_cloud', 50),
                visibility=int(hour_dict.get('visibility', 10.0) * 1000),
                wind_speed=hour_dict.get('wind_speed', 0.0),
                wind_deg=hour_dict.get('wind_direction', 0),
                wind_gust=hour_dict.get('wind_gust', 0.0),
                weather_id=symbol,
                weather_main=description.split()[0] if description else "Unknown",
                weather_description=description,
                weather_icon=get_owm_icon_from_smhi_code(symbol),
                rain_1h=hour_dict.get('mean_precipitation', 0.0),
                snow_1h=hour_dict.get('frozen_precipitation', 0.0)
            )
            transformed_data['hourly'].append(hourly_point)

    # --- Daily Data Processing ---
    start_index = 0
    if smhi_daily:
        if len(smhi_daily) > 1:
            first_day = getattr(smhi_daily[0], 'valid_time', datetime.min.replace(tzinfo=timezone.utc)).date()
            second_day = getattr(smhi_daily[1], 'valid_time', datetime.min.replace(tzinfo=timezone.utc)).date()
            if first_day == second_day:
                start_index = 1

        processed_dates = set()
        for day_fc in smhi_daily[start_index:]:
            day_dict = day_fc.__dict__ if hasattr(day_fc, '__dict__') else day_fc
            day_date = day_dict.get('valid_time', datetime.now(timezone.utc)).date()
            
            if day_date in processed_dates: continue
            processed_dates.add(day_date)
            
            normalized_dt = datetime(day_date.year, day_date.month, day_date.day, 0, 0, 0, tzinfo=timezone.utc)
            symbol = day_dict.get('symbol', 0)
            description = SMHI_SYMBOL_DESC.get(symbol, 'Unknown')
            temp_max = day_dict.get('temperature_max', day_dict.get('temperature', 0.0))
            temp_min = day_dict.get('temperature_min', day_dict.get('temperature', 0.0))

            daily_point = DailyDataPoint(
                dt=int(normalized_dt.timestamp()),
                summary=description,
                temp_day=(temp_max + temp_min) / 2,
                temp_min=temp_min,
                temp_max=temp_max,
                temp_night=temp_min,
                temp_eve=temp_min,
                temp_morn=temp_min,
                feels_like_day=(temp_max + temp_min) / 2,
                feels_like_night=temp_min,
                pressure=day_dict.get('pressure', 1013.0),
                humidity=day_dict.get('humidity', 50),
                wind_speed=day_dict.get('wind_speed', 0.0),
                wind_deg=day_dict.get('wind_direction', 0),
                wind_gust=day_dict.get('wind_gust', 0.0),
                weather_id=symbol,
                weather_main=description.split()[0] if description else "Unknown",
                weather_description=description,
                weather_icon=get_owm_icon_from_smhi_code(symbol),
                clouds=day_dict.get('total_cloud', 50),
                rain=day_dict.get('total_precipitation', 0.0)
            )
            transformed_data['daily'].append(daily_point)

    # --- Current Data Fallback ---
    if transformed_data['hourly']:
        cur = transformed_data['hourly'][0]
        transformed_data['current'] = {
            'dt': cur.dt, 'temp': cur.temp, 'feels_like': cur.feels_like,
            'pressure': cur.pressure, 'humidity': cur.humidity, 'uvi': 0,
            'clouds': cur.clouds, 'visibility': cur.visibility,
            'wind_speed': cur.wind_speed, 'wind_deg': cur.wind_deg, 'wind_gust': cur.wind_gust,
            'weather': [{'id': cur.weather_id, 'main': cur.weather_main, 
                         'description': cur.weather_description, 'icon': cur.weather_icon}],
            'rain': {'1h': cur.rain_1h}
        }
    elif transformed_data['daily']:
        cur = transformed_data['daily'][0]
        transformed_data['current'] = {
            'dt': cur.dt, 'temp': cur.temp_day, 'feels_like': cur.feels_like_day,
            'pressure': cur.pressure, 'humidity': cur.humidity, 'uvi': 0,
            'wind_speed': cur.wind_speed, 'wind_deg': cur.wind_deg,
            'weather': [{'id': cur.weather_id, 'main': cur.weather_main, 
                         'description': cur.weather_description, 'icon': cur.weather_icon}],
            'rain': {'1h': 0}
        }
    
    if not transformed_data['current']:
        # Minimal fallback
        transformed_data['current'] = {
            'dt': int(datetime.now(timezone.utc).timestamp()),
            'temp': 0, 'weather': [{'icon': 'na', 'description': 'Unknown'}]
        }

    return transformed_data

class SMHIProvider(WeatherProvider):
    def __init__(self, lat, lon, **kwargs):
        provider_id = kwargs.pop("provider_id_for_cache", "smhi")
        super().__init__(lat, lon, provider_id_for_cache=provider_id, **kwargs)
        self.provider_name = "SMHI"
        try:
            from pysmhi import SMHIPointForecast
            self.SMHIPointForecast = SMHIPointForecast
        except ImportError:
            print("Error: pysmhi library not found.")
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
            
            except ClientResponseError as e:
                # Specific handling for SMHI "Point Out of Bounds" (404)
                if e.status == 404:
                    print(f"SMHI Error: The coordinates ({self.lat}, {self.lon}) are out of bounds for the SMHI model (Scandinavia only).")
                    return None
                print(f"HTTP Error fetching {self.provider_name}: {e}")
                return None
            except Exception as e:
                print(f"Error fetching {self.provider_name} data: {e}")
                traceback.print_exc()
                return None