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
    if not iso_time_str: return 0
    try:
        if '+' not in iso_time_str and 'Z' not in iso_time_str: iso_time_str += '+00:00'
        elif 'Z' in iso_time_str: iso_time_str = iso_time_str.replace('Z', '+00:00')
        if '.' in iso_time_str:
            base_time, fractional = iso_time_str.split('.')[:2]
            iso_time_str = f"{base_time}.{fractional[:6]}+{iso_time_str.split('+')[-1]}"
        return int(datetime.fromisoformat(iso_time_str).timestamp())
    except Exception: return 0

def parse_google_date(date_obj):
    if not date_obj: return 0
    try:
        dt_obj = datetime(date_obj.get('year'), date_obj.get('month'), date_obj.get('day'), 0, 0, 0, tzinfo=timezone.utc)
        return int(dt_obj.timestamp())
    except Exception: return 0

# --- Data Structures ---
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
    
    # Temp
    temp_day: Optional[float] = None
    temp_min: Optional[float] = None
    temp_max: Optional[float] = None
    temp_night: Optional[float] = None
    temp_eve: Optional[float] = None   # Restored for SMHI
    temp_morn: Optional[float] = None  # Restored for SMHI
    
    # Feels Like
    feels_like_day: Optional[float] = None
    feels_like_night: Optional[float] = None
    feels_like_eve: Optional[float] = None  # Restored for SMHI
    feels_like_morn: Optional[float] = None # Restored for SMHI
    
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
    def __init__(self, lat, lon, provider_id_for_cache, **kwargs):
        self.lat = lat
        self.lon = lon
        project_root_path = kwargs.get("project_root_path", os.getcwd())
        cache_duration_cfg = kwargs.get("cache_duration_minutes", CACHE_DURATION_MINUTES)
        self.cache_duration = timedelta(minutes=cache_duration_cfg)
        
        cache_filename = f"{provider_id_for_cache.lower().replace(' ', '_').replace('-', '_')}{DEFAULT_CACHE_FILENAME_SUFFIX}"
        self.cache_file = os.path.join(project_root_path, "cache", cache_filename)
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)

        self._data = None
        self.supplemental_providers_info = []
        self.provider_name = "UnknownProvider"

    def _is_cache_valid(self):
        if not os.path.exists(self.cache_file): return False
        try:
            return (datetime.now() - datetime.fromtimestamp(os.path.getmtime(self.cache_file))) < self.cache_duration
        except OSError: return False

    def _load_from_cache(self):
        try:
            with open(self.cache_file, 'r') as f: cached_content = json.load(f)
            if cached_content.get('cached_provider_name') != self.provider_name: return False
            weather_data = cached_content.get('weather_data')
            if isinstance(weather_data, dict):
                weather_data['hourly'] = [HourlyDataPoint(**h) for h in weather_data.get('hourly', [])]
                weather_data['daily'] = [DailyDataPoint(**d) for d in weather_data.get('daily', [])]
                self._data = weather_data
                print(f"Using cached data for {self.provider_name}.")
                return True
            return False
        except Exception as e:
            print(f"Cache load error {self.provider_name}: {e}")
            return False

    def _save_to_cache(self, data):
        if not data: return
        try:
            import copy
            serializable = copy.deepcopy(data)
            serializable['hourly'] = [asdict(h) if is_dataclass(h) else h for h in serializable.get('hourly', [])]
            serializable['daily'] = [asdict(d) if is_dataclass(d) else d for d in serializable.get('daily', [])]
            with open(self.cache_file, 'w') as f:
                json.dump({'cached_provider_name': self.provider_name, 'weather_data': serializable}, f, indent=4)
        except Exception as e: print(f"Cache save error: {e}")

    def _merge_supplemental_data(self, supplemental_data, parameters):
        if not self._data or not supplemental_data: return
        print(f"Merging {parameters} from supplemental...")
        if 'current' in supplemental_data and 'current' in self._data:
            for p in parameters: 
                if p in supplemental_data['current']: self._data['current'][p] = supplemental_data['current'][p]
        sup_h_map = {h.dt: h for h in supplemental_data.get('hourly', [])}
        for h in self._data.get('hourly', []):
            if h.dt in sup_h_map:
                for p in parameters:
                    if hasattr(sup_h_map[h.dt], p): setattr(h, p, getattr(sup_h_map[h.dt], p))
        sup_d_map = {datetime.fromtimestamp(d.dt, timezone.utc).strftime('%Y-%m-%d'): d for d in supplemental_data.get('daily', [])}
        for d in self._data.get('daily', []):
            d_str = datetime.fromtimestamp(d.dt, timezone.utc).strftime('%Y-%m-%d')
            if d_str in sup_d_map:
                for p in parameters:
                    if hasattr(sup_d_map[d_str], p): setattr(d, p, getattr(sup_d_map[d_str], p))

    @abstractmethod
    async def _fetch_from_api(self): pass

    async def fetch_data(self):
        if self._is_cache_valid() and self._load_from_cache(): return True
        print(f"Fetching API data for {self.provider_name}...")
        try:
            data = await self._fetch_from_api()
            if data:
                self._data = data
                for sup in self.supplemental_providers_info:
                    print(f"Fetching supplemental {sup['instance'].provider_name}...")
                    if await sup['instance'].fetch_data():
                        self._merge_supplemental_data(sup['instance'].get_all_data(), sup['parameters'])
                self._save_to_cache(self._data)
                return True
            else:
                print(f"API fetch failed. Fallback to cache.")
                return self._load_from_cache()
        except Exception as e:
            print(f"Fetch loop error: {e}")
            traceback.print_exc()
            return False

    def get_current_data(self): return self._data.get('current') if self._data else None
    def get_hourly_data(self): return self._data.get('hourly') if self._data else None
    def get_daily_data(self): return self._data.get('daily') if self._data else None
    def get_all_data(self): return self._data

# --- Factory ---
def get_weather_provider(config, project_root_path_from_caller):
    from providers.provider_owm import OpenWeatherMapProvider
    from providers.provider_meteomatics import MeteomaticsProvider
    from providers.provider_openmeteo import OpenMeteoProvider
    from providers.provider_google import GoogleWeatherProvider
    from providers.provider_smhi import SMHIProvider
    from providers.provider_aqicn import AQICNProvider

    p_name = config.get("weather_provider", "openweathermap").lower()
    
    # STRICTLY USE latitude / longitude
    lat = config.get("latitude")
    lon = config.get("longitude")

    print(f"DEBUG FACTORY: lat: {lat}, lon: {lon}")

    if lat is None or lon is None:
        raise ValueError("Latitude and Longitude must be defined in config.")

    common_args = {
        "lat": float(lat), "lon": float(lon),
        "project_root_path": project_root_path_from_caller,
        "cache_duration_minutes": config.get("cache_duration_minutes", 60),
        "provider_id_for_cache": p_name
    }

    try:
        if p_name == "meteomatics": provider = MeteomaticsProvider(config.get("meteomatics_username"), config.get("meteomatics_password"), **common_args)
        elif p_name == "openweathermap": provider = OpenWeatherMapProvider(config.get("openweathermap_api_key"), **common_args)
        elif p_name == "open-meteo": provider = OpenMeteoProvider(**common_args)
        elif p_name == "google": provider = GoogleWeatherProvider(config.get("google_api_key"), **common_args)
        elif p_name == "smhi": provider = SMHIProvider(**common_args)
        elif p_name == "aqicn": provider = AQICNProvider(config.get("aqicn_api_token"), **common_args)
        else: return None
        
        for sup in config.get("supplemental_providers", []):
            s_name = sup.get("provider_name", "").lower()
            if not s_name or s_name == p_name: continue
            
            s_common = common_args.copy(); s_common["provider_id_for_cache"] = s_name
            s_inst = None
            if s_name == "aqicn": s_inst = AQICNProvider(config.get("aqicn_api_token"), **s_common)
            elif s_name == "open-meteo": s_inst = OpenMeteoProvider(**s_common)
            
            if s_inst: provider.supplemental_providers_info.append({'instance': s_inst, 'parameters': sup.get("parameters", [])})
            
        return provider
    except Exception as e:
        print(f"Provider Init Error: {e}")
        traceback.print_exc()
        return None