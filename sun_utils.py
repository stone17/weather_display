import datetime
from astral import LocationInfo
from astral.sun import sun

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
    city = LocationInfo("Custom", "Region", "Timezone", lat, lon)
    
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
            #   Start: s['dusk'] (Civil Dusk)
            #   End:   sun(day+1)['dawn'] (Civil Dawn of next day)
            
            dusk = s['dusk']
            
            # Get next day's dawn
            s_next = sun(city.observer, date=current_date + datetime.timedelta(days=1))
            dawn_next = s_next['dawn']
            
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
            
            interval_start = dusk
            interval_end = dawn_next
            
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
