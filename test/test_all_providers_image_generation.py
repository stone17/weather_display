import asyncio
import os
import sys
import copy
import traceback
import aiohttp

# --- PATH SETUP ---
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TEST_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# --- IMPORTS FROM BACKEND ---
from weather_provider_base import get_weather_provider
from weather_data_parser import WeatherData
from image_generator import generate_weather_image
from create_weather_info import load_configuration

ALL_PROVIDER_IDS = ["openweathermap", "open-meteo", "meteomatics", "google", "smhi", "aqicn"]

class SMHIDirectProbe:
    """Probes the SMHI API directly to check for version-specific 404 errors."""
    def __init__(self, lat, lon):
        self.lat = round(float(lat), 6)
        self.lon = round(float(lon), 6)

    async def probe_endpoint(self, category="pmp3g", version=3):
        url = f"https://opendata-download-metfcst.smhi.se/api/category/{category}/version/{version}/geotype/point/lon/{self.lon}/lat/{self.lat}/data.json"
        print(f"  --> Probing SMHI {category} V{version} directly: {url}")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        print(f"  [SUCCESS] SMHI {category} V{version} is reachable.")
                        return True
                    else:
                        print(f"  [FAILURE] SMHI {category} V{version} returned status: {response.status}")
                        return False
            except Exception as e:
                print(f"  [ERROR] Could not reach SMHI {category} V{version}: {e}")
                return False

async def test_provider_image_generation(provider_id, base_config):
    print(f"\n--- Testing Provider: {provider_id} ---")

    if provider_id == "smhi":
        probe = SMHIDirectProbe(base_config['latitude'], base_config['longitude'])
        # Test legacy (pmp3g) and the new 2026 API (snow1g)
        await probe.probe_endpoint(category="pmp3g", version=2)
        await probe.probe_endpoint(category="snow1g", version=1)

    current_provider_config = copy.deepcopy(base_config)
    current_provider_config["weather_provider"] = provider_id

    provider_instance = get_weather_provider(current_provider_config, BACKEND_DIR)
    
    if not provider_instance:
        print(f"Failed to initialize weather provider: {provider_id}")
        return False

    print(f"Fetching data for {provider_id}...")
    fetch_success = await provider_instance.fetch_data()

    if not fetch_success and not provider_instance.get_all_data():
        print(f"Failed to fetch weather data and no valid cache available.")
        return False

    weather_data_obj = WeatherData(
        provider_instance.get_current_data(),
        provider_instance.get_hourly_data(),
        provider_instance.get_daily_data(),
        current_provider_config.get("temperature_unit", "C"),
        graph_config=current_provider_config.get('graph_24h_forecast_config', {})
    )

    if not weather_data_obj.has_sufficient_data():
        print(f"WeatherData object for {provider_id} reports insufficient data.")
        return False

    # --- FIX: Ensure icon_cache_dir is explicitly passed ---
    safe_id = provider_id.replace('-', '_')
    test_output_dir = os.path.join(TEST_DIR, "test_outputs")
    icon_cache_dir = os.path.join(test_output_dir, "icon_cache")
    
    os.makedirs(test_output_dir, exist_ok=True)
    os.makedirs(icon_cache_dir, exist_ok=True)
    
    output_image_path = os.path.join(test_output_dir, f"weather_provider_{safe_id}_forecast.png")

    try:
        generated_image = generate_weather_image(
            weather_data_obj,
            output_image_path,
            current_provider_config,
            BACKEND_DIR,
            icon_cache_path=icon_cache_dir
        )
        if generated_image:
            print(f"Successfully generated image for {provider_id}.")
            return True
    except Exception:
        traceback.print_exc()
    return False

async def run_all_provider_tests():
    base_config_path = os.path.join(CONFIG_DIR, "config.yaml")
    local_config_path = os.path.join(CONFIG_DIR, "config.local.yaml")

    print(f"Loading configuration from: {base_config_path}")
    base_config = load_configuration(base_config_path, local_config_path)
    
    if not base_config:
        print("Failed to load configuration. Exiting.")
        return

    # --- CONFIG SANITIZATION ---
    if 'cache_duration_minutes' in base_config:
        try:
            base_config['cache_duration_minutes'] = int(base_config['cache_duration_minutes'])
        except (ValueError, TypeError):
            base_config['cache_duration_minutes'] = 60

    for coord in ['lat', 'lon', 'latitude', 'longitude']:
        if coord in base_config and base_config[coord] is not None:
            try:
                base_config[coord] = float(base_config[coord])
            except (ValueError, TypeError):
                pass

    results = {}
    for provider_id in ALL_PROVIDER_IDS:
        if provider_id == "openweathermap" and not base_config.get("openweathermap_api_key"):
            status = "SKIPPED"
        elif provider_id == "meteomatics" and not (base_config.get("meteomatics_username") and base_config.get("meteomatics_password")):
            status = "SKIPPED"
        elif provider_id == "google" and not base_config.get("google_api_key"):
            status = "SKIPPED"
        elif provider_id == "aqicn" and not base_config.get("aqicn_api_token"):
            status = "SKIPPED"
        else:
            success = await test_provider_image_generation(provider_id, base_config)
            status = "PASSED" if success else "FAILED"
        
        results[provider_id] = status

    print("\n--- Test Summary ---")
    for pid, status in results.items():
        print(f"{pid}: {status}")

if __name__ == "__main__":
    asyncio.run(run_all_provider_tests())