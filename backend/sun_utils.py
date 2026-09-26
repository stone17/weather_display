import datetime
from astral import LocationInfo
from astral.sun import sun, elevation

def is_daylight(dt, lat, lon):
    """
    Determines if it is daytime at the specified datetime/timestamp and coordinates.
    Returns True if sun is above the horizon, False if nighttime.
    """
    if lat is None or lon is None:
        return None

    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return None

    if isinstance(dt, (int, float)):
        dt_utc = datetime.datetime.fromtimestamp(dt, tz=datetime.timezone.utc)
    elif isinstance(dt, datetime.datetime):
        if dt.tzinfo is None:
            dt_utc = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt_utc = dt.astimezone(datetime.timezone.utc)
    else:
        return None

    city = LocationInfo("Custom", "Region", "UTC", lat, lon)
    try:
        target_date = dt_utc.date()
        s = sun(city.observer, date=target_date)
        if s['sunrise'] <= dt_utc < s['sunset']:
            return True
        # Check adjacent days for edge cases near UTC midnight
        s_prev = sun(city.observer, date=target_date - datetime.timedelta(days=1))
        if s_prev['sunrise'] <= dt_utc < s_prev['sunset']:
            return True
        s_next = sun(city.observer, date=target_date + datetime.timedelta(days=1))
        if s_next['sunrise'] <= dt_utc < s_next['sunset']:
            return True
        return False
    except Exception:
        try:
            return elevation(city.observer, dt_utc) > -0.833
        except Exception:
            return None

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
    Calculates night intervals for the given timeframe.
    Streamlined to use the exact same sunrise/sunset definitions as is_daylight.
    """
    city = LocationInfo("Custom", "Region", "UTC", lat, lon)
    intervals = []
    
    current_date = start_dt.date() - datetime.timedelta(days=1)
    end_date = end_dt.date() + datetime.timedelta(days=1)
    
    while current_date <= end_date:
        try:
            s = sun(city.observer, date=current_date)
            # Night starts at sunset
            interval_start = s['sunset']
            
            # Night ends at next day's sunrise
            s_next = sun(city.observer, date=current_date + datetime.timedelta(days=1))
            interval_end = s_next['sunrise']
            
            local_tz = start_dt.tzinfo or datetime.timezone.utc
            interval_start = interval_start.astimezone(local_tz)
            interval_end = interval_end.astimezone(local_tz)
            
            if interval_start < end_dt and interval_end > start_dt:
                intervals.append((max(interval_start, start_dt), min(interval_end, end_dt)))
        except Exception:
            pass
        current_date += datetime.timedelta(days=1)
    return intervals
