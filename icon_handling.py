# icon_handling.py
import os
import requests

GOOGLE_ICON_BASE_URL = "https://maps.gstatic.com/weather/v1/"
OWM_ICON_BASE_URL = "http://openweathermap.org/img/w/"
DEFAULT_GOOGLE_ICON_NAME = "cloudy" # Fallback Google icon
DEFAULT_OWM_ICON_CODE = "03d" # Fallback OWM icon (scattered clouds day)

# Refined map based on the provided list of Google SVG files
OWM_TO_GOOGLE_ICON_MAP = {
    "01d": "sunny",
    "01n": "clear",
    "02d": "mostly_sunny",
    "02n": "mostly_clear",
    "03d": "mostly_cloudy",
    "03n": "partly_clear", # OWM scattered clouds
    "04d": "cloudy",
    "04n": "mostly_cloudy_night", # OWM broken/overcast
    "09d": "showers",
    "09n": "showers", # OWM shower rain / drizzle
    "10d": "showers",
    "10n": "showers", # OWM rain (can also be "heavy" from Google list for heavy rain)
    "11d": "strong_tstorms",
    "11n": "strong_tstorms", # OWM thunderstorm
    "13d": "snow_showers",
    "13n": "snow_showers", # OWM snow (Google has flurries, scattered_snow, heavy_snow)
    "50d": DEFAULT_GOOGLE_ICON_NAME,
    "50n": DEFAULT_GOOGLE_ICON_NAME, # OWM fog/mist - no direct match in list
}

def download_and_cache_icon(owm_icon_code, provider, project_root_path, icon_cache_dir="icon_cache"):
    """
    Downloads and caches weather icons.
    'provider' can be "openweathermap" or "google".
    """
    if not owm_icon_code or owm_icon_code == 'na':
        print(f"Skipping download for invalid OWM icon code: {owm_icon_code}")
        # Optionally, return a path to a default placeholder icon here
        return None

    full_icon_cache_dir = os.path.join(project_root_path, icon_cache_dir)
    os.makedirs(full_icon_cache_dir, exist_ok=True)

    icon_url = None
    icon_filename = None

    if provider == "openweathermap":
        icon_url = f"{OWM_ICON_BASE_URL}{owm_icon_code}.png"
        icon_filename = f"owm_{owm_icon_code}.png"
    elif provider == "google":
        google_icon_name = OWM_TO_GOOGLE_ICON_MAP.get(owm_icon_code, DEFAULT_GOOGLE_ICON_NAME)
        icon_url = f"{GOOGLE_ICON_BASE_URL}{google_icon_name}.png" # Changed to .png
        # Ensure the URL ends with .png
        if not icon_url.lower().endswith('.png'):
            icon_url = icon_url.rsplit('.', 1)[0] + '.png'
        icon_filename = f"google_{google_icon_name}.png" # Changed to .png
    else:
        print(f"Unsupported icon provider: {provider}. Defaulting to OWM icon.")
        # Fallback to OWM if provider is unknown
        icon_url = f"{OWM_ICON_BASE_URL}{owm_icon_code}.png"
        icon_filename = f"owm_{owm_icon_code}.png"

    if not icon_url or not icon_filename: # Should not happen if logic above is correct
        print(f"Could not determine icon URL or filename for {owm_icon_code} with provider {provider}")
        return None

    icon_path = os.path.join(full_icon_cache_dir, icon_filename)

    if os.path.exists(icon_path):
        return icon_path

    print(f"Downloading icon from: {icon_url}")
    try:
        response = requests.get(icon_url, timeout=15)
        response.raise_for_status()
        with open(icon_path, 'wb') as f:
            f.write(response.content)
        print(f"Icon downloaded and cached: {icon_path}")
        return icon_path
    except requests.exceptions.RequestException as e:
        print(f"Error downloading icon {owm_icon_code} (provider: {provider}) from {icon_url}: {e}")
    except OSError as e:
        print(f"Error saving icon {owm_icon_code} (provider: {provider}) to {icon_path}: {e}")
    except Exception as e:
        print(f"Unexpected error for icon {owm_icon_code} (provider: {provider}): {e}")
    return None