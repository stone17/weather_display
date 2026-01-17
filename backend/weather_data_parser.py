# weather_data_parser.py
from datetime import datetime, timezone
from typing import Union, Dict, Any

class WeatherData:
    """
    Parses and prepares raw weather data for display.
    """
    def __init__(self, current_raw, hourly_raw, daily_raw, temp_unit_pref,
                 graph_config=None): # Removed icon_provider_preference
        self.current_raw = current_raw if current_raw is not None else {}
        self.hourly_raw = hourly_raw if hourly_raw is not None else []
        self.daily_raw = daily_raw if daily_raw is not None else []
        # self.icon_provider_preference = icon_provider_preference.lower() # Removed
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

    # _select_icon_identifier method is removed.
    # Individual data parsers (e.g., GoogleWeatherFetcher, OpenWeatherMapFetcher)
    # are now responsible for populating 'weather_icon' with a standardized OWM icon code.
    # The choice of downloading Google vs. OWM icons will be made in image_generator.py
    # based on the global icon_provider config.

    def _parse_current_weather(self):
        if not self.current_raw:
            return {}
            
        current_parsed = {}
        current_parsed['temp_value'] = self.current_raw.get('temp')
        current_parsed['feels_like_value'] = self.current_raw.get('feels_like')
        current_parsed['humidity'] = self.current_raw.get('humidity')
        current_parsed['wind_speed'] = self.current_raw.get('wind_speed')
        # Format strings later in _format_temperature_strings()
        current_parsed['aqi'] = self.current_raw.get('aqi')
        current_parsed['dominant_pollutant'] = self.current_raw.get('dominant_pollutant')

        weather_info_list = self.current_raw.get('weather', [])
        weather_info = weather_info_list[0] if weather_info_list else {}
        # Expecting OWM icon code directly from the raw data (e.g., weather[0]['icon'] from OWM)
        current_parsed['weather_icon'] = weather_info.get('icon')
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

        aqi_val = self.current.get('aqi')
        dom_pol = self.current.get('dominant_pollutant')
        if aqi_val is not None:
            aqi_str = f" {aqi_val}"
            if dom_pol:
                aqi_str += f" ({dom_pol.upper()})"
            self.current['aqi_display'] = aqi_str
        else:
            self.current['aqi_display'] = " ?"

    def _format_temp(self, temp_value, unit_str, decimals=1):
        """Formats a temperature value with the specified unit and decimals."""
        return f"{temp_value:.{decimals}f}{unit_str}"

    def _parse_hourly_forecast(self):
        """ Parses hourly data for the graph, ensuring valid timestamps. """
        parsed_hourly = []
        if not self.hourly_raw:
            return []

        # Create a quick lookup for daily sunrise/sunset from self.daily_raw
        # self.daily_raw is a list of DailyDataPoint objects
        daily_sun_events_map = {}
        if self.daily_raw:
            for day_data_point_raw in self.daily_raw:
                # Ensure the raw daily data point has 'dt', 'sunrise', and 'sunset' attributes
                if hasattr(day_data_point_raw, 'dt') and day_data_point_raw.dt and \
                   hasattr(day_data_point_raw, 'sunrise') and day_data_point_raw.sunrise and \
                   hasattr(day_data_point_raw, 'sunset') and day_data_point_raw.sunset:
                    
                    day_date_key = datetime.fromtimestamp(day_data_point_raw.dt, tz=timezone.utc).date()
                    daily_sun_events_map[day_date_key] = (day_data_point_raw.sunrise, day_data_point_raw.sunset)

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

            current_owm_icon = h_data.weather_icon
            adjusted_owm_icon = current_owm_icon # Start with the provided icon

            # Adjust icon for day/night if it's a daytime icon and it's actually night
            if current_owm_icon and current_owm_icon.endswith('d'):
                sunrise_ts, sunset_ts = daily_sun_events_map.get(dt_obj.date(), (None, None))

                if sunrise_ts and sunset_ts:
                    # dt_val is already a UTC timestamp
                    if not (sunrise_ts <= dt_val < sunset_ts): # It's nighttime
                        adjusted_owm_icon = current_owm_icon[:-1] + 'n'
                else:
                    # Fallback: simple hour-based day/night if no sun events from daily data
                    if not (6 <= dt_obj.hour < 18): # Crude approximation of night (6 AM to 6 PM UTC as day)
                        adjusted_owm_icon = current_owm_icon[:-1] + 'n'

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
                'weather_icon': adjusted_owm_icon, # Use the adjusted icon
                # 'weather_google_icon_uri' is removed; parsers should provide OWM code in weather_icon
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

            # Expecting OWM icon code directly from day_data.weather_icon
            entry['weather_icon'] = getattr(day_data, 'weather_icon', None)
            entry['original_provider_icon_code'] = None # Initialize

            if not entry['weather_icon'] or entry['weather_icon'] == 'na':
                # If icon mapping failed, try to find the original code that caused it.
                # Priority:
                # 1. day_data.weather_id (often the provider's raw numeric/enum code)
                # 2. day_data.weather_icon (the OWM-style code that might have been 'na' or problematic)
                # 3. Other specific fields like day_data.weather_code (if populated by a provider)

                found_original_code = None
                
                # Check weather_id first (provider's original integer/enum code)
                code_val_id = getattr(day_data, 'weather_id', None)
                if code_val_id is not None and str(code_val_id).strip().lower() not in ['', 'na']:
                    found_original_code = str(code_val_id)
                
                # If not found via weather_id, check weather_icon 
                # (this would be the OWM-style icon string, e.g., "01d" or "na")
                if found_original_code is None: # Check the attribute itself if it was 'na' or None
                    code_val_icon = getattr(day_data, 'weather_icon', None)
                    # We accept 'na' or None here as a reportable "code" if weather_id wasn't available/useful
                    if code_val_icon is not None and str(code_val_icon).strip() != '': 
                        found_original_code = str(code_val_icon)

                # As a further fallback, check a list of other common attribute names
                if found_original_code is None:
                    potential_fallback_attrs = ['weather_code', 'condition_code', 'symbol_code', 'icon_code']
                    for attr_name in potential_fallback_attrs:
                        code_val = getattr(day_data, attr_name, None)
                        if code_val is not None and str(code_val).strip().lower() not in ['', 'na']:
                            found_original_code = str(code_val)
                            break 
                
                if found_original_code:
                    entry['original_provider_icon_code'] = found_original_code
            # Store numerical values directly. Formatting will be done in image_generator.
            entry['temp_max'] = day_data.temp_max
            entry['temp_min'] = day_data.temp_min
            entry['rain'] = day_data.rain
            entry['wind_speed'] = day_data.wind_speed
            entry['uvi'] = day_data.uvi
            entry['aqi_pm25_avg'] = getattr(day_data, 'aqi_pm25_avg', None) # Add this line
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
