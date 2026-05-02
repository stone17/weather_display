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
                feels_like=None,
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
            first_day = getattr(smhi_daily[0], 'valid_time', smhi_daily[0].get('valid_time') if isinstance(smhi_daily[0], dict) else datetime.min.replace(tzinfo=timezone.utc)).date()
            second_day = getattr(smhi_daily[1], 'valid_time', smhi_daily[1].get('valid_time') if isinstance(smhi_daily[1], dict) else datetime.min.replace(tzinfo=timezone.utc)).date()
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
                feels_like_day=None,
                feels_like_night=None,
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

    async def _fetch_direct_v1(self, session, lat_str, lon_str):
        print("Attempting direct fallback fetch using SMHI snow1g V1 API...")
        url = f"https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/{lon_str}/lat/{lat_str}/data.json"
        
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()

        now_utc = datetime.now(timezone.utc)
        start_of_today = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
        
        hourly_data = []
        historical_count = 0

        for entry in data.get('timeSeries', []):
            # NEW API FORMAT: timestamp is under 'time', not 'validTime'
            dt_str = entry.get('time')
            if not dt_str: continue
            
            valid_time = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            
            # Drop historical/hindcast data
            if valid_time < start_of_today:
                historical_count += 1
                continue

            # NEW API FORMAT: flat dictionary under 'data'
            params = entry.get('data', {})
            
            # Fallbacks included in case symbol key names vary slightly in production
            symbol = int(params.get('symbol_code', params.get('weather_symbol', 0)))
            temp = params.get('air_temperature', 0.0)
            pressure = params.get('air_pressure_at_mean_sea_level', 1013.0)
            humidity = params.get('relative_humidity', 50)
            
            clouds_pct = params.get('cloud_area_fraction', 0)
            if 0 < clouds_pct <= 8.0:  # Handle octas if they sneak in
                clouds_pct *= 12.5
                
            visibility = params.get('visibility_in_air', 10.0)
            wind_speed = params.get('wind_speed', 0.0)
            wind_direction = params.get('wind_from_direction', 0)
            wind_gust = params.get('wind_speed_of_gust', 0.0)
            
            precip = params.get('precipitation_amount_mean', params.get('precipitation_amount_mean_deterministic', 0.0))
            thunder = params.get('thunderstorm_probability', 0)
            
            hourly_data.append({
                'valid_time': valid_time,
                'symbol': symbol,
                'temperature': temp,
                'pressure': pressure,
                'humidity': humidity,
                'total_cloud': clouds_pct,
                'visibility': visibility,
                'wind_speed': wind_speed,
                'wind_direction': wind_direction,
                'wind_gust': wind_gust,
                'mean_precipitation': precip,
                'frozen_precipitation': 0.0, # Simplified for now
                'thunder': thunder
            })
        
        print(f"DEBUG SMHI: Dropped {historical_count} past records. Kept {len(hourly_data)} future records.")
            
        daily_map = {}
        for h in hourly_data:
            d_date = h['valid_time'].date()
            if d_date not in daily_map:
                daily_map[d_date] = []
            daily_map[d_date].append(h)
            
        daily_data = []
        for d_date, hours in daily_map.items():
            temps = [h['temperature'] for h in hours]
            precips = [h['mean_precipitation'] for h in hours]
            
            noon_hour = next((h for h in hours if h['valid_time'].hour == 12), hours[len(hours)//2])
            
            daily_data.append({
                'valid_time': datetime(d_date.year, d_date.month, d_date.day, tzinfo=timezone.utc),
                'symbol': noon_hour['symbol'],
                'temperature_max': max(temps) if temps else 0,
                'temperature_min': min(temps) if temps else 0,
                'temperature': sum(temps)/len(temps) if temps else 0,
                'pressure': noon_hour['pressure'],
                'humidity': noon_hour['humidity'],
                'wind_speed': max(h['wind_speed'] for h in hours),
                'wind_direction': noon_hour['wind_direction'],
                'wind_gust': max(h['wind_gust'] for h in hours),
                'total_cloud': sum(h['total_cloud'] for h in hours) / len(hours),
                'total_precipitation': sum(precips)
            })
            
        print(f"{self.provider_name} raw data fetched successfully via direct API.")
        return transform_smhi_data(daily_data, hourly_data, self.lat, self.lon)

    async def _fetch_from_api(self):
        print(f"Fetching data from {self.provider_name}...")
        
        # SMHI API strictly requires a maximum of 6 decimal places. 
        lon_str = str(round(self.lon, 6))
        lat_str = str(round(self.lat, 6))
        
        async with aiohttp.ClientSession() as session:
            try:
                client = self.SMHIPointForecast(lon_str, lat_str, session)
                smhi_daily_data = await client.async_get_daily_forecast()
                smhi_hourly_data = await client.async_get_hourly_forecast()
                print(f"{self.provider_name} raw data fetched successfully via pysmhi.")
                return transform_smhi_data(smhi_daily_data, smhi_hourly_data, self.lat, self.lon)
            
            except Exception as e:
                # Catch failures (including the 404 from the outdated API endpoint)
                # and trigger the direct v1 fallback natively.
                error_msg = str(e)
                print(f"SMHI library fetch failed ({error_msg}). Initiating fallback...")
                
                try:
                    return await self._fetch_direct_v1(session, lat_str, lon_str)
                except Exception as direct_e:
                    print(f"Error fetching direct fallback {self.provider_name} data: {direct_e}")
                    return None