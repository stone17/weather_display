# create_weather_info.py
import requests
import json
import os
from datetime import datetime, timedelta
import hashlib
import io
import traceback

# Third-party imports
from PIL import Image, ImageDraw, ImageFont
try:
    # Newer Pillow versions use Resampling
    from PIL.Image import Resampling
    LANCZOS_FILTER = Resampling.LANCZOS
except ImportError:
    # Older Pillow versions use direct constants
    LANCZOS_FILTER = Image.LANCZOS
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from IPy import IP

# Local application imports
import upload
import weather_provider


# Global variable for image, used by create_24h_forecast_section
image = None


# --- download_and_cache_icon (Keep as is - using /img/w/) ---
# (Function remains exactly as provided in the base code)
def download_and_cache_icon(icon_identifier, icon_cache_dir="icon_cache"):
    """
    Downloads and caches weather icons.
    Fetches standard 50x50 (/img/w/) for OpenWeatherMap codes (preferred for e-ink).
    Handles full URLs (e.g., from Google).
    Generates filename based on identifier (code or hash of URL).
    """
    os.makedirs(icon_cache_dir, exist_ok=True)

    is_url = isinstance(icon_identifier, str) and icon_identifier.startswith('http')
    icon_url = None
    icon_filename = None

    if is_url:
        # Handle URL identifier (e.g., from Google)
        icon_url = icon_identifier
        if not icon_url.lower().endswith('.png'):
            print(f"Warning: Google icon URI '{icon_identifier}' doesn't end with .png. Appending.")
            icon_url += '.png'

        # Create a filename based on hash of the base URL part before .png
        base_url_for_hash = icon_url.rsplit('.png', 1)[0]
        filename_base = hashlib.md5(base_url_for_hash.encode()).hexdigest()
        icon_filename = f"google_{filename_base}.png"
    elif isinstance(icon_identifier, str) and icon_identifier != 'na':
        # Handle OWM code identifier - Fetch standard 50x50 version
        icon_code = icon_identifier
        icon_url = f"http://openweathermap.org/img/w/{icon_code}.png"
        icon_filename = f"{icon_code}.png"
    else:
        print(f"Skipping download for invalid icon identifier: {icon_identifier}")
        return None

    icon_path = os.path.join(icon_cache_dir, icon_filename)

    # Check cache using the correct filename (e.g., code.png)
    if os.path.exists(icon_path):
        return icon_path

    # Download if not cached
    print(f"Downloading icon from: {icon_url}")
    try:
        response = requests.get(icon_url, timeout=15)
        response.raise_for_status()
        with open(icon_path, 'wb') as f:
            f.write(response.content)
        print(f"Icon downloaded and cached: {icon_path}")
        return icon_path
    except requests.exceptions.RequestException as e:
        print(f"Error downloading icon {icon_identifier}: {e}")
        return None
    except OSError as e:
        print(f"Error saving icon {icon_identifier}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error downloading/saving icon {icon_identifier}: {e}")
        return None


# --- create_24h_forecast_section (Keep as is) ---
# (Function remains exactly as provided in the base code)
def create_24h_forecast_section(draw, hourly_forecast_data, x, y, width, height, font_path, font_size):
    """Creates the 24-hour forecast section (graph) on the image."""
    global image # Need global image to paste onto

    if not hourly_forecast_data:
        print("Warning: No hourly forecast data provided for graph.")
        try:
            fallback_font = ImageFont.truetype(font_path, font_size + 2)
        except IOError:
            fallback_font = ImageFont.load_default()
        draw.text((x + 10, y + height // 2), "Hourly data unavailable", font=fallback_font, fill=(255, 0, 0))
        return

    # Extract data, handling potential missing keys
    times = [datetime.fromtimestamp(h.get('dt', 0)) for h in hourly_forecast_data]
    temps = [h.get('temp', 0.0) for h in hourly_forecast_data]
    winds = [h.get('wind_speed', 0.0) for h in hourly_forecast_data]
    rains = [h.get('rain', {}).get('1h', 0.0) for h in hourly_forecast_data]

    # Filter out potential bad timestamps (dt=0)
    valid_indices = [i for i, t in enumerate(times) if t.year > 1970]
    if not valid_indices:
        print("Warning: No valid timestamps found for forecast graph.")
        return

    times = [times[i] for i in valid_indices]
    temps = [temps[i] for i in valid_indices]
    winds = [winds[i] for i in valid_indices]
    rains = [rains[i] for i in valid_indices]

    if not times: # Check again after filtering
        print("Warning: Insufficient valid data points after filtering for forecast graph.")
        return

    try:
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        print(f"Warning: Could not load font {font_path} for graph. Using default.")
        font = ImageFont.load_default()
        font_size = 10 # Adjust size for default font if needed

    # Calculate peaks and ranges safely
    peak_wind = max(winds) if winds else 0
    peak_rain = max(rains) if rains else 0
    min_temp = min(temps) if temps else 0
    max_temp = max(temps) if temps else 0
    temp_range = max_temp - min_temp if temps else 0

    # Create Matplotlib figure and axes
    fig, ax1 = plt.subplots(figsize=(width / 100, height / 100), dpi=100)

    # --- Plotting ---
    # Rain (secondary y-axis, right, bottom)
    ax3 = ax1.twinx()
    ax3.spines['right'].set_position(('outward', 0))
    ax3.fill_between(times, rains, color='blue', alpha=0.3, label='Rainfall (mm)', linewidth=1)
    ax3.set_yticks([])
    ax3.set_yticklabels([])
    ax3.set_ylim(0, max(0.1, peak_rain * 1.4)) # Ensure some visible height

    # Wind (secondary y-axis, right, middle)
    ax2 = ax1.twinx()
    ax2.plot(times, winds, '--', color='green', alpha=0.7, label='Wind Speed (m/s)', linewidth=1.5)
    ax2.set_yticks([])
    ax2.set_yticklabels([])
    ax2.set_ylim(0, max(1.0, peak_wind * 1.4)) # Ensure some visible height

    # Temperature (primary y-axis, right, top)
    ax1.plot(times, temps, color='red', label='Temperature (°C)', linewidth=2)
    ax1.set_ylabel('Temp. (°C)', color='red', fontsize=max(9, font_size + 2))
    ax1.yaxis.tick_right() # Move ticks and label to the right
    ax1.set_ylim(min_temp - max(1, (temp_range * 0.1)), max_temp + max(1, (temp_range * 0.1)))
    ax1.tick_params(axis='y', labelcolor='red', which='both', left=False, right=True, labelleft=False, labelright=True, labelsize=max(8, font_size))
    ax1.tick_params(axis='x', which='both', labelsize=max(8, font_size))

    # Text labels for peaks (with background)
    text_bbox = dict(boxstyle='round,pad=0.2', fc='white', alpha=0.7, ec='none')
    ax2.text(0.97, 0.97, f'Wind: {peak_wind:.1f} m/s', transform=ax2.transAxes,
             color='green', ha='right', va='top', fontsize=max(8, font_size - 1),
             bbox=text_bbox)
    ax3.text(0.97, 0.87, f'Rain: {peak_rain:.1f} mm', transform=ax3.transAxes,
             color='blue', ha='right', va='top', fontsize=max(8, font_size - 1),
             bbox=text_bbox)

    # --- X-Axis Formatting ---
    first_time = times[0]
    try:
        # Start x-axis slightly after the first hour begins
        next_hour = (first_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    except ValueError:
        next_hour = first_time # Fallback

    ax1.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 6))) # Ticks every 6 hours
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M')) # Format as HH:MM
    ax1.set_xlim(left=next_hour, right=times[-1] + timedelta(minutes=30)) # Ensure end time is included
    plt.xticks(rotation=30, ha="right")
    ax1.grid(True, which='major', axis='x', linestyle='-', color='grey', alpha=0.3)
    ax1.grid(True, which='major', axis='y', linestyle=':', color='grey', alpha=0.3)

    fig.tight_layout(pad=0.5) # Adjust padding around the plot

    # --- Save plot to buffer and paste ---
    try:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)
        plt.close(fig) # Close the plot to free memory
        buf.seek(0)
        plot_img = Image.open(buf).convert("RGBA")

        # Paste the plot onto the main image
        image.paste(plot_img, (x, y), mask=plot_img)
    except Exception as e:
        print(f"Error creating or pasting forecast graph: {e}")
        plt.close(fig) # Ensure figure is closed on error


# --- MODIFIED create_weather_image signature and icon logic ---
def create_weather_image(current_data, hourly_data, daily_data, output_path, icon_provider):
    """
    Creates the weather forecast image (600x448, with graph).
    Uses specified icon_provider ('openweathermap' or 'google').
    """
    global image # Uses global image

    if not current_data or not hourly_data or not daily_data:
        print("Error: Missing essential weather data for image creation.")
        # ... (Error handling remains the same) ...
        image = Image.new("RGB", (600, 448), "white")
        draw = ImageDraw.Draw(image)
        try: 
            err_font = ImageFont.truetype("arialbd.ttf"if os.name == 'nt' else "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 20)
        except IOError:
            err_font = ImageFont.load_default()
        draw.text((50, 200), "Error: Weather data unavailable.", font=err_font, fill="red")
        image.save(output_path)
        print(f"Error image saved to {output_path}")
        return None

    image_width = 600
    image_height = 448
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)

    # --- Fonts and Colors (Keep as is) ---
    if os.name == 'nt': 
        font_path="arial.ttf"
        bold_font_path="arialbd.ttf"
    else: 
        font_path="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        bold_font_path="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    try:
        heading_font = ImageFont.truetype(bold_font_path, 18)
        temp_font = ImageFont.truetype(bold_font_path, 36)
        regular_font = ImageFont.truetype(bold_font_path, 18)
        small_font = ImageFont.truetype(bold_font_path, 14)
        graph_font_size = 11
    except IOError as e:
        print(f"Error loading font: {e}. Using default font.")
        heading_font = ImageFont.load_default()
        temp_font = ImageFont.load_default()
        regular_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
        font_path = "arial.ttf" if os.name == 'nt' else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        graph_font_size = 10
    bg_color = (255, 255, 255)
    text_color = (50, 50, 50)
    blue_color = (0, 0, 200)
    green_color = (0, 180, 0)
    orange_color = (255, 140, 0)
    draw.rectangle(((0, 0), (image_width, image_height)), fill=bg_color)

    # --- Current Weather Section ---
    current_weather_width = 150
    current_temp = f"{current_data.get('temp', '?'):.1f}°C".replace('?.1', '?')
    temp_x = 25
    temp_y = 10
    draw.text((temp_x, temp_y), current_temp, font=temp_font, fill=text_color)

    # --- Icon Logic ---
    weather_info = current_data.get('weather', [{}])[0]
    google_icon_uri = weather_info.get('google_icon_uri')
    owm_icon_code = weather_info.get('icon')

    icon_identifier_to_download = None
    # --- Select identifier based on config ---
    if icon_provider == "google" and google_icon_uri:
        icon_identifier_to_download = google_icon_uri
        print(f"DEBUG: Using configured Google icon URI: {google_icon_uri}")
    elif owm_icon_code and owm_icon_code != 'na':
        # Default to OWM if provider is not 'google' or google URI is missing
        # Use day version for current icon display
        if 'n' in owm_icon_code:
            icon_identifier_to_download = owm_icon_code.replace("n", "d")
        else:
            icon_identifier_to_download = owm_icon_code
        print(f"DEBUG: Using OWM icon code (provider: {icon_provider}): {icon_identifier_to_download}")
    else:
        print("Warning: No suitable icon identifier found.")
    # --- End Icon Selection ---

    if icon_identifier_to_download:
        icon_path = download_and_cache_icon(icon_identifier_to_download)
        if icon_path:
            try:
                # --- Conditional Resize and Positioning from Base Code ---
                is_google_icon = isinstance(icon_identifier_to_download, str) and icon_identifier_to_download.startswith('http')
                if is_google_icon:
                    target_icon_size = (90, 90)
                    paste_pos = (temp_x - 0, temp_y + 45)
                else:
                    target_icon_size = (100, 100)
                    paste_pos = (temp_x - 15, temp_y + 35)

                icon_image = Image.open(icon_path).convert("RGBA")
                icon_image = icon_image.resize(target_icon_size, resample=LANCZOS_FILTER)

                image.paste(icon_image, paste_pos, mask=icon_image)
                # --- End Conditional Resize ---
            except Exception as e:
                print(f"Error displaying current icon: {e}")
                # Draw placeholder matching target size/pos (use 100x100 as default)
                target_icon_size = (100, 100)
                paste_pos = (temp_x - 15, temp_y + 35) # Use OWM position for placeholder
                draw.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")
        else: # Placeholder if download failed
             target_icon_size = (100, 100)
             paste_pos = (temp_x - 15, temp_y + 35) # Use OWM position for placeholder
             draw.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")

    # --- Current Weather Details ---
    details_y = 155
    details_x = 20
    line_height = 25
    details = [
        f"Feel  : {current_data.get('feels_like', '?'):.1f}°C".replace('?.1', '?'),
        f"Hum.: {current_data.get('humidity', '?')}%",
        f"Wind: {current_data.get('wind_speed', '?'):.1f} m/s".replace('?.1', '?'),
    ]
    for i, text in enumerate(details):
        draw.text((details_x, details_y + i * line_height), text, font=regular_font, fill=text_color)

    # --- Hourly Forecast Graph Section ---
    hourly_forecast_x = current_weather_width
    hourly_forecast_y = 0
    hourly_forecast_height = 250
    hourly_forecast_width = image_width - current_weather_width - 15
    create_24h_forecast_section(
        draw, hourly_data[:24], hourly_forecast_x, hourly_forecast_y,
        hourly_forecast_width, hourly_forecast_height, font_path, graph_font_size
    )

    # --- Daily Forecast Section ---
    daily_start_x = 25
    daily_start_y = 270
    daily_width = (image_width - 10) // 5 # Width per day column

    for i, day_data in enumerate(daily_data[:5]): # Show 5 days
        daily_x = daily_start_x + i * daily_width

        # Day Name (Use X position from base code)
        day_dt = datetime.fromtimestamp(day_data.get('dt', 0))
        day_str = day_dt.strftime('%a')
        draw.text((daily_x + 20, daily_start_y - 5), day_str, font=heading_font, fill=text_color)

        # --- Icon Logic ---
        weather_info = day_data.get('weather', [{}])[0]
        google_icon_uri = weather_info.get('google_icon_uri')
        owm_icon_code = weather_info.get('icon')

        icon_identifier_to_download = None
        # --- Select identifier based on config ---
        if icon_provider == "google" and google_icon_uri:
            icon_identifier_to_download = google_icon_uri
            # print(f"DEBUG: Using configured Google daily icon URI") # Optional
        elif owm_icon_code and owm_icon_code != 'na':
            # Default to OWM if provider is not 'google' or google URI is missing
            # Use day version for daily icons
            if 'n' in owm_icon_code:
                icon_identifier_to_download = owm_icon_code.replace("n", "d")
            else:
                icon_identifier_to_download = owm_icon_code
            # print(f"DEBUG: Using OWM daily icon code (provider: {icon_provider})") # Optional
        else:
            print(f"Warning: No suitable daily icon identifier found for day {i}.")
        # --- End Icon Selection ---

        if icon_identifier_to_download:
            icon_path = download_and_cache_icon(icon_identifier_to_download)
            if icon_path:
                try:
                    # --- Conditional Resize ---
                    is_google_icon = isinstance(icon_identifier_to_download, str) and icon_identifier_to_download.startswith('http')
                    if is_google_icon:
                        target_icon_size = (60, 60)
                        paste_pos = (daily_x - 0, daily_start_y + 20)
                    else:
                        target_icon_size = (100, 100)
                        paste_pos = (daily_x - 12, daily_start_y + 5)

                    icon_img = Image.open(icon_path).convert("RGBA")
                    icon_img = icon_img.resize(target_icon_size, resample=LANCZOS_FILTER)

                    image.paste(icon_img, paste_pos, mask=icon_img)
                    # --- End Conditional Resize ---
                except Exception as e:
                    print(f"Error displaying daily icon for day {i}: {e}")
                    # Draw placeholder matching target size/pos (use 100x100 as default)
                    target_icon_size = (100, 100)
                    paste_pos = (daily_x - 12, daily_start_y + 5) # Use OWM position for placeholder
                    draw.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")
            else: # Placeholder if download failed
                 target_icon_size = (100, 100)
                 paste_pos = (daily_x - 12, daily_start_y + 5) # Use OWM position for placeholder
                 draw.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")

        # --- Daily Text ---
        temp_dict = day_data.get('temp', {})
        high_temp = f"{temp_dict.get('max', '?'):.0f}°".replace('?.0', '?')
        low_temp = f"{temp_dict.get('min', '?'):.0f}°".replace('?.0', '?')
        temp_y_pos = daily_start_y + 90
        temp_text = f"{high_temp} / {low_temp}"
        temp_text_x = daily_x + 10
        draw.text((temp_text_x, temp_y_pos), temp_text, font=small_font, fill=text_color)

        rain_data = day_data.get('rain', 0.0)
        rain = f"{rain_data:.1f} mm"
        rain_y_pos = temp_y_pos + 20 # Relative to temp_y_pos
        rain_text_x = daily_x + 10
        draw.text((rain_text_x, rain_y_pos), f"{rain}", font=small_font, fill=blue_color)

        wind = day_data.get('wind_speed', '?')
        wind_str = f"{wind:.1f} m/s" if isinstance(wind, (int, float)) else f"{wind} m/s"
        wind_y_pos = rain_y_pos + 20 # Relative to rain_y_pos
        wind_text_x = daily_x + 10 
        draw.text((wind_text_x, wind_y_pos), wind_str, font=small_font, fill=green_color)

        uvi = day_data.get('uvi', '?')
        uvi_str = f"UV {uvi:.1f}" if isinstance(uvi, (int, float)) else f"UV {uvi}"
        uvi_y_pos = wind_y_pos + 20 # Relative to wind_y_pos
        uvi_text_x = daily_x + 10
        draw.text((uvi_text_x, uvi_y_pos), uvi_str, font=small_font, fill=orange_color)

    # --- Save Final Image ---
    try:
        image.save(output_path)
        print(f"Weather image saved to {output_path}")
        return image
    except Exception as e:
        print(f"Error saving final image: {e}")
        return None


# --- Main Execution ---
def main():
    output_image_path = "weather_forecast_graph.png"

    # --- Load Config ---
    try:
        with open("config.json", "r") as config_file:
            config = json.load(config_file)
    except json.JSONDecodeError as e:
        print(f"Error loading config.json: {e}")
        exit(1)
    except FileNotFoundError:
        print("Error: config.json not found.")
        exit(1)

    # --- Get Icon Provider Setting ---
    # Default to 'openweathermap' if not specified
    icon_provider = config.get("icon_provider", "openweathermap").lower()
    print(f"Using icon provider: {icon_provider}")

    # --- Get Weather Provider Instance ---
    provider = weather_provider.get_weather_provider(config)
    if not provider:
        print("Failed to initialize weather provider. Exiting.")
        exit(1)

    # --- Fetch Data (uses internal caching) ---
    if not provider.fetch_data():
        if not provider.get_all_data():
            print("Failed to fetch weather data and no valid cache available. Exiting.")
            exit(1)
        else: print("Proceeding with potentially outdated cached data.")

    # --- Get Data Slices ---
    current = provider.get_current_data()
    hourly = provider.get_hourly_data()
    daily = provider.get_daily_data()

    # --- Create Image ---
    # Pass the icon_provider setting
    img = create_weather_image(current, hourly, daily, output_image_path, icon_provider)
    if img is None:
        print("Failed to create weather image. Exiting.")
        exit(1)

    # --- Process and Upload Image ---
    server_ip = config.get("server_ip")
    ip_valid = False
    if server_ip:
        try: 
            IP(server_ip)
            ip_valid = True
        except ValueError:
            print(f"Warning: Invalid server_ip '{server_ip}' in config.json. Skipping upload.")
        except Exception as e:
            print(f"Warning: Error validating server_ip '{server_ip}': {e}. Skipping upload.")
    else: print("Warning: server_ip not found in config.json. Skipping upload.")

    if ip_valid:
        print("Processing image for upload...")
        try:
            processed_data, width, height = upload.process_image(img)
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
    main()
