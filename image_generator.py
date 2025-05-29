# image_generator.py
import os
import requests
import hashlib
import io
from PIL import Image, ImageDraw, ImageFont
try:
    from PIL.Image import Resampling
    LANCZOS_FILTER = Resampling.LANCZOS
except ImportError:
    LANCZOS_FILTER = Image.LANCZOS
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.path import Path
from matplotlib.transforms import Affine2D
from datetime import datetime, timedelta, timezone

# Local application imports (assuming weather_data_parser is in the same directory or accessible via sys.path)
# If WeatherData is needed here for type hinting, it would be imported.
# For now, it's passed as an object, so direct import might not be strictly necessary
# from weather_data_parser import WeatherData # If type hinting WeatherData object

# Global variable for image, used by create_24h_forecast_section and create_daily_forecast_display
# This will be initialized within generate_weather_image
image_canvas = None
draw_context = None

def download_and_cache_icon(icon_identifier, project_root_path, icon_cache_dir="icon_cache"):
    """
    Downloads and caches weather icons.
    Fetches standard 50x50 (/img/w/) for OpenWeatherMap codes.
    Handles full URLs (e.g., from Google).
    Generates filename based on identifier (code or hash of URL).
    """
    full_icon_cache_dir = os.path.join(project_root_path, icon_cache_dir)
    os.makedirs(full_icon_cache_dir, exist_ok=True)

    is_url = isinstance(icon_identifier, str) and icon_identifier.startswith('http')
    icon_url = None
    icon_filename = None

    if is_url:
        icon_url = icon_identifier
        if not icon_url.lower().endswith('.png'):
            print(f"Warning: Google icon URI '{icon_identifier}' doesn't end with .png. Appending.")
            icon_url += '.png'
        base_url_for_hash = icon_url.rsplit('.png', 1)[0]
        filename_base = hashlib.md5(base_url_for_hash.encode()).hexdigest()
        icon_filename = f"google_{filename_base}.png"
    elif isinstance(icon_identifier, str) and icon_identifier != 'na':
        icon_code = icon_identifier
        icon_url = f"http://openweathermap.org/img/w/{icon_code}.png"
        icon_filename = f"{icon_code}.png"
    else:
        print(f"Skipping download for invalid icon identifier: {icon_identifier}")
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
        print(f"Error downloading icon {icon_identifier}: {e}")
    except OSError as e:
        print(f"Error saving icon {icon_identifier}: {e}")
    except Exception as e:
        print(f"Unexpected error downloading/saving icon {icon_identifier}: {e}")
    return None


def create_24h_forecast_section(parsed_hourly_data, x, y, width, height, font_path, font_size, show_wind_arrows):
    """Creates the 24-hour forecast section (graph) on the image_canvas."""
    global image_canvas # Uses global image_canvas

    if not parsed_hourly_data:
        print("Warning: No hourly forecast data provided for graph.")
        try:
            fallback_font = ImageFont.truetype(font_path, font_size + 2)
        except IOError:
            fallback_font = ImageFont.load_default()
        draw_context.text((x + 10, y + height // 2), "Hourly data unavailable", font=fallback_font, fill=(255, 0, 0))
        return

    times = [h['dt'] for h in parsed_hourly_data]
    temps = [h['temp'] for h in parsed_hourly_data]
    winds = [h['wind_speed'] for h in parsed_hourly_data]
    winds_deg = [h['wind_deg'] for h in parsed_hourly_data]
    rains = [h['rain'] for h in parsed_hourly_data]

    if not times:
        print("Warning: Insufficient valid data points for forecast graph.")
        return

    try:
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        print(f"Warning: Could not load font {font_path} for graph. Using default.")
        font = ImageFont.load_default()
        font_size = 10

    peak_wind = max(winds) if winds else 0
    peak_rain = max(rains) if rains else 0
    min_temp = min(temps) if temps else 0
    max_temp = max(temps) if temps else 0
    temp_range = max_temp - min_temp if temps else 0

    fig, ax1 = plt.subplots(figsize=(width / 100, height / 100), dpi=100)

    ax3 = ax1.twinx()
    ax3.spines['right'].set_position(('outward', 0))
    ax3.fill_between(times, rains, color='blue', alpha=0.3, label='Rainfall (mm)', linewidth=1)
    ax3.set_yticks([])
    ax3.set_yticklabels([])
    ax3.set_ylim(0, max(0.1, peak_rain * 1.4))

    ax2 = ax1.twinx()
    ax2.plot(times, winds, '--', color='green', alpha=0.7, label='Wind Speed (m/s)', linewidth=1.5)
    ax2.set_yticks([])
    ax2.set_yticklabels([])
    ax2.set_ylim(0, max(1.0, peak_wind * 1.4))

    ax1.plot(times, temps, color='red', label='Temperature (°C)', linewidth=2)
    ax1.set_ylabel('Temp. (°C)', color='red', fontsize=max(9, font_size + 2))
    ax1.yaxis.tick_right()
    ax1.set_ylim(min_temp - max(1, (temp_range * 0.1)), max_temp + max(1, (temp_range * 0.1)))
    ax1.tick_params(axis='y', labelcolor='red', which='both', left=False, right=True, labelleft=False, labelright=True, labelsize=max(8, font_size))
    ax1.tick_params(axis='x', which='both', labelsize=max(8, font_size))

    text_bbox = dict(boxstyle='round,pad=0.2', fc='white', alpha=0.7, ec='none')
    ax2.text(0.97, 0.97, f'Wind: {peak_wind:.1f} m/s', transform=ax2.transAxes,
             color='green', ha='right', va='top', fontsize=max(8, font_size - 1), bbox=text_bbox)
    ax3.text(0.97, 0.87, f'Rain: {peak_rain:.1f} mm', transform=ax3.transAxes,
             color='blue', ha='right', va='top', fontsize=max(8, font_size - 1), bbox=text_bbox)

    first_time = times[0]
    try:
        next_hour = (first_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    except ValueError:
        next_hour = first_time

    ax1.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 6)))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax1.set_xlim(left=next_hour, right=times[-1] + timedelta(minutes=30))
    plt.xticks(rotation=30, ha="right")
    ax1.grid(True, which='major', axis='x', linestyle='-', color='grey', alpha=0.3)
    ax1.grid(True, which='major', axis='y', linestyle=':', color='grey', alpha=0.3)

    fig.tight_layout(pad=0.5)

    pointy_arrow_verts = [(1.0, 0.0), (-0.4, 0.4), (-0.4, -0.4), (1.0, 0.0)]
    pointy_arrow_codes = [Path.MOVETO, Path.LINETO, Path.LINETO, Path.CLOSEPOLY]
    pointy_arrow_base_path = Path(pointy_arrow_verts, pointy_arrow_codes)
    try:
        if show_wind_arrows and winds:
            major_tick_locs = ax1.get_xticks()
            major_tick_dates_utc = [mdates.num2date(loc).astimezone(timezone.utc) for loc in major_tick_locs]

            for tick_date_utc in major_tick_dates_utc:
                if not times: continue
                closest_time_utc = min(times, key=lambda x: abs(x - tick_date_utc))
                idx_at_tick = -1
                for i, t_val in enumerate(times): # Renamed t to t_val to avoid conflict
                    if t_val == closest_time_utc:
                        idx_at_tick = i
                        break
                if idx_at_tick != -1:
                    wind_speed_val = winds[idx_at_tick]
                    wind_deg_val = winds_deg[idx_at_tick]
                    marker_angle = (270 - wind_deg_val + 360) % 360
                    rotation_transform = Affine2D().rotate_deg(marker_angle)
                    custom_rotated_marker = pointy_arrow_base_path.transformed(rotation_transform)
                    ax2.plot(closest_time_utc, wind_speed_val,
                             marker=custom_rotated_marker,
                             linestyle='None', markersize=16, color='green',
                             markeredgecolor='black', clip_on=False)

        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)
        plt.close(fig)
        buf.seek(0)
        plot_img = Image.open(buf).convert("RGBA")
        image_canvas.paste(plot_img, (x, y), mask=plot_img)
    except Exception as e:
        print(f"Error creating or pasting forecast graph: {e}")
        if 'fig' in locals() and fig: plt.close(fig)


def create_daily_forecast_display(weather_data_daily, project_root_path, fonts, colors):
    """Draws the daily forecast section onto the global image_canvas."""
    global image_canvas, draw_context # Uses global image_canvas and draw_context

    daily_start_x = 25
    daily_start_y = 270
    image_width = image_canvas.width

    if not weather_data_daily:
        draw_context.text((daily_start_x, daily_start_y + 50), "Daily data unavailable", font=fonts['regular'], fill=(255,0,0))
        return

    daily_width = (image_width - 10) // len(weather_data_daily) if weather_data_daily else (image_width - 10) // 5

    for i, day_forecast in enumerate(weather_data_daily):
        daily_x = daily_start_x + i * daily_width

        day_str = day_forecast.get('day_name', '???')
        draw_context.text((daily_x + 20, daily_start_y - 5), day_str, font=fonts['heading'], fill=colors['text'])

        icon_identifier_to_download = day_forecast.get('icon_identifier')
        if not icon_identifier_to_download:
            print(f"Warning: No suitable daily icon identifier found for day {i}.")

        if icon_identifier_to_download:
            icon_path = download_and_cache_icon(icon_identifier_to_download, project_root_path)
            if icon_path:
                try:
                    is_google_icon = isinstance(icon_identifier_to_download, str) and icon_identifier_to_download.startswith('http')
                    if is_google_icon:
                        target_icon_size = (60, 60)
                        paste_pos = (daily_x - 0, daily_start_y + 20)
                    else:
                        target_icon_size = (100, 100)
                        paste_pos = (daily_x - 12, daily_start_y + 5)

                    icon_img = Image.open(icon_path).convert("RGBA")
                    icon_img = icon_img.resize(target_icon_size, resample=LANCZOS_FILTER)
                    image_canvas.paste(icon_img, paste_pos, mask=icon_img)
                except Exception as e:
                    print(f"Error displaying daily icon for day {i}: {e}")
                    target_icon_size = (100, 100)
                    paste_pos = (daily_x - 12, daily_start_y + 5)
                    draw_context.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")
            else:
                 target_icon_size = (100, 100)
                 paste_pos = (daily_x - 12, daily_start_y + 5)
                 draw_context.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")

        high_temp = day_forecast.get('temp_max', '?°')
        low_temp = day_forecast.get('temp_min', '?°')
        temp_y_pos = daily_start_y + 90
        temp_text = f"{high_temp} / {low_temp}"
        temp_text_x = daily_x + 10
        draw_context.text((temp_text_x, temp_y_pos), temp_text, font=fonts['small'], fill=colors['text'])

        rain_text = day_forecast.get('rain', '? mm')
        rain_y_pos = temp_y_pos + 20
        rain_text_x = daily_x + 10
        draw_context.text((rain_text_x, rain_y_pos), rain_text, font=fonts['small'], fill=colors['blue'])

        wind_str = day_forecast.get('wind_speed', '? m/s')
        wind_y_pos = rain_y_pos + 20
        wind_text_x = daily_x + 10
        draw_context.text((wind_text_x, wind_y_pos), wind_str, font=fonts['small'], fill=colors['green'])

        uvi_str = day_forecast.get('uvi', 'UV ?')
        uvi_y_pos = wind_y_pos + 20
        uvi_text_x = daily_x + 10
        draw_context.text((uvi_text_x, uvi_y_pos), uvi_str, font=fonts['small'], fill=colors['orange'])


def generate_weather_image(weather_data, output_path: str, show_wind_arrows_in_graph: bool, project_root_path: str):
    """
    Creates the weather forecast image (600x448).
    weather_data: An instance of WeatherData (from weather_data_parser.py)
    """
    global image_canvas, draw_context # Initialize global image_canvas and draw_context

    if not weather_data or not weather_data.has_sufficient_data():
        print("Error: Missing essential parsed weather data for image creation.")
        image_canvas = Image.new("RGB", (600, 448), "white")
        draw_context = ImageDraw.Draw(image_canvas)
        try:
            err_font = ImageFont.truetype("arialbd.ttf" if os.name == 'nt' else "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 20)
        except IOError:
            err_font = ImageFont.load_default()
        draw_context.text((50, 200), "Error: Weather data unavailable.", font=err_font, fill="red")
        image_canvas.save(output_path)
        print(f"Error image saved to {output_path}")
        return None

    image_width = 600
    image_height = 448
    image_canvas = Image.new("RGB", (image_width, image_height), "white")
    draw_context = ImageDraw.Draw(image_canvas)

    # --- Fonts and Colors ---
    if os.name == 'nt':
        font_path="arial.ttf"
        bold_font_path="arialbd.ttf"
    else:
        font_path="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        bold_font_path="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

    fonts = {}
    try:
        fonts['heading'] = ImageFont.truetype(bold_font_path, 18)
        fonts['temp'] = ImageFont.truetype(bold_font_path, 36)
        fonts['regular'] = ImageFont.truetype(bold_font_path, 18)
        fonts['small'] = ImageFont.truetype(bold_font_path, 14)
        graph_font_size = 11
    except IOError as e:
        print(f"Error loading font: {e}. Using default font.")
        fonts['heading'] = ImageFont.load_default()
        fonts['temp'] = ImageFont.load_default()
        fonts['regular'] = ImageFont.load_default()
        fonts['small'] = ImageFont.load_default()
        font_path = "arial.ttf" if os.name == 'nt' else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" # Fallback for graph
        graph_font_size = 10

    colors = {
        'bg': (255, 255, 255),
        'text': (50, 50, 50),
        'blue': (0, 0, 200),
        'green': (0, 180, 0),
        'orange': (255, 140, 0)
    }
    draw_context.rectangle(((0, 0), (image_width, image_height)), fill=colors['bg'])

    # --- Current Weather Section ---
    current_weather_width = 150
    current_temp_text = weather_data.current.get('temp', '?°C')
    temp_x = 25
    temp_y = 10
    draw_context.text((temp_x, temp_y), current_temp_text, font=fonts['temp'], fill=colors['text'])

    icon_identifier_to_download = weather_data.current.get('icon_identifier')
    if icon_identifier_to_download:
        icon_path = download_and_cache_icon(icon_identifier_to_download, project_root_path)
        if icon_path:
            try:
                is_google_icon = isinstance(icon_identifier_to_download, str) and icon_identifier_to_download.startswith('http')
                if is_google_icon:
                    target_icon_size = (90, 90)
                    paste_pos = (temp_x - 0, temp_y + 45)
                else:
                    target_icon_size = (100, 100)
                    paste_pos = (temp_x - 15, temp_y + 35)

                icon_image_obj = Image.open(icon_path).convert("RGBA") # Renamed to avoid conflict
                icon_image_obj = icon_image_obj.resize(target_icon_size, resample=LANCZOS_FILTER)
                image_canvas.paste(icon_image_obj, paste_pos, mask=icon_image_obj)
            except Exception as e:
                print(f"Error displaying current icon: {e}")
                target_icon_size = (100, 100)
                paste_pos = (temp_x - 15, temp_y + 35)
                draw_context.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")
        else:
             target_icon_size = (100, 100)
             paste_pos = (temp_x - 15, temp_y + 35)
             draw_context.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")

    details_y = 155
    details_x = 20
    line_height = 25
    details = [
        f"Feel  : {weather_data.current.get('feels_like', '?°C')}",
        f"Hum.: {weather_data.current.get('humidity', '?%')}",
        f"Wind: {weather_data.current.get('wind_speed', '? m/s')}",
    ]
    for i, text in enumerate(details):
        draw_context.text((details_x, details_y + i * line_height), text, font=fonts['regular'], fill=colors['text'])

    # --- Hourly Forecast Graph Section ---
    hourly_forecast_x = current_weather_width
    hourly_forecast_y = 0
    hourly_forecast_height = 250
    hourly_forecast_width = image_width - current_weather_width - 15
    create_24h_forecast_section(
        weather_data.hourly, hourly_forecast_x, hourly_forecast_y,
        hourly_forecast_width, hourly_forecast_height, font_path, graph_font_size, show_wind_arrows_in_graph
    )

    # --- Daily Forecast Section ---
    create_daily_forecast_display(weather_data.daily, project_root_path, fonts, colors)

    # --- Save Final Image ---
    try:
        image_canvas.save(output_path)
        print(f"Weather image saved to {output_path}")
        return image_canvas
    except Exception as e:
        print(f"Error saving final image: {e}")
        return None

