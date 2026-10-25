# provider_metno.py
import json
from datetime import datetime, timezone
import traceback
import aiohttp

from weather_provider_base import WeatherProvider, parse_iso_time, calculate_feels_like, HourlyDataPoint, DailyDataPoint

# --- MET Norway symbol_code Mappings ---
METNO_SYMBOL_TO_OWM_ICON = {
    'clearsky': '01d',
    'fair': '02d',
    'partlycloudy': '03d',
    'cloudy': '04d',
    'fog': '50d',
    'lightrainshowers': '09d',
    'rainshowers': '09d',
    'heavyrainshowers': '09d',
    'lightrainshowersandthunder': '11d',
    'rainshowersandthunder': '11d',
    'heavyrainshowersandthunder': '11d',
    'lightsleetshowers': '13d',
    'sleetshowers': '13d',
    'heavysleetshowers': '13d',
    'lightssleetshowersandthunder': '11d',
    'lightsleetshowersandthunder': '11d',
    'sleetshowersandthunder': '11d',
    'heavysleetshowersandthunder': '11d',
    'lightsnowshowers': '13d',
    'snowshowers': '13d',
    'heavysnowshowers': '13d',
    'lightssnowshowersandthunder': '11d',
    'lightsnowshowersandthunder': '11d',
    'snowshowersandthunder': '11d',
    'heavysnowshowersandthunder': '11d',
    'lightrain': '10d',
    'rain': '10d',
    'heavyrain': '10d',
    'lightrainandthunder': '11d',
    'rainandthunder': '11d',
    'heavyrainandthunder': '11d',
    'lightsleet': '13d',
    'sleet': '13d',
    'heavysleet': '13d',
    'lightsleetandthunder': '11d',
    'sleetandthunder': '11d',
    'heavysleetandthunder': '11d',
    'lightsnow': '13d',
    'snow': '13d',
    'heavysnow': '13d',
    'lightsnowandthunder': '11d',
    'snowandthunder': '11d',
    'heavysnowandthunder': '11d',
}

METNO_SYMBOL_DESC = {
    'clearsky': 'Clear sky',
    'fair': 'Fair',
    'partlycloudy': 'Partly cloudy',
    'cloudy': 'Cloudy',
    'fog': 'Fog',
    'lightrainshowers': 'Light rain showers',
    'rainshowers': 'Rain showers',
    'heavyrainshowers': 'Heavy rain showers',
    'lightrainshowersandthunder': 'Light rain showers and thunder',
    'rainshowersandthunder': 'Rain showers and thunder',
    'heavyrainshowersandthunder': 'Heavy rain showers and thunder',
    'lightsleetshowers': 'Light sleet showers',
    'sleetshowers': 'Sleet showers',
    'heavysleetshowers': 'Heavy sleet showers',
    'lightssleetshowersandthunder': 'Light sleet showers and thunder',
    'lightsleetshowersandthunder': 'Light sleet showers and thunder',
    'sleetshowersandthunder': 'Sleet showers and thunder',
    'heavysleetshowersandthunder': 'Heavy sleet showers and thunder',
    'lightsnowshowers': 'Light snow showers',
    'snowshowers': 'Snow showers',
    'heavysnowshowers': 'Heavy snow showers',
    'lightssnowshowersandthunder': 'Light snow showers and thunder',
    'lightsnowshowersandthunder': 'Light snow showers and thunder',
    'snowshowersandthunder': 'Snow showers and thunder',
    'heavysnowshowersandthunder': 'Heavy snow showers and thunder',
    'lightrain': 'Light rain',
    'rain': 'Rain',
    'heavyrain': 'Heavy rain',
    'lightrainandthunder': 'Light rain and thunder',
    'rainandthunder': 'Rain and thunder',
    'heavyrainandthunder': 'Heavy rain and thunder',
    'lightsleet': 'Light sleet',
    'sleet': 'Sleet',
    'heavysleet': 'Heavy sleet',
    'lightsleetandthunder': 'Light sleet and thunder',
    'sleetandthunder': 'Sleet and thunder',
    'heavysleetandthunder': 'Heavy sleet and thunder',
    'lightsnow': 'Light snow',
    'snow': 'Snow',
    'heavysnow': 'Heavy snow',
    'lightsnowandthunder': 'Light snow and thunder',
    'snowandthunder': 'Snow and thunder',
    'heavysnowandthunder': 'Heavy snow and thunder',
}

def strip_metno_symbol(symbol_code):
    if not symbol_code:
        return ''
    for suffix in ('_day', '_night', '_polar_twilight'):
        if symbol_code.endswith(suffix):
            return symbol_code[:-len(suffix)]
    return symbol_code

def get_owm_icon_from_metno_symbol(symbol_code, is_night=None):
    if not symbol_code:
        return 'na'
    base_symbol = strip_metno_symbol(symbol_code)
    icon = METNO_SYMBOL_TO_OWM_ICON.get(base_symbol, 'na')
    if icon == 'na':
        return 'na'
    if is_night is None:
        is_night = symbol_code.endswith('_night')
    if is_night:
        icon = icon[:-1] + 'n'
    else:
        icon = icon[:-1] + 'd'
    return icon

def get_metno_description(symbol_code):
    base_symbol = strip_metno_symbol(symbol_code)
    return METNO_SYMBOL_DESC.get(base_symbol, 'Unknown')

def _is_snow_symbol(symbol_code):
    base = strip_metno_symbol(symbol_code)
    return 'snow' in base

def transform_metno_data(metno_json, lat, lon):
    if not metno_json:
        return None
    properties = metno_json.get('properties', {})
    timeseries = properties.get('timeseries', [])
    if not timeseries:
        return None

    transformed_data = {
        'lat': lat,
        'lon': lon,
        'timezone': 'UTC',
        'timezone_offset': 0,
        'current': {},
        'hourly': [],
        'daily': []
    }

    now_utc = datetime.now(timezone.utc)
    start_of_today = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
    start_of_today_ts = int(start_of_today.timestamp())

    daily_buckets = {}

    for entry in timeseries:
        time_str = entry.get('time')
        ts = parse_iso_time(time_str)
        if ts == 0 or ts < start_of_today_ts:
            continue

        data_block = entry.get('data', {})
        instant_details = data_block.get('instant', {}).get('details', {})
        next_1h = data_block.get('next_1_hours', {})
        next_6h = data_block.get('next_6_hours', {})
        next_12h = data_block.get('next_12_hours', {})

        # Determine symbol code (prefer 1h -> 6h -> 12h)
        symbol_code = (
            next_1h.get('summary', {}).get('symbol_code')
            or next_6h.get('summary', {}).get('symbol_code')
            or next_12h.get('summary', {}).get('symbol_code')
            or ''
        )
        description = get_metno_description(symbol_code)
        icon = get_owm_icon_from_metno_symbol(symbol_code)

        temp = instant_details.get('air_temperature')
        pressure = instant_details.get('air_pressure_at_sea_level', 1013.0)
        humidity = instant_details.get('relative_humidity')
        if humidity is not None:
            humidity = int(round(humidity))
        dew_point = instant_details.get('dew_point_temperature')
        clouds = instant_details.get('cloud_area_fraction')
        if clouds is not None:
            clouds = int(round(clouds))
        uvi = instant_details.get('ultraviolet_index_clear_sky', 0.0)
        wind_speed = instant_details.get('wind_speed', 0.0)
        wind_deg = instant_details.get('wind_from_direction')
        if wind_deg is not None:
            wind_deg = int(round(wind_deg))
        wind_gust = instant_details.get('wind_speed_of_gust', wind_speed)

        # Precipitation & probability
        n1_details = next_1h.get('details', {})
        n6_details = next_6h.get('details', {})
        n12_details = next_12h.get('details', {})

        if 'precipitation_amount' in n1_details:
            precip_1h = n1_details.get('precipitation_amount', 0.0)
        elif 'precipitation_amount' in n6_details:
            precip_1h = round(n6_details.get('precipitation_amount', 0.0) / 6.0, 2)
        else:
            precip_1h = 0.0

        pop_raw = (
            n1_details.get('probability_of_precipitation')
            if 'probability_of_precipitation' in n1_details
            else n6_details.get('probability_of_precipitation', n12_details.get('probability_of_precipitation'))
        )
        pop = (pop_raw / 100.0) if pop_raw is not None else None

        is_snow = _is_snow_symbol(symbol_code) or (temp is not None and temp < 0.0)
        rain_1h = 0.0 if is_snow else precip_1h
        snow_1h = precip_1h if is_snow else 0.0

        feels_like = calculate_feels_like(temp, wind_speed, humidity)

        hourly_point = HourlyDataPoint(
            dt=ts,
            temp=temp,
            feels_like=feels_like,
            pressure=pressure,
            humidity=humidity,
            dew_point=dew_point,
            uvi=uvi,
            clouds=clouds,
            visibility=10000,
            wind_speed=wind_speed,
            wind_deg=wind_deg,
            wind_gust=wind_gust,
            weather_id=None,
            weather_main=description.split()[0] if description else "Unknown",
            weather_description=description,
            weather_icon=icon,
            pop=pop,
            rain_1h=rain_1h,
            snow_1h=snow_1h
        )
        transformed_data['hourly'].append(hourly_point)

        # Group into daily buckets by UTC date
        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        day_date = dt_utc.date()
        if day_date not in daily_buckets:
            daily_buckets[day_date] = []
        daily_buckets[day_date].append({
            'dt_utc': dt_utc,
            'hourly': hourly_point,
            'symbol_code': symbol_code,
            'next_1h': next_1h,
            'next_6h': next_6h,
            'next_12h': next_12h
        })

    # --- Daily Processing ---
    for day_date in sorted(daily_buckets.keys()):
        items = daily_buckets[day_date]
        temps = [it['hourly'].temp for it in items if it['hourly'].temp is not None]
        # Also include period min/max temperatures from next_6_hours if present
        for it in items:
            n6_det = it['next_6h'].get('details', {})
            if n6_det.get('air_temperature_max') is not None:
                temps.append(n6_det['air_temperature_max'])
            if n6_det.get('air_temperature_min') is not None:
                temps.append(n6_det['air_temperature_min'])

        temp_max = max(temps) if temps else 0.0
        temp_min = min(temps) if temps else 0.0
        temp_day = (temp_max + temp_min) / 2.0

        # Pick representative daytime entry (closest to 12:00 UTC) and nighttime entry (closest to 00:00 / 23:00 UTC)
        day_entry = min(items, key=lambda x: abs(x['dt_utc'].hour - 12))
        night_candidates = [x for x in items if x['dt_utc'].hour in (0, 1, 2, 3, 21, 22, 23)]
        night_entry = night_candidates[0] if night_candidates else items[-1]

        day_symbol = day_entry['symbol_code'] or next((x['symbol_code'] for x in items if x['symbol_code']), '')
        night_symbol = night_entry['symbol_code'] or day_symbol

        daily_icon_day = get_owm_icon_from_metno_symbol(day_symbol, is_night=False)
        daily_icon_night = get_owm_icon_from_metno_symbol(night_symbol, is_night=True)
        description = get_metno_description(day_symbol)

        # Calculate total daily precipitation:
        # If we have 1-hour steps, sum rain_1h + snow_1h; for 6-hour steps, use next_6h precipitation_amount at 00, 06, 12, 18
        has_1h_steps = any('precipitation_amount' in it['next_1h'].get('details', {}) for it in items)
        if has_1h_steps:
            # Sum 1h precip where available, or fallback to 6h blocks at 6h boundaries
            total_rain = 0.0
            total_snow = 0.0
            for it in items:
                if 'precipitation_amount' in it['next_1h'].get('details', {}):
                    total_rain += it['hourly'].rain_1h or 0.0
                    total_snow += it['hourly'].snow_1h or 0.0
                elif it['dt_utc'].hour in (0, 6, 12, 18) and 'precipitation_amount' in it['next_6h'].get('details', {}):
                    p6 = it['next_6h']['details'].get('precipitation_amount', 0.0)
                    if _is_snow_symbol(it['symbol_code']):
                        total_snow += p6
                    else:
                        total_rain += p6
        else:
            six_hour_items = [it for it in items if it['dt_utc'].hour in (0, 6, 12, 18) and 'precipitation_amount' in it['next_6h'].get('details', {})]
            if not six_hour_items:
                six_hour_items = [it for it in items if 'precipitation_amount' in it['next_6h'].get('details', {})][:4]
            total_rain = 0.0
            total_snow = 0.0
            for it in six_hour_items:
                p6 = it['next_6h']['details'].get('precipitation_amount', 0.0)
                if _is_snow_symbol(it['symbol_code']):
                    total_snow += p6
                else:
                    total_rain += p6

        wind_speeds = [it['hourly'].wind_speed for it in items if it['hourly'].wind_speed is not None]
        wind_gusts = [it['hourly'].wind_gust for it in items if it['hourly'].wind_gust is not None]
        uvis = [it['hourly'].uvi for it in items if it['hourly'].uvi is not None]
        pops = [it['hourly'].pop for it in items if it['hourly'].pop is not None]
        clouds_list = [it['hourly'].clouds for it in items if it['hourly'].clouds is not None]

        normalized_dt = datetime(day_date.year, day_date.month, day_date.day, 0, 0, 0, tzinfo=timezone.utc)
        rep_h = day_entry['hourly']
        rep_night_h = night_entry['hourly']

        daily_point = DailyDataPoint(
            dt=int(normalized_dt.timestamp()),
            summary=description,
            temp_day=temp_day,
            temp_min=temp_min,
            temp_max=temp_max,
            temp_night=temp_min,
            temp_eve=temp_min,
            temp_morn=temp_min,
            feels_like_day=rep_h.feels_like if rep_h.feels_like is not None else calculate_feels_like(temp_day, rep_h.wind_speed, rep_h.humidity),
            feels_like_night=rep_night_h.feels_like if rep_night_h.feels_like is not None else calculate_feels_like(temp_min, rep_night_h.wind_speed, rep_night_h.humidity),
            pressure=rep_h.pressure,
            humidity=rep_h.humidity,
            dew_point=rep_h.dew_point,
            wind_speed=max(wind_speeds) if wind_speeds else 0.0,
            wind_deg=rep_h.wind_deg,
            wind_gust=max(wind_gusts) if wind_gusts else 0.0,
            weather_id=None,
            weather_main=description.split()[0] if description else "Unknown",
            weather_description=description,
            weather_icon=daily_icon_day,
            weather_icon_day=daily_icon_day,
            weather_icon_night=daily_icon_night,
            clouds=int(round(sum(clouds_list) / len(clouds_list))) if clouds_list else 50,
            pop=max(pops) if pops else None,
            precipitation=round(total_rain + total_snow, 2),
            rain=round(total_rain, 2),
            snow=round(total_snow, 2),
            uvi=max(uvis) if uvis else 0.0
        )
        transformed_data['daily'].append(daily_point)

    # --- Current Weather ---
    if transformed_data['hourly']:
        now_ts = int(now_utc.timestamp())
        cur = min(transformed_data['hourly'], key=lambda h: abs(h.dt - now_ts))
        transformed_data['current'] = {
            'dt': cur.dt,
            'temp': cur.temp,
            'feels_like': cur.feels_like,
            'pressure': cur.pressure,
            'humidity': cur.humidity,
            'dew_point': cur.dew_point,
            'uvi': cur.uvi,
            'clouds': cur.clouds,
            'visibility': cur.visibility,
            'wind_speed': cur.wind_speed,
            'wind_deg': cur.wind_deg,
            'wind_gust': cur.wind_gust,
            'weather': [{
                'id': cur.weather_id,
                'main': cur.weather_main,
                'description': cur.weather_description,
                'icon': cur.weather_icon
            }],
            'rain': {'1h': cur.rain_1h or 0.0},
            'snow': {'1h': cur.snow_1h or 0.0}
        }

    transformed_data['hourly'] = transformed_data['hourly'][:48]
    transformed_data['daily'] = transformed_data['daily'][:8]
    return transformed_data


class MetNoProvider(WeatherProvider):
    def __init__(self, lat, lon, **kwargs):
        provider_id = kwargs.pop("provider_id_for_cache", "metno")
        super().__init__(lat, lon, provider_id_for_cache=provider_id, **kwargs)
        self.provider_name = "MET Norway"

    async def _fetch_from_api(self):
        print(f"Fetching data from {self.provider_name}...")
        # MET Norway ToS requires max 4 decimals for lat/lon and a custom User-Agent
        lat_rounded = round(float(self.lat), 4)
        lon_rounded = round(float(self.lon), 4)
        url = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
        params = {
            "lat": str(lat_rounded),
            "lon": str(lon_rounded)
        }
        headers = {
            "User-Agent": "WeatherDisplay/1.0 (https://github.com/weather_display)"
        }
        response = None
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(url, params=params, timeout=30) as response:
                    print(f"MET Norway Response Status Code: {response.status}")
                    response.raise_for_status()
                    raw_data = await response.json()
                    print(f"{self.provider_name} raw data fetched successfully.")
                    return transform_metno_data(raw_data, self.lat, self.lon)
            except aiohttp.ClientError as e:
                print(f"Error fetching {self.provider_name} data: {e}")
                if response is not None:
                    try:
                        print(f"Response Body: {await response.text()}")
                    except Exception:
                        pass
                return None
            except json.JSONDecodeError as e:
                print(f"Error decoding {self.provider_name} JSON response: {e}")
                return None
            except Exception as e:
                print(f"An unexpected error occurred during {self.provider_name} fetch/transform: {e}")
                traceback.print_exc()
                return None
