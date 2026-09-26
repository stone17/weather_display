# weather_data_parser.py
from datetime import datetime, timezone, timedelta
from typing import Union, Dict, Any
import sun_utils

class WeatherData:
    """
    Parses and prepares raw weather data for display.
    """
    def __init__(self, current_raw, hourly_raw, daily_raw, temp_unit_pref,
                 graph_config=None, lat=None, lon=None):
        self.current_raw = current_raw if current_raw is not None else {}
        self.hourly_raw = hourly_raw if hourly_raw is not None else []
        self.daily_raw = daily_raw if daily_raw is not None else []
        self.graph_config = graph_config if graph_config is not None else {}

        # Coordinates for astronomical sun calculations
        raw_lat = lat if lat is not None else self.current_raw.get('lat')
        if raw_lat is None and isinstance(self.current_raw.get('coord'), dict):
            raw_lat = self.current_raw['coord'].get('lat')
        raw_lon = lon if lon is not None else self.current_raw.get('lon')
        if raw_lon is None and isinstance(self.current_raw.get('coord'), dict):
            raw_lon = self.current_raw['coord'].get('lon')

        try:
            self.lat = float(raw_lat) if raw_lat is not None else None
        except (ValueError, TypeError):
            self.lat = None
        try:
            self.lon = float(raw_lon) if raw_lon is not None else None
        except (ValueError, TypeError):
            self.lon = None

        self.tz = self._determine_timezone()

        # Build lookup map for daily sun events if available from raw daily data
        self.daily_sun_events_map = {}
        if self.daily_raw:
            for day_data_point_raw in self.daily_raw:
                if hasattr(day_data_point_raw, 'dt') and day_data_point_raw.dt and \
                   hasattr(day_data_point_raw, 'sunrise') and day_data_point_raw.sunrise and \
                   hasattr(day_data_point_raw, 'sunset') and day_data_point_raw.sunset:
                    day_date_key = datetime.fromtimestamp(day_data_point_raw.dt, tz=timezone.utc).astimezone(self.tz).date()
                    self.daily_sun_events_map[day_date_key] = (day_data_point_raw.sunrise, day_data_point_raw.sunset)

        self.current = self._parse_current_weather()
        self.hourly = self._parse_hourly_forecast()  # Note: Parsing, no conversion yet.
        self.daily = self._parse_daily_forecast()    # Same here.
        self.temperature_unit = temp_unit_pref.upper()
        self._convert_temperatures_if_needed() # Conversion happens after parsing.

    def get_night_intervals(self, start_dt, end_dt):
        """
        Calculates night intervals for the given timeframe.
        Uses astronomical calculation via astral if coordinates are available.
        Otherwise falls back to provider sunrise/sunset or daily sun events.
        """
        if self.lat is not None and self.lon is not None:
            return sun_utils.get_night_intervals(self.lat, self.lon, start_dt, end_dt)
            
        # Fallback using daily sun events map or current sunrise/sunset
        intervals = []
        current_dt = start_dt - timedelta(days=1)
        end_dt_plus = end_dt + timedelta(days=1)
        
        while current_dt <= end_dt_plus:
            current_date = current_dt.date()
            sunset_ts = None
            sunrise_next_ts = None
            
            if current_date in self.daily_sun_events_map:
                _, sunset_ts = self.daily_sun_events_map[current_date]
            elif self.current_raw.get('sunset'):
                # Very rough fallback if we only have current day's sunset
                sunset_ts = self.current_raw.get('sunset') + (current_dt - datetime.now(self.tz)).days * 86400
                
            next_date = current_date + timedelta(days=1)
            if next_date in self.daily_sun_events_map:
                sunrise_next_ts, _ = self.daily_sun_events_map[next_date]
            elif self.current_raw.get('sunrise'):
                sunrise_next_ts = self.current_raw.get('sunrise') + (current_dt + timedelta(days=1) - datetime.now(self.tz)).days * 86400

            if sunset_ts and sunrise_next_ts:
                interval_start = datetime.fromtimestamp(sunset_ts, tz=timezone.utc).astimezone(self.tz)
                interval_end = datetime.fromtimestamp(sunrise_next_ts, tz=timezone.utc).astimezone(self.tz)
                if interval_start < end_dt and interval_end > start_dt:
                    intervals.append((max(interval_start, start_dt), min(interval_end, end_dt)))
            
            current_dt += timedelta(days=1)
            
        return intervals

    def _is_daylight_at(self, dt_val):
        """
        Determines whether the given timestamp (UTC epoch) is in daylight.
        Uses astronomical calculation via astral if coordinates are available.
        Otherwise falls back to provider sunrise/sunset or local daytime hours.
        """
        if dt_val is None:
            return True

        if self.lat is not None and self.lon is not None:
            daylight = sun_utils.is_daylight(dt_val, self.lat, self.lon)
            if daylight is not None:
                return daylight

        dt_obj = datetime.fromtimestamp(dt_val, tz=timezone.utc).astimezone(self.tz)

        # Fallback to daily sun events map
        if dt_obj.date() in self.daily_sun_events_map:
            sr, ss = self.daily_sun_events_map[dt_obj.date()]
            if sr and ss:
                return sr <= dt_val < ss

        # Fallback to provider current sunrise/sunset if available
        sunrise_ts = self.current_raw.get('sunrise')
        sunset_ts = self.current_raw.get('sunset')
        if sunrise_ts and sunset_ts:
            return sunrise_ts <= dt_val < sunset_ts

        # Fallback to local hour (6 AM to 6 PM)
        return 6 <= dt_obj.hour < 18

    def _adjust_icon_day_night(self, icon_code, dt_val):
        """
        Adjusts an OWM icon suffix ('d' or 'n') based on whether dt_val is in daylight.
        """
        if not icon_code or icon_code == 'na':
            return icon_code

        is_day = self._is_daylight_at(dt_val)
        if is_day and icon_code.endswith('n'):
            return icon_code[:-1] + 'd'
        elif not is_day and icon_code.endswith('d'):
            return icon_code[:-1] + 'n'
        return icon_code

    def _determine_timezone(self):
        tz_name = self.current_raw.get('timezone')
        tz_offset = self.current_raw.get('timezone_offset')
        
        if tz_name and tz_name != 'UTC':
            try:
                import zoneinfo
                return zoneinfo.ZoneInfo(tz_name)
            except Exception as e:
                print(f"Warning: Could not load timezone {tz_name} (tzdata missing?). Fallback to local/offset.")
                
        if tz_offset is not None:
            return timezone(timedelta(seconds=tz_offset))
            
        # Fallback to system local timezone
        return datetime.now().astimezone().tzinfo

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
        raw_icon = weather_info.get('icon')
        
        # Adjust current icon for day/night based on sunrise/sunset
        if raw_icon:
            dt_val = self.current_raw.get('dt')
            raw_icon = self._adjust_icon_day_night(raw_icon, dt_val)
                    
        current_parsed['weather_icon'] = raw_icon
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

        hours_to_display = self.graph_config.get('graph_time_range_hours', 24)
        for h_data in self.hourly_raw[:hours_to_display]:
            is_dict = isinstance(h_data, dict)
            dt_val = h_data.get('dt') if is_dict else getattr(h_data, 'dt', None)
            
            if dt_val is None:
                continue
                
            try:
                # Attempt to create a datetime object to catch obviously bad timestamps early
                # (e.g., if dt_val is not a number or is extremely out of range)
                # The year check later is more specific.
                datetime.fromtimestamp(dt_val) 
            except (ValueError, TypeError, OSError):
                # print(f"Warning: Skipping hourly data point with invalid timestamp {dt_val}")
                continue

            dt_obj = datetime.fromtimestamp(dt_val, tz=timezone.utc).astimezone(self.tz)
            
            if dt_obj.year <= 1970: # Filter out placeholder/invalid timestamps
                # print(f"Warning: Skipping hourly data point with year <= 1970: {dt_obj}")
                continue

            current_owm_icon = h_data.get('weather_icon') if is_dict else getattr(h_data, 'weather_icon', None)
            adjusted_owm_icon = self._adjust_icon_day_night(current_owm_icon, dt_val)

            entry = {
                'dt': dt_obj,
                'temp': h_data.get('temp') if is_dict else getattr(h_data, 'temp', None),
                'feels_like': h_data.get('feels_like') if is_dict else getattr(h_data, 'feels_like', None),
                'humidity': h_data.get('humidity') if is_dict else getattr(h_data, 'humidity', None),
                'uvi': h_data.get('uvi') if is_dict else getattr(h_data, 'uvi', None),
                'wind_speed': h_data.get('wind_speed') if is_dict else getattr(h_data, 'wind_speed', None),
                'wind_deg': h_data.get('wind_deg') if is_dict else getattr(h_data, 'wind_deg', None),
                'wind_gust': h_data.get('wind_gust') if is_dict else getattr(h_data, 'wind_gust', None),
                'rain': h_data.get('rain_1h') if is_dict else getattr(h_data, 'rain_1h', None),
                'snow': h_data.get('snow_1h') if is_dict else getattr(h_data, 'snow_1h', None),
                'weather_icon': adjusted_owm_icon,
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
            is_day_dict = isinstance(day_data, dict)
            base_icon = day_data.get('weather_icon') if is_day_dict else getattr(day_data, 'weather_icon', None)
            entry['weather_icon'] = base_icon
            
            icon_day = day_data.get('weather_icon_day') if is_day_dict else getattr(day_data, 'weather_icon_day', None)
            icon_night = day_data.get('weather_icon_night') if is_day_dict else getattr(day_data, 'weather_icon_night', None)
            if not icon_day and base_icon and base_icon != 'na':
                icon_day = (base_icon[:-1] + 'd') if base_icon.endswith('n') else base_icon
            if not icon_night and base_icon and base_icon != 'na':
                icon_night = (base_icon[:-1] + 'n') if base_icon.endswith('d') else base_icon

            entry['weather_icon_day'] = icon_day
            entry['weather_icon_night'] = icon_night
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
