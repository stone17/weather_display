import json
import os
from datetime import datetime, timedelta, timezone
from abc import ABC, abstractmethod
import traceback
import aiohttp
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict, is_dataclass

# --- Constants ---
CACHE_DURATION_MINUTES = 60
DEFAULT_CACHE_FILENAME_SUFFIX = "_weather_data_cache.json"

# --- Common Helper Functions ---
def parse_iso_time(iso_time_str):
    """Parses ISO time string (UTC assumed if no offset) to Unix timestamp."""
    if not iso_time_str:
        return 0
    try:
        if '+' not in iso_time_str and 'Z' not in iso_time_str:
            iso_time_str += '+00:00'
        elif 'Z' in iso_time_str:
            iso_time_str = iso_time_str.replace('Z', '+00:00')

        if '.' in iso_time_str:
            time_part, tz_part = iso_time_str.split('+')
            # Truncate fractional seconds to 6 digits to match python isoformat
            base_time, fractional = time_part.split('.')
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

# --- Standardized Data Structures ---
@dataclass
class HourlyDataPoint:
    dt: int = 0
    temp: Optional[float] = None
    feels_like: Optional[float] = None
    pressure: Optional[float] = None
    humidity: Optional[int] = None
    dew_point: Optional[float] = None
    uvi: Optional[float] = None
    clouds: Optional[int] = None
    visibility: Optional[int] = None
    wind_speed: Optional[float] = None
    wind_deg: Optional[int] = None
    wind_gust: Optional[float] = None
    weather_id: Optional[int] = None
    weather_main: Optional[str] = None
    weather_description: Optional[str] = None
    weather_icon: Optional[str] = None
    pop: Optional[float] = None
    rain_1h: Optional[float] = None
    snow_1h: Optional[float] = None

@dataclass
class DailyDataPoint:
    dt: int = 0 
    sunrise: Optional[int] = None
    sunset: Optional[int] = None
    moonrise: Optional[int] = None
    moonset: Optional[int] = None
    moon_phase: Optional[float] = None
    summary: Optional[str] = None
    temp_day: Optional[float] = None
    temp_min: Optional[float] = None
    temp_max: Optional[float] = None
    temp_night: Optional[float] = None
    temp_eve: Optional[float] = None
    temp_morn: Optional[float] = None
    feels_like_day: Optional[float] = None
    feels_like_night: Optional[float] = None
    feels_like_eve: Optional[float] = None
    feels_like_morn: Optional[float] = None
    pressure: Optional[float] = None
    humidity: Optional[int] = None
    dew_point: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_deg: Optional[int] = None
    wind_gust: Optional[float] = None
    weather_id: Optional[int] = None
    weather_main: Optional[str] = None
    weather_description: Optional[str] = None
    weather_icon: Optional[str] = None
    clouds: Optional[int] = None
    pop: Optional[float] = None
    precipitation: Optional[float] = None
    rain: Optional[float] = None
    snow: Optional[float] = None
    uvi: Optional[float] = None
    aqi_pm25_avg: Optional[int] = None

# --- Base Class ---
class WeatherProvider(ABC):
    """Abstract base class for weather data providers."""
    def __init__(self, lat, lon, provider_id_for_cache, **kwargs):
        self.lat = lat
        self.lon = lon

        project_root_path = kwargs.get("project_root_path")
        if not project_root_path:
            project_root_path = os.getcwd()

        cache_duration_cfg = kwargs.get("cache_duration_minutes", CACHE_DURATION_MINUTES)
        self.cache_duration = timedelta(minutes=cache_duration_cfg)

        cache_filename = f"{provider_id_for_cache.lower().replace(' ', '_').replace('-', '_')}{DEFAULT_CACHE_FILENAME_SUFFIX}"
        self.cache_file = os.path.join(project_root_path, "cache", cache_filename)
        
        # Ensure cache directory exists
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)

        self._data = None
        self.supplemental_providers_info = []
        self.provider_name = "UnknownProvider"

    def _is_cache_valid(self):
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
        try:
            print(f"Attempting to load {self.provider_name} data from cache: {self.cache_file}")
            with open(self.cache_file, 'r') as f:
                cached_content = json.load(f)
            if cached_content.get('cached_provider_name') != self.provider_name:
                return False
            
            weather_data = cached_content.get('weather_data')
            if isinstance(weather_data, dict) and 'current' in weather_data and 'hourly' in weather_data and 'daily' in weather_data:
                # Reconstruct Data Objects
                loaded_hourly_dicts = weather_data.get('hourly', [])
                weather_data['hourly'] = [HourlyDataPoint(**h_dict) for h_dict in loaded_hourly_dicts if isinstance(h_dict, dict)]
                
                loaded_daily_dicts = weather_data.get('daily', [])
                weather_data['daily'] = [DailyDataPoint(**d_dict) for d_dict in loaded_daily_dicts if isinstance(d_dict, dict)]

                self._data = weather_data
                print(f"Using cached weather data for {self.provider_name}.")
                return True
            else:
                return False
        except Exception as e:
            print(f"Error loading cache file {self.cache_file}: {e}")
            return False

    def _save_to_cache(self, data_to_save):
        if data_to_save:
            import copy
            data_to_serialize = copy.deepcopy(data_to_save)

            if isinstance(data_to_serialize.get('hourly'), list):
                data_to_serialize['hourly'] = [asdict(h) if is_dataclass(h) else h for h in data_to_serialize['hourly']]
            
            if isinstance(data_to_serialize.get('daily'), list):
                data_to_serialize['daily'] = [asdict(d) if is_dataclass(d) else d for d in data_to_serialize['daily']]
            
            cache_content = {
                'cached_provider_name': self.provider_name,
                'weather_data': data_to_serialize
            }
            try:
                with open(self.cache_file, 'w') as f:
                    json.dump(cache_content, f, indent=4)
                print(f"Serialized weather data for {self.provider_name} saved to cache.")
            except Exception as e:
                print(f"Error saving data to cache: {e}")

    # --- RESTORED ROBUST MERGING LOGIC ---
    def _merge_supplemental_data(self, supplemental_data_all, parameters_to_merge):
        if not self._data or not supplemental_data_all:
            print(f"Skipping merge for {self.provider_name}: primary or supplemental data missing.")
            return
            
        print(f"Merging parameters {parameters_to_merge} from supplemental provider into {self.provider_name} data.")
        
        # 1. Merge Current
        sup_current = supplemental_data_all.get('current')
        if sup_current and self._data.get('current'):
            for param in parameters_to_merge:
                if param in sup_current:
                    self._data['current'][param] = sup_current[param]
                    print(f"  Merged 'current.{param}'")

        # 2. Merge Hourly (Match by Timestamp)
        sup_hourly_list = supplemental_data_all.get('hourly', [])
        primary_hourly_list = self._data.get('hourly', [])

        if sup_hourly_list and primary_hourly_list:
            sup_hourly_lookup = {h.dt: h for h in sup_hourly_list if hasattr(h, 'dt')}
            
            for primary_hour_dp in primary_hourly_list:
                if not hasattr(primary_hour_dp, 'dt'): continue 

                dt_match = primary_hour_dp.dt
                if dt_match in sup_hourly_lookup:
                    sup_hour_dp = sup_hourly_lookup[dt_match]
                    for param in parameters_to_merge:
                        if hasattr(sup_hour_dp, param):
                            value_to_merge = getattr(sup_hour_dp, param)
                            setattr(primary_hour_dp, param, value_to_merge)

        # 3. Merge Daily (Match by Date String YYYY-MM-DD)
        # This is robust against slightly different "midnight" timestamps
        sup_daily_list = supplemental_data_all.get('daily', [])
        primary_daily_list = self._data.get('daily', [])
        
        if sup_daily_list and primary_daily_list:
            sup_daily_date_lookup = {}
            for sup_day_dp in sup_daily_list:
                if not hasattr(sup_day_dp, 'dt'): continue
                sup_dt_val = sup_day_dp.dt
                if sup_dt_val is not None: 
                    sup_date_str = datetime.fromtimestamp(sup_dt_val, tz=timezone.utc).strftime('%Y-%m-%d')
                    sup_daily_date_lookup[sup_date_str] = sup_day_dp
            
            for primary_day_dp in primary_daily_list:
                if not hasattr(primary_day_dp, 'dt'): continue
                primary_dt_val = primary_day_dp.dt
                primary_date_str = datetime.fromtimestamp(primary_dt_val, tz=timezone.utc).strftime('%Y-%m-%d') if primary_dt_val else None
                
                if primary_date_str and primary_date_str in sup_daily_date_lookup:
                    sup_day_dp_match = sup_daily_date_lookup[primary_date_str]
                    for param in parameters_to_merge:
                        if hasattr(sup_day_dp_match, param):
                            value_to_merge = getattr(sup_day_dp_match, param)
                            setattr(primary_day_dp, param, value_to_merge)
        print("Data merging complete.")

    @abstractmethod
    async def _fetch_from_api(self):
        pass

    async def fetch_data(self):
        if self._is_cache_valid() and self._load_from_cache():
            return True
        print(f"Fetching new weather data from API for {self.provider_name}...")
        
        try:
            fetched_api_data = await self._fetch_from_api()
            if fetched_api_data:
                self._data = fetched_api_data
                for sup_info in self.supplemental_providers_info:
                    sup_instance = sup_info['instance']
                    sup_params = sup_info['parameters']
                    print(f"Fetching supplemental data from {sup_instance.provider_name} for parameters: {sup_params}")
                    
                    # Fetch logic for supplemental
                    if await sup_instance.fetch_data():
                        supplemental_full_data = sup_instance.get_all_data()
                        if supplemental_full_data:
                            self._merge_supplemental_data(supplemental_full_data, sup_params)
                    else:
                        print(f"Failed to fetch data from supplemental provider: {sup_instance.provider_name}")
                
                self._save_to_cache(self._data)
                return True
            else:
                print(f"Failed to fetch new data from API for {self.provider_name}.")
                if os.path.exists(self.cache_file):
                    print(f"Attempting to use potentially outdated cache as fallback for {self.provider_name}.")
                    return self._load_from_cache()
                return False
        except Exception as e:
            print(f"Fetch Error: {e}")
            traceback.print_exc()
            return False

    def get_current_data(self):
        return self._data.get('current') if self._data else None
    def get_hourly_data(self):
        return self._data.get('hourly') if self._data else None
    def get_daily_data(self):
        return self._data.get('daily') if self._data else None
    def get_all_data(self):
        return self._data

# --- Factory Function ---
def get_weather_provider(config, project_root_path_from_caller):
    """
    Factory function to create and return the appropriate WeatherProvider instance.
    """
    from providers.provider_owm import OpenWeatherMapProvider
    from providers.provider_meteomatics import MeteomaticsProvider
    from providers.provider_openmeteo import OpenMeteoProvider
    from providers.provider_google import GoogleWeatherProvider
    from providers.provider_smhi import SMHIProvider
    from providers.provider_aqicn import AQICNProvider

    provider_config_name = config.get("weather_provider", "openweathermap").lower()
    
    # --- FIX: Support 'lat'/'lon' from UI and 'latitude'/'longitude' from yaml ---
    lat = config.get("lat") if config.get("lat") is not None else config.get("latitude")
    lon = config.get("lon") if config.get("lon") is not None else config.get("longitude")
    
    cache_duration_cfg = config.get("cache_duration_minutes", CACHE_DURATION_MINUTES)
    supplemental_providers_config = config.get("supplemental_providers", [])

    if lat is None or lon is None:
        raise ValueError("Latitude and Longitude must be defined in config.json")

    print(f"Attempting to initialize provider: {provider_config_name} with cache duration: {cache_duration_cfg} minutes")

    def _instantiate_provider(p_config_name_arg, is_supplemental=False):
        # Common arguments
        common_provider_args = {
            "lat": float(lat),
            "lon": float(lon),
            "project_root_path": project_root_path_from_caller,
            "cache_duration_minutes": cache_duration_cfg,
            "provider_id_for_cache": p_config_name_arg
        }

        if p_config_name_arg == "meteomatics":
            return MeteomaticsProvider(config.get("meteomatics_username"), config.get("meteomatics_password"), **common_provider_args)
        elif p_config_name_arg == "openweathermap":
            return OpenWeatherMapProvider(config.get("openweathermap_api_key"), **common_provider_args)
        elif p_config_name_arg == "open-meteo":
            return OpenMeteoProvider(**common_provider_args)
        elif p_config_name_arg == "google":
            return GoogleWeatherProvider(config.get("google_api_key"), **common_provider_args)
        elif p_config_name_arg == "smhi":
            return SMHIProvider(**common_provider_args)
        elif p_config_name_arg == "aqicn":
            return AQICNProvider(config.get("aqicn_api_token"), **common_provider_args)
        else:
            print(f"Error: Unknown provider name '{p_config_name_arg}' encountered.")
            return None

    primary_provider = None
    try:
        primary_provider = _instantiate_provider(provider_config_name)
    except Exception as e:
        print(f"Error initializing primary provider '{provider_config_name}': {e}")
        traceback.print_exc()
        return None

    if not primary_provider:
        print(f"Failed to initialize primary provider '{provider_config_name}'.")
        return None

    for sup_config in supplemental_providers_config:
        sup_provider_name = sup_config.get("provider_name")
        sup_parameters = sup_config.get("parameters", [])
        if not sup_provider_name or not sup_parameters:
            continue
        if sup_provider_name.lower() == primary_provider.provider_name.lower():
            continue
            
        print(f"Initializing supplemental provider: {sup_provider_name} for parameters: {sup_parameters}")
        try:
            supplemental_instance = _instantiate_provider(sup_provider_name.lower(), is_supplemental=True)
            if supplemental_instance:
                primary_provider.supplemental_providers_info.append({
                    'instance': supplemental_instance,
                    'parameters': sup_parameters
                })
        except Exception as e:
            print(f"Error initializing supplemental provider '{sup_provider_name}': {e}")
            traceback.print_exc()

    return primary_provider