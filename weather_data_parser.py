# weather_data_parser.py
from datetime import datetime, timezone

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

    def _select_icon_identifier(self, weather_info_dict):
        """
        Selects the icon identifier (URL or code) based on provider preference.
        Always attempts to return a 'day' version for OWM icons.
        """
        if not weather_info_dict:
            return None
            
        google_icon_uri = weather_info_dict.get('google_icon_uri')
        owm_icon_code = weather_info_dict.get('icon')

        if self.icon_provider_preference == "google" and google_icon_uri:
            return google_icon_uri
        elif owm_icon_code and owm_icon_code != 'na':
            # Prefer day version for display if OWM is used
            if 'n' in owm_icon_code:
                return owm_icon_code.replace("n", "d")
            return owm_icon_code
        return None

    def _parse_current_weather(self):
        if not self.current_raw:
            return {}
            
        data = {}
        data['temp'] = f"{self.current_raw.get('temp', '?'):.1f}°C".replace('?.1', '?')
        
        weather_info_list = self.current_raw.get('weather', [])
        weather_info = weather_info_list[0] if weather_info_list else {}
        data['icon_identifier'] = self._select_icon_identifier(weather_info)
        
        data['feels_like'] = f"{self.current_raw.get('feels_like', '?'):.1f}°C".replace('?.1', '?')
        data['humidity'] = f"{self.current_raw.get('humidity', '?')}%"
        data['wind_speed'] = f"{self.current_raw.get('wind_speed', '?'):.1f} m/s".replace('?.1', '?')
        return data

    def _parse_hourly_forecast(self):
        """ Parses hourly data for the graph, ensuring valid timestamps. """
        parsed_hourly = []
        if not self.hourly_raw:
            return []

        hours_to_display = self.graph_config.get('graph_time_range_hours', 24)
        for h_data in self.hourly_raw[:hours_to_display]:
            dt_val = h_data.get('dt', 0)
            # Ensure dt_val is a valid timestamp before conversion
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

            # Ensure rain and snow are numeric or None
            rain_val = h_data.get('rain')
            if isinstance(rain_val, dict):
                rain_val = rain_val.get('1h') # Common key for 1-hour accumulation

            snow_val = h_data.get('snow')
            if isinstance(snow_val, dict):
                snow_val = snow_val.get('1h') # Common key for 1-hour accumulation

            entry = {
                'dt': dt_obj,
                'temp': h_data.get('temp'), # Will be None if missing
                'feels_like': h_data.get('feels_like'),
                'humidity': h_data.get('humidity'),
                'uvi': h_data.get('uvi'),
                'wind_speed': h_data.get('wind_speed'),
                'wind_deg': h_data.get('wind_deg'), # Still needed for arrows
                # Provider adapters should aim to place 'rain' and 'snow' as direct numeric values.
                # This parser now also attempts to extract '1h' if they are dicts.
                'rain': rain_val,
                'snow': snow_val
            }
            parsed_hourly.append(entry)
        return parsed_hourly

    def _parse_daily_forecast(self):
        parsed_daily = []

        if not self.daily_raw:
            return []

        for day_data in self.daily_raw[:5]: # Show 5 days
            entry = {}
            dt_val = day_data.get('dt', 0)
            entry['day_name'] = datetime.fromtimestamp(dt_val).strftime('%a') if dt_val else '???'
            
            weather_info_list = day_data.get('weather', [])
            weather_info = weather_info_list[0] if weather_info_list else {}
            entry['icon_identifier'] = self._select_icon_identifier(weather_info)

            temp_dict = day_data.get('temp', {})
            entry['temp_max'] = f"{temp_dict.get('max', '?'):.0f}°".replace('?.0', '?')
            entry['temp_min'] = f"{temp_dict.get('min', '?'):.0f}°".replace('?.0', '?')
            
            rain_val = day_data.get('rain', 0.0)
            entry['rain'] = f"{rain_val:.1f} mm"
            
            wind_val = day_data.get('wind_speed', '?')
            entry['wind_speed'] = f"{wind_val:.1f} m/s" if isinstance(wind_val, (int, float)) else f"{wind_val} m/s"

            uvi_val = day_data.get('uvi', '?')
            entry['uvi'] = f"UV {uvi_val:.1f}" if isinstance(uvi_val, (int, float)) else f"UV {uvi_val}"
            
            parsed_daily.append(entry)
        return parsed_daily
