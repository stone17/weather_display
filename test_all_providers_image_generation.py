import asyncio
import os
import sys
import copy # For deepcopying config
import traceback

# Adjust Python path to correctly handle relative imports
# Assumes this script is in the project root (e.g., c:\Toolz\weather_display\)
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weather_provider_base import get_weather_provider
from weather_data_parser import WeatherData
from image_generator import generate_weather_image
from create_weather_info import load_configuration # Re-use config loading

# Define the list of provider IDs to test.
# These should match the keys used in your `get_weather_provider` factory
# and how they are identified for caching (provider_id_for_cache).
ALL_PROVIDER_IDS = ["openweathermap", "open-meteo", "meteomatics", "google", "smhi"]

async def test_provider_image_generation(provider_id, base_config, project_root_path):
    """
    Tests the full image generation pipeline for a single weather provider.
    Fetches data, parses it, and generates an image.
    """
    print(f"\n--- Testing Provider: {provider_id} ---")

    # Create a deep copy of the base configuration to modify it for the current provider
    current_provider_config = copy.deepcopy(base_config)
    current_provider_config["weather_provider"] = provider_id # Override the provider

    # --- 1. Initialize and Fetch Weather Data ---
    provider_instance = get_weather_provider(current_provider_config, project_root_path)
    if not provider_instance:
        print(f"Failed to initialize weather provider: {provider_id}")
        return False

    print(f"Fetching data for {provider_id} (Provider: {provider_instance.provider_name})...")
    fetch_success = await provider_instance.fetch_data()

    if not fetch_success and not provider_instance.get_all_data():
        print(f"Failed to fetch weather data for {provider_id} and no valid cache was available.")
        return False
    elif not fetch_success:
        print(f"Warning: Failed to fetch new data for {provider_id}. Proceeding with cached data if available.")

    raw_current = provider_instance.get_current_data()
    raw_hourly = provider_instance.get_hourly_data()
    raw_daily = provider_instance.get_daily_data()

    if not raw_current or not raw_hourly or not raw_daily:
        print(f"Insufficient data (current, hourly, or daily missing) after fetch for {provider_id}.")
        all_data_check = provider_instance.get_all_data()
        if not all_data_check or not all_data_check.get('current') or not all_data_check.get('hourly') or not all_data_check.get('daily'):
             print(f"Provider {provider_id} get_all_data() also confirms missing components.")
        return False

    # --- 2. Prepare/Parse Weather Data ---
    print(f"Preparing/parsing data for {provider_id}...")
    temp_unit = current_provider_config.get("temperature_unit", "C")
    icon_pref = current_provider_config.get("icon_provider", "openweathermap").lower()
    graph_config_for_parser = current_provider_config.get('graph_24h_forecast_config', {})

    try:
        weather_data_obj = WeatherData(
            raw_current, raw_hourly, raw_daily,
            temp_unit,
            icon_pref,
            graph_config=graph_config_for_parser
        )
        if not weather_data_obj.has_sufficient_data():
            print(f"WeatherData object for {provider_id} reports insufficient data after parsing.")
            print(f"  Parsed current: {bool(weather_data_obj.current)}")
            print(f"  Parsed hourly: {bool(weather_data_obj.hourly)}")
            print(f"  Parsed daily: {bool(weather_data_obj.daily)}")
            return False
    except Exception as e:
        print(f"Error preparing/parsing weather data for {provider_id}: {e}")
        traceback.print_exc()
        return False

    # --- 3. Generate Image ---
    # Sanitize provider_id for filename (e.g., "open-meteo" -> "open_meteo")
    safe_provider_id_filename = provider_id.replace('-', '_')
    output_image_filename = f"weather_provider_{safe_provider_id_filename}_forecast.png"
    
    # Ensure the output directory exists
    test_output_dir = os.path.join(project_root_path, "test_outputs")
    os.makedirs(test_output_dir, exist_ok=True)
    output_image_path = os.path.join(test_output_dir, output_image_filename)

    print(f"Generating image for {provider_id} at {output_image_path}...")
    try:
        generated_image = generate_weather_image(
            weather_data_obj,
            output_image_path,
            current_provider_config, # Pass the provider-specific config
            project_root_path
        )
        if generated_image:
            print(f"Successfully generated image for {provider_id}.")
            return True
        else:
            print(f"Failed to generate image for {provider_id} (generate_weather_image returned None).")
            return False
    except Exception as e:
        print(f"Error generating image for {provider_id}: {e}")
        traceback.print_exc()
        return False

async def run_all_provider_tests():
    """
    Main function to run tests for all specified weather providers.
    """
    # project_root is defined globally at the top of the script.
    base_config_path = os.path.join(project_root, "config.yaml")
    local_config_path = os.path.join(project_root, "config.local.yaml")

    # Load base configuration
    base_config = load_configuration(base_config_path, local_config_path)
    if not base_config:
        print("Failed to load base configuration. Exiting test.")
        return

    # Essential check: latitude and longitude must be in config
    if not base_config.get("latitude") or not base_config.get("longitude"):
        print("Error: 'latitude' and 'longitude' must be defined in the configuration.")
        print("Please add them to your config.yaml or config.local.yaml to run tests.")
        return

    test_output_dir = os.path.join(project_root, "test_outputs")
    if not os.path.exists(test_output_dir):
        os.makedirs(test_output_dir)
    print(f"Test output images will be saved in: {test_output_dir}")

    results = {}
    for provider_id in ALL_PROVIDER_IDS:
        # Pre-flight check for API keys/credentials for providers that require them
        should_skip = False
        skip_reason = ""
        if provider_id == "openweathermap" and not base_config.get("openweathermap_api_key"):
            skip_reason = "SKIPPED (openweathermap_api_key not configured)"
            should_skip = True
        elif provider_id == "meteomatics" and not (base_config.get("meteomatics_username") and base_config.get("meteomatics_password")):
            skip_reason = "SKIPPED (Meteomatics credentials not configured)"
            should_skip = True
        elif provider_id == "google" and not base_config.get("google_api_key"):
            skip_reason = "SKIPPED (google_api_key not configured)"
            should_skip = True
        # Add other provider key checks here if necessary

        if should_skip:
            print(f"\n--- Skipping Provider: {provider_id} ({skip_reason.split('(')[1][:-1]}) ---")
            results[provider_id] = skip_reason
            continue
        
        # If not skipped due to missing keys, attempt the test
        success = await test_provider_image_generation(provider_id, base_config, project_root)
        results[provider_id] = "PASSED" if success else "FAILED"

    print("\n\n--- System Test Summary ---")
    all_tests_passed_or_skipped = True
    any_passed = False
    for provider_id, status in results.items():
        print(f"Provider {provider_id}: {status}")
        if status == "FAILED":
            all_tests_passed_or_skipped = False
        if status == "PASSED":
            any_passed = True
    
    if not results:
        print("\nNo providers were configured or available for testing.")
    elif all_tests_passed_or_skipped and any_passed:
        print("\nAll configured and runnable provider tests completed successfully or were appropriately skipped.")
    elif all_tests_passed_or_skipped and not any_passed: # All were skipped
        print("\nAll providers were skipped (e.g., due to missing API keys). No tests were run.")
    else:
        print("\nSome provider tests failed. Please review the logs and output images.")

if __name__ == "__main__":
    asyncio.run(run_all_provider_tests())