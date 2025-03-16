import requests
import json
import time
import os
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import io
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import upload

# Load settings from config.json
with open("config.json", "r") as config_file:
    config = json.load(config_file)

API_KEY = config["api_key"]
LAT = config["latitude"]
LON = config["longitude"]
SERVER_IP = config["server_ip"]

def fetch_weather_data(api_key, lat, lon):
    """Fetches weather data from OpenWeatherMap API."""
    try:
        url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={api_key}&units=metric&exclude=minutely,alerts"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Error parsing weather data: {e}")
        return None

def download_and_cache_icon(icon_code, icon_cache_dir="icon_cache"):
    """Downloads and caches weather icons (using correct white bg URL)."""
    os.makedirs(icon_cache_dir, exist_ok=True)
    icon_filename = f"{icon_code}.png"
    icon_path = os.path.join(icon_cache_dir, icon_filename)

    if os.path.exists(icon_path):
        return icon_path

    try:
        icon_url = f"http://openweathermap.org/img/w/{icon_code}.png"  # CORRECT URL
        response = requests.get(icon_url)
        response.raise_for_status()
        with open(icon_path, 'wb') as f:
            f.write(response.content)
        return icon_path
    except requests.exceptions.RequestException as e:
        print(f"Error downloading icon {icon_code}: {e}")
        return None
    except OSError as e:
        print(f"Error saving icon {icon_code}: {e}")
        return None

def create_12h_forecast_section(draw, hourly_forecast, x, y, width, height, font_path, font_size):
    """Creates the 12-hour forecast section (graph) on the image."""

    font = ImageFont.truetype(font_path, font_size)
    title_font = ImageFont.truetype(font_path, font_size + 4)

    times = [datetime.fromtimestamp(h['dt']) for h in hourly_forecast]
    temps = [h['temp'] for h in hourly_forecast]
    winds = [h['wind_speed'] for h in hourly_forecast]
    rains = [h.get('rain', {}).get('1h', 0) for h in hourly_forecast]

    peak_wind = max(winds)
    peak_rain = max(rains)
    min_temp = min(temps)
    max_temp = max(temps)
    temp_range = max_temp - min_temp

    fig, ax1 = plt.subplots(figsize=(width / 100, height / 100), dpi=100)

    # --- Plotting Order Changes ---
    # 1. Rain (fill_between - needs to be first to be at the back)
    ax3 = ax1.twinx()
    ax3.spines['right'].set_position(('outward', 0))
    ax3.fill_between(times, rains, color='blue', alpha=0.3, label='Rainfall (mm)', linewidth=2)
    ax3.set_yticks([])
    ax3.set_yticklabels([])
    ax3.set_ylim(0, max(0.1, max(rains) * 1.4))

    # 2. Wind (plot - needs to be second)
    ax2 = ax1.twinx()
    ax2.plot(times, winds, '--', color='green', alpha=0.7, label='Wind Speed (m/s)', linewidth=2)
    ax2.set_yticks([])
    ax2.set_yticklabels([])
    ax2.set_ylim(0, max(0.1, max(winds) * 1.4))

    # 3. Temperature (plot - needs to be last to be on top)
    ax1.plot(times, temps, color='red', label='Temperature (°C)', linewidth=3)
    ax1.set_ylabel('Temp. (°C)', color='red', fontsize=13)
    #ax1.yaxis.set_label_position("right")
    ax1.yaxis.tick_right()
    ax1.set_ylim(min_temp - (temp_range * 0.1), max_temp + (temp_range * 0.1))
    ax1.tick_params(axis='y', labelcolor='red', which='both', left=False, labelleft=False, labelsize=12)
    ax1.tick_params(axis='x', which='both', labelsize=12)

    ax2.text(0.95, 0.95, f'Wind: {peak_wind:.1f} m/s', transform=ax2.transAxes,
             color='green', ha='right', va='top', fontsize=font_size)
    ax3.text(0.95, 0.85, f'Rain: {peak_rain:.1f} mm', transform=ax3.transAxes,
             color='blue', ha='right', va='top', fontsize=font_size)

    fig.tight_layout()
    #plt.title("Temperature, Wind, and Rainfall Forecast", fontsize=10, pad=10)

    # --- X-Axis Formatting (Every 3 Hours, starting at next full hour) ---
    first_time = times[0]
    next_hour = (first_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    ax1.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3)))  # Every 3 hours
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax1.set_xlim(left=next_hour) # Start at the *next* full hour
    plt.xticks(rotation=45, ha="right")  # Rotate labels for readability
    # --- ADDED GRIDLINES ---
    ax1.grid(True, which='both', axis='both', linestyle='-', color='gray', alpha=0.5)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    plot_img = Image.open(buf)
    plot_img = plot_img.convert("RGBA")

    image.paste(plot_img, (x, y+2))

def create_weather_image(data, output_path, font_path="arial.ttf"):
    """Creates the weather forecast image (600x448, with graph)."""
    global image
    if not data:
        print("No data to create image.")
        return

    image_width = 600
    image_height = 448
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)
    if 0: #use for linux system
        font_path="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf" #"arial.ttf"
        bold_font_path="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" #"arialbd.ttf"
    else:
        font_path="arial.ttf"
        bold_font_path="arialbd.ttf"

    try:
        title_font = ImageFont.truetype(bold_font_path, 24)
        heading_font = ImageFont.truetype(bold_font_path, 18)  # Use bold font for headings
        temp_font = ImageFont.truetype(bold_font_path, 36) # and temp
        regular_font = ImageFont.truetype(bold_font_path, 18)
        small_font = ImageFont.truetype(bold_font_path, 14)
    except IOError as e:
        print(f"Error loading font: {e}.  Using default font.")
        title_font = ImageFont.load_default()
        heading_font = ImageFont.load_default()
        temp_font = ImageFont.load_default()
        regular_font = ImageFont.load_default()
        small_font = ImageFont.load_default()


    bg_color = (255, 255, 255)
    text_color = (50, 50, 50)

    draw.rectangle(((0, 0), (image_width, image_height)), fill=bg_color)

    current = data['current']
    current_weather_width = 150

    #draw.text((10, 10), city_name, font=title_font, fill=text_color)
    current_time = datetime.fromtimestamp(current['dt']).strftime('%H:%M')
    #draw.text((10, 40), f"Last Updated: {current_time}", font=regular_font, fill=text_color)

    current_temp = f"{current['temp']:3.1f}°C"
    temp_x = 25
    temp_y = 10
    draw.text((temp_x, temp_y), current_temp, font=temp_font, fill=text_color)

    # --- Current Weather Icon (White Background) ---
    icon_code = current['weather'][0]['icon']
    icon_code = icon_code.replace("n", "d")  # Use day icons
    icon_path = download_and_cache_icon(icon_code)
    if icon_path:
        try:
            icon_image = Image.open(icon_path).resize((140, 140)).convert("RGBA")
            image.paste(icon_image, (temp_x-20, temp_y + 30), mask=icon_image)  # Adjusted position
        except Exception as e:
            print(f"Error displaying current icon: {e}")
            draw.rectangle((temp_x + 70, temp_y - 15, temp_x + 130, temp_y + 45), outline="black")
    else:
        draw.rectangle((temp_x + 70, temp_y - 15, temp_x + 130, temp_y + 45), outline="black")


    description = current['weather'][0]['description'].capitalize()
    #draw.text((10, 120), description, font=heading_font, fill=text_color)

    details_y = 155
    details_x = 20 #image_width - current_weather_width
    line_height = 25

    # --- Current Details (NO ICONS FOR NOW) ---
    details = [
      (f"Feel  : {current['feels_like']:.1f}°C"),
      (f"Hum.: {current['humidity']}%"),
      (f"Wind: {current['wind_speed']:.1f} m/s"),
    ]
    for i, (text) in enumerate(details):
        draw.text((details_x, details_y + i * line_height), text, font=regular_font, fill=text_color)

    hourly_forecast = data['hourly'][:12]
    hourly_forecast_x = current_weather_width
    hourly_forecast_height = 260
    create_12h_forecast_section(draw, hourly_forecast, hourly_forecast_x, 0, image_width - current_weather_width, hourly_forecast_height, font_path, 11)

    daily_start_x = 25
    daily_start_y = 270  # Adjusted for more space below the graph
    daily_width = (image_width - 40) // 5
    #draw.text((daily_start_x, daily_start_y - 40), "5-Day Forecast", font=heading_font, fill=text_color)

    daily = data['daily'][:5]
    for i, day_data in enumerate(daily):
        daily_x = daily_start_x + i * daily_width
        day_str = datetime.fromtimestamp(day_data['dt']).strftime('%a')
        draw.text((daily_x+20, daily_start_y - 5), day_str, font=heading_font, fill=text_color)

        # --- Daily Forecast Icon (White Background, 48x48) ---
        icon_code = day_data['weather'][0]['icon']
        icon_code = icon_code.replace("n", "d")
        icon_path = download_and_cache_icon(icon_code)
        if icon_path:
            try:
                icon_img = Image.open(icon_path).resize((100, 100)).convert("RGBA")
                image.paste(icon_img, (daily_x -12, daily_start_y + 5), mask=icon_img)  # Adjusted position
            except Exception as e:
                print(f"Error displaying daily icon for day {i}: {e}, path: {icon_path}")
                draw.rectangle((daily_x, daily_start_y + 15, daily_x + 48, daily_start_y + 63), outline="black") # Adjusted size
        else:
            print(f"Icon path is None for day {i}, icon_code: {icon_code}")
            draw.rectangle((daily_x, daily_start_y + 15, daily_x + 48, daily_start_y + 63), outline="black") # Adjusted size

        high_temp = f"{day_data['temp']['max']:.0f}°C"
        low_temp = f"{day_data['temp']['min']:.0f}°C"
        draw.text((daily_x, daily_start_y + 95), f"{high_temp} / {low_temp}", font=small_font, fill=text_color)

        rain_data = day_data.get('rain', 0)
        if rain_data is None:
            rain_data = 0.0
        rain = f"{rain_data:.1f} mm"
        draw.text((daily_x+10, daily_start_y + 115), f"{rain}", font=small_font, fill=text_color)

        wind = day_data.get('wind_speed')
        draw.text((daily_x+10, daily_start_y + 135), f"{wind:.1f} m/s", font=small_font, fill=text_color)

        uvi = day_data.get('uvi')
        draw.text((daily_x+10, daily_start_y + 155), f"UV {uvi:.1f}", font=small_font, fill=text_color)

    image.save(output_path)
    print(f"Weather image saved to {output_path}")
    return image

def main():
    output_image_path = "weather_forecast_graph.png"
    cache_file = "weather_data_cache_graph.json"

    try:
        if os.path.exists(cache_file):
            modified_time = os.path.getmtime(cache_file)
            if datetime.now() - datetime.fromtimestamp(modified_time) < timedelta(minutes=60):
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                print("Using cached data.")
            else:
                print("Cache expired, fetching new data.")
                data = fetch_weather_data(API_KEY, LAT, LON)
                if data:
                    with open(cache_file, 'w') as f:
                        json.dump(data, f)
        else:
            print("No cache found, fetching new data.")
            data = fetch_weather_data(API_KEY, LAT, LON)
            if data:
                with open(cache_file, 'w') as f:
                    json.dump(data, f)
    except Exception as e:
        print(f"Error with cache: {e}. Fetching new data.")
        data = fetch_weather_data(api_key, lat, lon)
        if data:
            try:
                with open(cache_file, 'w') as f:
                    json.dump(data, f)
            except Exception as e:
                print(f"Failed to save new data to cache: {e}")

    img = create_weather_image(data, output_image_path)

    #Process the image 
    processed_data, width, height = upload.process_image(img)
    print("Uploading weather image")
    upload_successful = upload.upload_processed_data(processed_data, width, height, SERVER_IP, upload.DEFAULT_UPLOAD_URL)
    if upload_successful:
        print("Upload complete")
    else:
        print("Upload failed")

if __name__ == "__main__":
    main()