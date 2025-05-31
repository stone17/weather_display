# weather_data_parser.py
from datetime import datetime, timezone
from typing import Union, Dict, Any

class WeatherData:
    """
    Parses and prepares raw weather data for display.
    """
    def __init__(self, current_raw, hourly_raw, daily_raw, temp_unit_pref,
                 icon_provider_preference, graph_config=None):
        self.current_raw = current_raw if current_raw is not None else {}
        self.hourly_raw = hourly_raw if hourly_raw is not None else []
        self.daily_raw = daily_raw if daily_raw is not None else []
        self.icon_provider_preference = icon_provider_preference.lower()
        self.graph_config = graph_config if graph_config is not None else {}

        self.current = self._parse_current_weather()
        self.hourly = self._parse_hourly_forecast()  # Note: Parsing, no conversion yet.
        self.daily = self._parse_daily_forecast()    # Same here.
        self.temperature_unit = temp_unit_pref.upper()
        self._convert_temperatures_if_needed() # Conversion happens after parsing.

    def _convert_temperatures_if_needed(self):
        if self.temperature_unit == "F":
            self.current['temp_value'] = self._celsius_to_fahrenheit(self.current.get('temp_value',0))
            self.current['feels_like_value'] = self._celsius_to_fahrenheit(self.current.get('feels_like_value',0))
            self.hourly = self._convert_hourly_temps(self.hourly)
            self.daily = self._convert_daily_temps(self.daily)
        self._prepare_current_weather_display_strings()


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
            
        current_parsed = {}
        current_parsed['temp_value'] = self.current_raw.get('temp')
        current_parsed['feels_like_value'] = self.current_raw.get('feels_like')
        current_parsed['humidity'] = self.current_raw.get('humidity')
        current_parsed['wind_speed'] = self.current_raw.get('wind_speed')
        # Format strings later in _format_temperature_strings()

        weather_info_list = self.current_raw.get('weather', [])
        weather_info = weather_info_list[0] if weather_info_list else {}
        current_parsed['icon_identifier'] = self._select_icon_identifier(weather_info)
        return current_parsed

    def _prepare_current_weather_display_strings(self):
        """
        Formats display strings for self.current weather data using the correct unit.
        Original numerical values (e.g., temp_value) remain untouched.
        Hourly and Daily data are NOT formatted here; they retain numerical values.
        """
        unit_symbol = "°" + self.temperature_unit

        temp_val = self.current.get('temp_value')
        self.current['temp_display'] = self._format_temp(temp_val, unit_symbol) if temp_val is not None else f"?{unit_symbol}"

        feels_like_val = self.current.get('feels_like_value')
        self.current['feels_like_display'] = self._format_temp(feels_like_val, unit_symbol) if feels_like_val is not None else f"?{unit_symbol}"

        humidity_val = self.current.get('humidity')
        self.current['humidity_display'] = f"{humidity_val}%" if humidity_val is not None else "?%"

        wind_speed_val = self.current.get('wind_speed')
        # Assuming wind speed unit is m/s from provider and doesn't change with C/F config.
        # If wind speed units can also change, this would need more logic.
        self.current['wind_speed_display'] = f"{wind_speed_val:.1f} m/s" if wind_speed_val is not None else "? m/s"


    def _format_temp(self, temp_value, unit_str, decimals=1):
        """Formats a temperature value with the specified unit and decimals."""
        return f"{temp_value:.{decimals}f}{unit_str}"

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
                'snow': h_data.snow_1h,
                'weather_icon': h_data.weather_icon, # Added for graph symbols
                'weather_google_icon_uri': h_data.weather_google_icon_uri # Added for graph symbols
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

            # Store numerical values directly. Formatting will be done in image_generator.
            entry['temp_max'] = day_data.temp_max
            entry['temp_min'] = day_data.temp_min
            entry['rain'] = day_data.rain
            entry['wind_speed'] = day_data.wind_speed
            entry['uvi'] = day_data.uvi
            # Other non-numerical fields from DailyDataPoint can be added if needed for display
            entry['summary'] = day_data.summary
            entry['pop'] = day_data.pop # Probability of precipitation

            parsed_daily.append(entry)
        return parsed_daily

    def _celsius_to_fahrenheit(self, celsius):
        """Converts Celsius to Fahrenheit."""
        if celsius is None:
            return None
        return (celsius * 9/5) + 32

    def _convert_hourly_temps(self, hourly_data):
        for entry in hourly_data:
            if 'temp' in entry and isinstance(entry['temp'], (int, float)):
                entry['temp'] = self._celsius_to_fahrenheit(entry['temp'])
            # Feels-like could be added here if needed.
        return hourly_data

    def _convert_daily_temps(self, daily_data):
        for entry in daily_data:
            for temp_key in ['temp_max', 'temp_min']:
                if temp_key in entry and isinstance(entry[temp_key], (int, float)):
                    entry[temp_key] = self._celsius_to_fahrenheit(entry[temp_key])
        return daily_data
