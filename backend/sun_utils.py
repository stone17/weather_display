import datetime
from astral import LocationInfo
from astral.sun import sun

def get_sunrise_sunset_times(lat, lon, target_date=None, tzinfo=None):
    """
    Calculates the sunrise and sunset times for a given location and date.
    """
    if target_date is None:
        target_date = datetime.date.today()
        
    city = LocationInfo("Custom", "Region", "UTC", lat, lon)
    try:
        s = sun(city.observer, date=target_date)
        sunrise = s['sunrise']
        sunset = s['sunset']
        if tzinfo:
            sunrise = sunrise.astimezone(tzinfo)
            sunset = sunset.astimezone(tzinfo)
        return sunrise.strftime('%H:%M'), sunset.strftime('%H:%M')
    except Exception:
        return None, None

def get_night_intervals(lat, lon, start_dt, end_dt, mode="civil_twilight"):
    """
    Calculates night intervals (between dusk and dawn) for the given timeframe.
    
    Args:
        lat (float): Latitude.
        lon (float): Longitude.
        start_dt (datetime): Start of the graph timeframe (timezone aware).
        end_dt (datetime): End of the graph timeframe (timezone aware).
        mode (str): "civil_twilight" (default) keys off civil dusk/dawn.
    
    Returns:
        list of tuples: [(interval_start, interval_end), ...]
    """
    city = LocationInfo("Custom", "Region", "UTC", lat, lon)
    
    intervals = []
    
    # Iterate through days covering the range
    # Start a bit before to ensure we catch a night starting before start_dt
    current_date = start_dt.date() - datetime.timedelta(days=1)
    end_date = end_dt.date() + datetime.timedelta(days=1)
    
    while current_date <= end_date:
        try:
            s = sun(city.observer, date=current_date)
            # For civil twilight mode: night is between civil dusk and civil dawn of next day?
            # Actually, standard "night" is often between dusk and dawn.
            # Astral returns: dawn, sunrise, noon, sunset, dusk.
            # Civil Twilight: Dawn to Sunrise, Sunset to Dusk.
            # "Night" (darkness): Dusk to Dawn (next day).
            
            # The user asked for: "light grey transparent background for the civil dawn dusk times"
            # likely meaning the dark period.
            
            # We want to highlight the "dark" part.
            # Dark starts at Dusk (civil dusk) and ends at Dawn (civil dawn) of the next day?
            # Or does it start at Dusk of day D and end at Dawn of day D+1?
            # Astral's 'dusk' is civil dusk. 'dawn' is civil dawn.
            
            # Let's define "night interval" for Day D as:
            #   Start: s['sunset']
            #   End:   sun(day+1)['sunrise']
            
            dusk = s['sunset']
            
            # Get next day's sunrise
            s_next = sun(city.observer, date=current_date + datetime.timedelta(days=1))
            dawn_next = s_next['sunrise']
            
            # Clip the interval to the requested start/end range
            # If the night interval assumes timezone info (astral returns tz-aware if observer has it, 
            # or if we are careful).
            # The passed start_dt/end_dt are likely UTC or match what we get from weather provider.
            # Astral usually returns UTC if no timezone specified on observer? 
            # LocationInfo takes timezone but observer might need it.
            # Let's assume input timestamps are consistent with what astral produces (UTC typically if not specified).
            
            # Adjust timezones if necessary.
            # Ideally verify what start_dt/end_dt are. In this app, they seem to be UTC (from weather_data_parser).
            
            # If dusk/dawn are timezone naive or different, we must match.
            # Astral defaults to UTC.
            
            local_tz = start_dt.tzinfo or datetime.timezone.utc
            interval_start = dusk.astimezone(local_tz)
            interval_end = dawn_next.astimezone(local_tz)
            
            print(f"DEBUG sun_utils: Date {current_date} | Sunset (start): {interval_start} | Sunrise next (end): {interval_end}")
            
            # Check overlap with [start_dt, end_dt]
            if interval_start < end_dt and interval_end > start_dt:
                intervals.append((max(interval_start, start_dt), min(interval_end, end_dt)))
                
        except Exception as e:
            # In polar regions or edge cases, sun() might raise errors (e.g. sun never sets)
            # For now print/ignore
            # print(f"Astral calculation error for {current_date}: {e}")
            pass
            
        current_date += datetime.timedelta(days=1)
            
    return intervals
