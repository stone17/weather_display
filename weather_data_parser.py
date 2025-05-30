# weather_data_parser.py
from datetime import datetime, timezone
from typing import Union, Dict, Any

class WeatherData:
    """
    Parses and prepares raw weather data for display.
    """
    def __init__(self, current_raw, hourly_raw, daily_raw, icon_provider_preference, graph_config=None):
        self.current_raw = current_raw if current_raw is not None else {}
        self.hourly_raw = hourly_raw if hourly_raw is not None else []
        self.daily_raw = daily_raw if daily_raw is not None else []
        self.icon_provider_preference = icon_provider_preference.lower()
        self.graph_config = graph_config if graph_config is not None else {}

        self.current = self._parse_current_weather()
        self.hourly = self._parse_hourly_forecast()
        self.daily = self._parse_daily_forecast()

    def has_sufficient_data(self):
        """Checks if essential data components are present."""
        return bool(self.current and self.hourly and self.daily)

    def _select_icon_identifier(self, weather_source: Union[Dict[str, Any], object]):
        """
        Selects the icon identifier (URL or code) based on provider preference.
        Accepts either a dictionary (for current weather's 'weather' item)
        or a HourlyDataPoint/DailyDataPoint object.
        Always attempts to return a 'day' version for OWM icons.
        """
        if not weather_source:
            return None

        if isinstance(weather_source, dict):
            google_icon_uri = weather_source.get('google_icon_uri')
            owm_icon_code = weather_source.get('icon')
        else: # Assumes HourlyDataPoint or DailyDataPoint object
            google_icon_uri = getattr(weather_source, 'weather_google_icon_uri', None)
            owm_icon_code = getattr(weather_source, 'weather_icon', None)

        if self.icon_provider_preference == "google" and google_icon_uri:
            return google_icon_uri
        elif owm_icon_code and owm_icon_code != 'na':
            if 'n' in owm_icon_code:
                return owm_icon_code.replace("n", "d")
            return owm_icon_code
        return None

    def _parse_current_weather(self):
        if not self.current_raw:
            return {}
            
        parsed_current = {}
        temp_val = self.current_raw.get('temp')
        parsed_current['temp'] = f"{temp_val:.1f}°C" if temp_val is not None else "?°C"

        weather_info_list = self.current_raw.get('weather', [])
        weather_info = weather_info_list[0] if weather_info_list else {}
        parsed_current['icon_identifier'] = self._select_icon_identifier(weather_info)

        feels_like_val = self.current_raw.get('feels_like')
        parsed_current['feels_like'] = f"{feels_like_val:.1f}°C" if feels_like_val is not None else "?°C"

        humidity_val = self.current_raw.get('humidity')
        parsed_current['humidity'] = f"{humidity_val}%" if humidity_val is not None else "?%"

        wind_speed_val = self.current_raw.get('wind_speed')
        parsed_current['wind_speed'] = f"{wind_speed_val:.1f} m/s" if wind_speed_val is not None else "? m/s"
        return parsed_current

    def _parse_hourly_forecast(self):
        """ Parses hourly data for the graph, ensuring valid timestamps. """
        parsed_hourly = []
        if not self.hourly_raw:
            return []

        hours_to_display = self.graph_config.get('graph_time_range_hours', 24)
        for h_data in self.hourly_raw[:hours_to_display]:
            # h_data is an HourlyDataPoint object, access attributes directly
            dt_val = h_data.dt
            try:
                # Attempt to create a datetime object to catch obviously bad timestamps early
                # (e.g., if dt_val is not a number or is extremely out of range)
                # The year check later is more specific.
                datetime.fromtimestamp(dt_val) 
            except (ValueError, TypeError, OSError):
                # print(f"Warning: Skipping hourly data point with invalid timestamp {dt_val}")
                continue

            dt_obj = datetime.fromtimestamp(dt_val, tz=timezone.utc)
            
            if dt_obj.year <= 1970: # Filter out placeholder/invalid timestamps
                # print(f"Warning: Skipping hourly data point with year <= 1970: {dt_obj}")
                continue

            entry = {
                'dt': dt_obj,
                'temp': h_data.temp,
                'feels_like': h_data.feels_like,
                'humidity': h_data.humidity,
                'uvi': h_data.uvi,
                'wind_speed': h_data.wind_speed,
                'wind_deg': h_data.wind_deg,
                'wind_gust': h_data.wind_gust,
                'rain': h_data.rain_1h,
                'snow': h_data.snow_1h
            }
            parsed_hourly.append(entry)
        return parsed_hourly


    def _parse_daily_forecast(self):
        parsed_daily = []

        if not self.daily_raw:
            return []

        for day_data in self.daily_raw[:5]: # Show 5 days
            entry = {}
            dt_val = day_data.dt # day_data is DailyDataPoint
            entry['day_name'] = datetime.fromtimestamp(dt_val).strftime('%a') if dt_val else '???'
            
            entry['icon_identifier'] = self._select_icon_identifier(day_data) # Pass the object itself

            temp_max_val = day_data.temp_max
            entry['temp_max'] = f"{temp_max_val:.0f}°" if temp_max_val is not None else "?°"
            temp_min_val = day_data.temp_min
            entry['temp_min'] = f"{temp_min_val:.0f}°" if temp_min_val is not None else "?°"
            
            rain_val = day_data.rain
            entry['rain'] = f"{rain_val:.1f} mm" if rain_val is not None else "? mm"
            
            wind_val = day_data.wind_speed
            if wind_val is not None and isinstance(wind_val, (int, float)):
                entry['wind_speed'] = f"{wind_val:.1f} m/s"
            else:
                entry['wind_speed'] = f"{wind_val} m/s" if wind_val is not None else "? m/s"

            uvi_val = day_data.uvi
            if uvi_val is not None and isinstance(uvi_val, (int, float)):
                entry['uvi'] = f"UV {uvi_val:.1f}"
            else:
                entry['uvi'] = f"UV {uvi_val}" if uvi_val is not None else "UV ?"
            parsed_daily.append(entry)
        return parsed_daily
