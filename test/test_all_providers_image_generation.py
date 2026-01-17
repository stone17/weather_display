import asyncio
import os
import sys
import copy
import traceback

# --- PATH SETUP ---
# 1. Identify the directory of this script (e.g., /weather_project/test)
TEST_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Identify the Project Root (e.g., /weather_project)
PROJECT_ROOT = os.path.dirname(TEST_DIR)

# 3. Identify the Backend Directory (e.g., /weather_project/backend)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

# 4. Identify the Config Directory (e.g., /weather_project/config)
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")

# 5. Add Backend to Python Path so we can import modules
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# --- IMPORTS FROM BACKEND ---
from weather_provider_base import get_weather_provider
from weather_data_parser import WeatherData
from image_generator import generate_weather_image
from create_weather_info import load_configuration

# Define the list of provider IDs to test.
ALL_PROVIDER_IDS = ["openweathermap", "open-meteo", "meteomatics", "google", "smhi", "aqicn"]

async def test_provider_image_generation(provider_id, base_config):
    """
    Tests the full image generation pipeline for a single weather provider.
    """
    print(f"\n--- Testing Provider: {provider_id} ---")

    # Create a deep copy of the base configuration to modify it for the current provider
    current_provider_config = copy.deepcopy(base_config)
    current_provider_config["weather_provider"] = provider_id

    # --- 1. Initialize and Fetch Weather Data ---
    # We pass BACKEND_DIR so the provider can find assets (like images) if needed,
    # and to maintain consistency with how the main app runs.
    provider_instance = get_weather_provider(current_provider_config, BACKEND_DIR)
    
    if not provider_instance:
        print(f"Failed to initialize weather provider: {provider_id}")
        return False

    print(f"Fetching data for {provider_id} (Provider: {provider_instance.provider_name})...")
    fetch_success = await provider_instance.fetch_data()

    if not fetch_success and not provider_instance.get_all_data():
        print(f"Failed to fetch weather data for {provider_id} and no valid cache was available.")
        return False
    elif not fetch_success:
        print(f"Warning: Failed to fetch new data for {provider_id}. Proceeding with cached data.")

    raw_current = provider_instance.get_current_data()
    raw_hourly = provider_instance.get_hourly_data()
    raw_daily = provider_instance.get_daily_data()

    # --- 2. Prepare/Parse Weather Data ---
    print(f"Preparing/parsing data for {provider_id}...")
    temp_unit = current_provider_config.get("temperature_unit", "C")
    graph_config_for_parser = current_provider_config.get('graph_24h_forecast_config', {})

    try:
        weather_data_obj = WeatherData(
            raw_current, raw_hourly, raw_daily, temp_unit,
            graph_config=graph_config_for_parser
        )

        # Log unmapped icons for debugging
        if weather_data_obj.daily:
            unmapped_codes_details = []
            for idx, day_entry in enumerate(weather_data_obj.daily):
                if day_entry.get('icon_identifier') is None:
                    original_code = day_entry.get('original_provider_icon_code')
                    if original_code is not None:
                        day_name = day_entry.get('day_name', f"Day {idx+1}")
                        unmapped_codes_details.append(
                            f"    - {day_name}: Code '{original_code}' failed to map."
                        )
            
            if unmapped_codes_details:
                print(f"  INFO: Unmapped icon codes for {provider_id}:")
                for detail in unmapped_codes_details:
                    print(detail)

        if not weather_data_obj.has_sufficient_data():
            print(f"WeatherData object for {provider_id} reports insufficient data.")
            return False

    except Exception as e:
        print(f"Error parsing weather data for {provider_id}: {e}")
        traceback.print_exc()
        return False

    # --- 3. Generate Image ---
    safe_id = provider_id.replace('-', '_')
    output_image_filename = f"weather_provider_{safe_id}_forecast.png"
    
    # Save output to /test/test_outputs/
    test_output_dir = os.path.join(TEST_DIR, "test_outputs")
    os.makedirs(test_output_dir, exist_ok=True)
    output_image_path = os.path.join(test_output_dir, output_image_filename)

    print(f"Generating image at {output_image_path}...")
    try:
        # We pass BACKEND_DIR so generate_weather_image finds the 'images' folder correctly
        generated_image = generate_weather_image(
            weather_data_obj,
            output_image_path,
            current_provider_config,
            BACKEND_DIR
        )
        if generated_image:
            print(f"Successfully generated image for {provider_id}.")
            return True
        else:
            print(f"Failed to generate image for {provider_id}.")
            return False
    except Exception as e:
        print(f"Error generating image for {provider_id}: {e}")
        traceback.print_exc()
        return False

async def run_all_provider_tests():
    """
    Main function to run tests for all specified weather providers.
    """
    # Load config from the new CONFIG_DIR location
    base_config_path = os.path.join(CONFIG_DIR, "config.yaml")
    local_config_path = os.path.join(CONFIG_DIR, "config.local.yaml")

    print(f"Loading configuration from: {base_config_path}")
    base_config = load_configuration(base_config_path, local_config_path)
    
    if not base_config:
        print("Failed to load configuration. Exiting.")
        return

    if not base_config.get("latitude") or not base_config.get("longitude"):
        print("Error: 'latitude' and 'longitude' must be defined in config.")
        return

    results = {}
    for provider_id in ALL_PROVIDER_IDS:
        # Check for missing API keys to skip tests gracefully
        should_skip = False
        if provider_id == "openweathermap" and not base_config.get("openweathermap_api_key"):
            should_skip = True
        elif provider_id == "meteomatics" and not (base_config.get("meteomatics_username") and base_config.get("meteomatics_password")):
            should_skip = True
        elif provider_id == "google" and not base_config.get("google_api_key"):
            should_skip = True
        elif provider_id == "aqicn" and not base_config.get("aqicn_api_token"):
            should_skip = True

        if should_skip:
            print(f"\n--- Skipping {provider_id} (Credentials missing) ---")
            results[provider_id] = "SKIPPED"
            continue
        
        success = await test_provider_image_generation(provider_id, base_config)
        results[provider_id] = "PASSED" if success else "FAILED"

    print("\n\n--- Test Summary ---")
    for pid, status in results.items():
        print(f"{pid}: {status}")

if __name__ == "__main__":
    asyncio.run(run_all_provider_tests())