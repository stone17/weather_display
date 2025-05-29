# create_weather_info.py
import argparse
import json
import traceback
from IPy import IP
import asyncio
import sys
import os

# Local application imports
import upload
import yaml

# Adjust Python path to correctly handle relative imports when running this script directly
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from weather_provider_base import get_weather_provider
from weather_data_parser import WeatherData
from image_generator import generate_weather_image

# --- Main Execution ---
async def main():
    # Use the globally defined project_root for the default config path
    base_config_path = os.path.join(project_root, "config.yaml")
    local_config_path = os.path.join(project_root, "config.local.yaml") # Path for local/private config

    parser = argparse.ArgumentParser(description="Create and optionally upload a weather display image.")
    parser.add_argument(
        "--config",
        dest="config_path",
        default=base_config_path, # Default to the base config path
        help=f"Path to the base configuration YAML file (default: {base_config_path}). A 'config.local.yaml' in the same directory will also be loaded if present."
    )
    args = parser.parse_args()

    output_image_path = os.path.join(project_root, "weather_forecast_graph.png")

    # --- Load Config ---
    config = load_configuration(args.config_path, local_config_path)
    if not config:
        exit(1) # load_configuration will print errors

    # --- Get Weather Data ---
    raw_weather_data = await fetch_weather_data(config, project_root)
    if not raw_weather_data:
        exit(1) # fetch_weather_data will print errors
    current_raw, hourly_raw, daily_raw = raw_weather_data

    # --- Prepare Weather Data ---
    icon_provider_preference = config.get("icon_provider", "openweathermap").lower()
    print(f"Using icon provider preference: {icon_provider_preference}")
    weather_data_obj = prepare_weather_data(current_raw, hourly_raw, daily_raw, icon_provider_preference)

    # --- Create Image ---
    show_wind_arrows_cfg = config.get("show_wind_direction_arrows", False)
    generated_image = generate_weather_image(
        weather_data_obj,
        output_image_path,
        show_wind_arrows_cfg,
        project_root # Pass project_root for icon caching path
    )
    if generated_image is None:
        print("Failed to create weather image. Exiting.")
        exit(1)

    # --- Process and Upload Image ---
    process_and_upload_image(generated_image, config)


def load_configuration(base_config_path_arg, local_config_path_arg):
    """Loads base and local YAML configurations and merges them."""
    config = {}
    try:
        print(f"Loading configuration from: {base_config_path_arg}")
        with open(base_config_path_arg, "r") as config_file:
            base_cfg = yaml.safe_load(config_file)
            if base_cfg:
                config.update(base_cfg)
    except (FileNotFoundError, yaml.YAMLError) as e: # Catch yaml.YAMLError
        print(f"Error loading YAML configuration file '{base_config_path_arg}': {e}")
        return None

    try:
        if os.path.exists(local_config_path_arg):
            print(f"Loading local configuration from: {local_config_path_arg}")
            with open(local_config_path_arg, "r") as local_config_file:
                local_cfg = yaml.safe_load(local_config_file)
                if local_cfg:
                    config.update(local_cfg)
        else:
            print(f"Local configuration file not found: {local_config_path_arg}. Proceeding with base config.")
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"Error loading local YAML configuration file '{local_config_path_arg}': {e}")
        # Continue with base config if local fails, but log it.

    if not config:
        print("No configuration loaded. Exiting.")
        return None
    return config


async def fetch_weather_data(app_config, proj_root):
    """Fetches raw weather data using the configured provider."""
    provider = get_weather_provider(app_config, proj_root)
    if not provider:
        print("Failed to initialize weather provider. Exiting.")
        return None

    if not await provider.fetch_data():
        if not provider.get_all_data():
            print("Failed to fetch weather data and no valid cache available. Exiting.")
            return None
        else: print("Proceeding with potentially outdated cached data.")

    return provider.get_current_data(), provider.get_hourly_data(), provider.get_daily_data()


def prepare_weather_data(current_raw, hourly_raw, daily_raw, icon_pref):
    """Parses raw weather data into a WeatherData object."""
    return WeatherData(current_raw, hourly_raw, daily_raw, icon_pref)


def process_and_upload_image(image_obj, app_config):
    """Processes the generated image and uploads it if server_ip is configured."""
    server_ip = app_config.get("server_ip")
    ip_valid = False
    if server_ip:
        try: 
            IP(server_ip)
            ip_valid = True
        except ValueError:
            print(f"Warning: Invalid server_ip '{server_ip}' in config.json. Skipping upload.")
        except Exception as e:
            print(f"Warning: Error validating server_ip '{server_ip}': {e}. Skipping upload.")
    else: print("Warning: server_ip not found in configuration. Skipping upload.")

    if ip_valid:
        print("Processing image for upload...")
        try:
            processed_data, width, height = upload.process_image(image_obj)
            if processed_data:
                print(f"Uploading image to {server_ip}...")
                upload_successful = upload.upload_processed_data(processed_data, width, height, server_ip, upload.DEFAULT_UPLOAD_URL)
                if upload_successful: print("Upload complete")
                else: print("Upload failed")
            else: print("Image processing failed.")
        except AttributeError:
            print("Error: Functions 'process_image' or 'upload_processed_data' not found in 'upload' module.")
            print("Ensure upload.py is present and defines these functions.")
        except Exception as e:
            print(f"An error occurred during image processing or upload: {e}")
            traceback.print_exc()
    else: print("Skipping upload.")


if __name__ == "__main__":
    asyncio.run(main())
