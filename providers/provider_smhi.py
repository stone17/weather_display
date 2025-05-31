# provider_smhi.py
from datetime import datetime, timezone
import traceback
import aiohttp

from weather_provider_base import WeatherProvider, HourlyDataPoint, DailyDataPoint # parse_iso_time not used here

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
    # SMHI codes are directly mapped, no day/night variant needed from the code itself
    return SMHI_SYMBOL_TO_OWM_ICON.get(code, 'na')

def transform_smhi_data(smhi_daily, smhi_hourly, lat, lon):
    if not smhi_daily and not smhi_hourly:
        print("Error: No data received from SMHI.")
        return None
    transformed_data = {'lat': lat, 'lon': lon, 'timezone': 'UTC', 'timezone_offset': 0,
                        'current': {}, 'hourly': [], 'daily': []}
    if smhi_hourly:
        for hour_fc in smhi_hourly:
            # print(hour_fc) # Debugging print
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

            hourly_point = HourlyDataPoint(
                dt=ts,
                temp=temp,
                feels_like=temp, # SMHI does not provide hourly feels_like
                pressure=pressure,
                humidity=humidity,
                # dew_point not directly available
                # uvi not directly available
                clouds=total_cloud,
                visibility=int(visibility),
                wind_speed=wind_speed,
                wind_deg=wind_deg,
                wind_gust=wind_gust,
                weather_id=symbol,
                weather_main=description.split()[0] if description else "Unknown",
                weather_description=description,
                weather_icon=owm_icon,
                rain_1h=mean_precipitation,
                snow_1h=hour_dict.get('frozen_precipitation', 0.0)
                # pop not directly available
            )
            transformed_data['hourly'].append(hourly_point)

    # --- Daily Data Processing ---
    start_index = 0
    if smhi_daily:
        # Check if the first two entries are for the same calendar day
        if len(smhi_daily) > 1:
            first_day_date = getattr(smhi_daily[0], 'valid_time', datetime.min.replace(tzinfo=timezone.utc)).date()
            second_day_date = getattr(smhi_daily[1], 'valid_time', datetime.min.replace(tzinfo=timezone.utc)).date()
            if first_day_date == second_day_date:
                print(f"SMHI: First two daily entries are for the same day ({first_day_date}). Starting daily forecast from the second entry.")
                start_index = 1

        processed_dates = set()
        # Process daily entries starting from the determined index
        for day_fc in smhi_daily[start_index:]: # Loop variable is day_fc
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

            daily_point = DailyDataPoint(
                dt=day_ts,
                summary=description,
                temp_day=(temp_max + temp_min) / 2 if temp_max is not None and temp_min is not None else None,
                temp_min=temp_min,
                temp_max=temp_max,
                temp_night=temp_min, # Approximation
                temp_eve=temp_min,   # Approximation
                temp_morn=temp_min,  # Approximation
                feels_like_day=(temp_max + temp_min) / 2 if temp_max is not None and temp_min is not None else None, # Approximation
                feels_like_night=temp_min, # Approximation
                pressure=day_dict.get('pressure', 1013.0),
                humidity=day_dict.get('humidity', 50),
                wind_speed=wind_speed,
                wind_deg=day_dict.get('wind_direction', 0),
                wind_gust=wind_gust,
                weather_id=symbol,
                weather_main=description.split()[0] if description else "Unknown",
                weather_description=description,
                weather_icon=owm_icon,
                clouds=day_dict.get('total_cloud', 50),
                rain=total_precipitation
                # uvi, pop, sunrise/sunset not directly available from pysmhi daily
            )
            transformed_data['daily'].append(daily_point)

    if transformed_data['hourly']:
        first_hour_dp = transformed_data['hourly'][0]
        # Construct 'current' as a dictionary, similar to OWM structure
        transformed_data['current'] = {
            'dt': first_hour_dp.dt,
            'temp': first_hour_dp.temp,
            'feels_like': first_hour_dp.feels_like, # SMHI doesn't provide, so it's same as temp
            'pressure': first_hour_dp.pressure,
            'humidity': first_hour_dp.humidity,
            'uvi': first_hour_dp.uvi, # SMHI doesn't provide, so it's None or 0
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
            'rain': {'1h': first_hour_dp.rain_1h} if first_hour_dp.rain_1h is not None else None
        }
        # SMHI hourly doesn't have sunrise/sunset, current will get it from daily if available later
    elif transformed_data['daily']:
         first_daily = transformed_data['daily'][0]
         transformed_data['current'] = {'dt': first_daily.dt, 'temp': first_daily.temp_day, 'feels_like': first_daily.feels_like_day,
                                        'pressure': first_daily.pressure, 'humidity': first_daily.humidity, 'uvi': first_daily.uvi,
                                        'wind_speed': first_daily.wind_speed, 'wind_deg': first_daily.wind_deg, 'wind_gust': first_daily.wind_gust,
                                        'weather': [{'id': first_daily.weather_id, 'main': first_daily.weather_main, 'description': first_daily.weather_description, 'icon': first_daily.weather_icon}],
                                        'rain': {'1h': 0}, 'pop': first_daily.pop, # Approximations
                                        'sunrise': first_daily.sunrise, 'sunset': first_daily.sunset}
    if not transformed_data['current']:
        print("ERROR: SMHI Transformation resulted in empty 'current' data.")
        # Create a minimal fallback current if all else fails
        transformed_data['current'] = {
            'dt': int(datetime.now(timezone.utc).timestamp()),
            'temp': 0,
            'feels_like': 0,
            'weather': [{'icon': 'na', 'description': 'Unknown'}],
            'sunrise': 0,
            'sunset': 0
        }

    return transformed_data

class SMHIProvider(WeatherProvider):
    def __init__(self, lat, lon, **kwargs):
        provider_id = kwargs.pop("provider_id_for_cache", "smhi") # Default if somehow missing
        super().__init__(lat, lon, provider_id_for_cache=provider_id, **kwargs)
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