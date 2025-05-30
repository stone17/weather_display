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


def create_24h_forecast_section(
    parsed_hourly_data,
    graph_plot_config, # New: from config.yaml section graph_24h_forecast_config
    x_pos, y_pos, # Renamed for clarity, position to paste the graph
    width, height,
    default_font_path, base_font_size # Base font settings from generate_weather_image
):
    """Creates the 24-hour forecast section (graph) on the image_canvas."""
    global image_canvas # Uses global image_canvas

    if not parsed_hourly_data:
        print("Warning: No hourly forecast data provided for graph.")
        try:
            # Use draw_context which should be initialized by generate_weather_image
            if draw_context:
                fallback_font = ImageFont.truetype(default_font_path, base_font_size + 2)
                draw_context.text((x_pos + 10, y_pos + height // 2), "Hourly data unavailable", font=fallback_font, fill=(255, 0, 0))
        except IOError:
            print("Warning: Could not load fallback font for graph error message.")
        return

    times = [h['dt'] for h in parsed_hourly_data]
    temps = [h['temp'] for h in parsed_hourly_data]
    winds = [h['wind_speed'] for h in parsed_hourly_data]
    winds_deg = [h['wind_deg'] for h in parsed_hourly_data]
    rains = [h['rain'] for h in parsed_hourly_data]

    # Check for graph_plot_config
    if not graph_plot_config or not graph_plot_config.get('series'):
        print("Warning: No graph series configured in 'graph_24h_forecast_config'. Skipping graph.")
        if draw_context:
            try:
                fallback_font = ImageFont.truetype(default_font_path, base_font_size)
                draw_context.text((x_pos + 10, y_pos + height // 2), "Graph not configured.", font=fallback_font, fill=(200, 0, 0))
            except IOError:
                pass # Already warned about font loading
        return

    # Extract original full times list for x-axis reference
    original_times = [h['dt'] for h in parsed_hourly_data if h.get('dt')]
    if not original_times:
        print("Warning: No valid time data for forecast graph.")
        return

    # Prepare fonts using base_font_size
    try:
        axis_label_font_size = max(9, base_font_size)
        tick_label_font_size = max(8, base_font_size -1)
    except IOError:
        print(f"Warning: Could not load font {default_font_path} for graph. Matplotlib will use its default.")
        # Matplotlib will use its own defaults if system fonts are an issue here
        axis_label_font_size = 10 # Fallback sizes
        tick_label_font_size = 9

    # Extract font weight settings from graph_plot_config for axis labels and ticks
    y_axis_label_fw = graph_plot_config.get('y_axis_label_font_weight', 'normal')
    x_axis_tick_fw = graph_plot_config.get('x_axis_tick_font_weight', 'normal')
    y_axis_tick_fw = graph_plot_config.get('y_axis_tick_font_weight', 'normal')

    fig, ax_primary_left = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    # ax_right = None # Will be managed differently
    left_axis_series_configs, right_axis_series_configs = [], []
    left_axis_used, right_axis_used = False, False

    for series_cfg in graph_plot_config.get('series', []):
        param_name = series_cfg.get('parameter')
        if not param_name: continue

        values = [h.get(param_name) for h in parsed_hourly_data]
        series_times_filtered, series_values_filtered = [], []
        for t, v in zip(original_times, values): # Use original_times for alignment
            if t is not None and v is not None:
                series_times_filtered.append(t)
                series_values_filtered.append(v)
        
        if not series_values_filtered:
            print(f"Warning: No valid data for parameter '{param_name}'. Skipping this series.")
            continue

        series_data_package = {'config': series_cfg, 'times': series_times_filtered, 'values': series_values_filtered}
        if series_cfg.get('axis') == 'left':
            left_axis_series_configs.append(series_data_package)
            left_axis_used = True
        elif series_cfg.get('axis') == 'right':
            # if ax_right is None: ax_right = ax_primary_left.twinx() # Logic moved
            right_axis_series_configs.append(series_data_package)
            right_axis_used = True

    # --- Axis Creation, Plotting, and Scaling ---
    # This section is significantly refactored for independent axes
    
    plotted_axes_info = [] # To store (axis_obj, series_cfg) for legend and wind arrows
    
    left_spine_offset = 0
    right_spine_offset = 0
    spine_offset_increment = 60 # Pixels, adjust as needed

    # Process Left Axis Series
    is_first_on_left = True
    for s_data in left_axis_series_configs:
        cfg, s_times, s_values = s_data['config'], s_data['times'], s_data['values']
        current_ax = None
        if is_first_on_left:
            current_ax = ax_primary_left
            is_first_on_left = False
        else:
            current_ax = ax_primary_left.twinx()
            current_ax.spines["left"].set_position(("outward", left_spine_offset))
            current_ax.spines["right"].set_visible(False) # Hide the default right spine
            current_ax.yaxis.tick_left()
            current_ax.yaxis.set_label_position("left")
            left_spine_offset += spine_offset_increment

        # --- Y-axis scaling logic for the current series ---
        data_s_min, data_s_max = min(s_values), max(s_values)
        scale_type = cfg.get('scale_type', 'auto_padded') # Default to auto_padded
        y_lim_min, y_lim_max = data_s_min, data_s_max

        if scale_type == "auto_padded":
            data_range = data_s_max - data_s_min
            # Default occupancy means data takes ~83.3% of axis (equiv. to 10% padding on data range top/bottom)
            occupancy = cfg.get('data_occupancy_factor', 1.0 / 1.2) 
            if data_range == 0:
                y_lim_min = data_s_min - 1
                y_lim_max = data_s_max + 1
            else:
                if occupancy <= 0 or occupancy > 1: occupancy = 1.0 / 1.2 # Ensure valid occupancy
                total_axis_span = data_range / occupancy
                total_padding = total_axis_span - data_range
                padding_each_side = total_padding / 2
                y_lim_min = data_s_min - padding_each_side
                y_lim_max = data_s_max + padding_each_side
        
        elif scale_type == "manual_range":
            cfg_y_min = cfg.get('y_axis_min')
            cfg_y_max = cfg.get('y_axis_max')
            default_padding_abs = 1.0 
            default_padding_factor = 0.1 

            if cfg_y_min is not None and cfg_y_max is not None:
                y_lim_min, y_lim_max = cfg_y_min, cfg_y_max
                if y_lim_min >= y_lim_max: y_lim_max = y_lim_min + default_padding_abs 
            elif cfg_y_min is not None:
                y_lim_min = cfg_y_min
                effective_data_max = max(data_s_max, y_lim_min)
                current_range = effective_data_max - y_lim_min
                padding = default_padding_abs if current_range == 0 else current_range * default_padding_factor
                y_lim_max = effective_data_max + padding
            elif cfg_y_max is not None:
                y_lim_max = cfg_y_max
                effective_data_min = min(data_s_min, y_lim_max)
                current_range = y_lim_max - effective_data_min
                padding = default_padding_abs if current_range == 0 else current_range * default_padding_factor
                y_lim_min = effective_data_min - padding
            else: # Neither min nor max specified for manual_range, so auto-scale with default padding
                data_range = data_s_max - data_s_min
                padding = default_padding_abs if data_range == 0 else data_range * default_padding_factor
                y_lim_min = data_s_min - padding
                y_lim_max = data_s_max + padding
        current_ax.set_ylim(y_lim_min, y_lim_max)
        
        # Determine label for standard legend (fallback to parameter name)
        std_legend_item_label = cfg.get('legend_label', cfg.get('parameter'))
        plot_args = {
            'color': cfg.get('color', 'black'),
            'label': std_legend_item_label,
            'linewidth': cfg.get('linewidth', 1.5)
            # zorder will be set based on plot_type
        }

        if cfg.get('plot_type') == 'fill_between':
            plot_args['zorder'] = 1.9 # Fills just behind lines
            current_ax.fill_between(s_times, s_values, alpha=cfg.get('alpha', 0.3), **plot_args)
        else:
            plot_args['zorder'] = 2.0 # Lines
            current_ax.plot(s_times, s_values, linestyle=cfg.get('line_style', 'solid'), **plot_args)

        # Set Y-axis label for this series
        y_axis_text_for_series = cfg.get('axis_label', '') # Default to empty string
        if y_axis_text_for_series: # Only set label if axis_label is provided and not empty
            series_plot_side = cfg.get('axis', 'left') # Where the series' spine is (left/right of graph)
            label_text_actual_side = cfg.get('axis_label_side', series_plot_side) # left/right of its own spine
            current_ax.yaxis.set_label_position(label_text_actual_side)
            current_ax.set_ylabel(y_axis_text_for_series, color=cfg.get('color', 'black'), fontsize=axis_label_font_size, fontweight=y_axis_label_fw)
        else:
            current_ax.set_ylabel('') # Explicitly set to empty if not provided or configured empty

        current_ax.tick_params(axis='y', labelcolor=cfg.get('color', 'black'), labelsize=tick_label_font_size)
        # Apply fontweight to y-tick labels individually
        for label in current_ax.get_yticklabels():
            label.set_fontweight(y_axis_tick_fw)
        # Handle tick visibility for this series' axis
        show_ticks = cfg.get('show_y_axis_ticks', True)
        show_tick_labels = cfg.get('show_y_axis_tick_labels', True)

        if show_ticks:
            # auto_padded should determine its own ticks based on its calculated range.
            # Matplotlib will auto-generate ticks based on the y_lim_min and y_lim_max.
            if not show_tick_labels:
                current_ax.set_yticklabels([])
        else: # No ticks means no labels either
            current_ax.set_yticks([])
            current_ax.set_yticklabels([]) # Explicitly clear, though set_yticks([]) usually does it

        plotted_axes_info.append({'ax': current_ax, 'config': cfg, 'parameter': cfg.get('parameter')})

    # Process Right Axis Series
    is_first_on_right = True
    ax_primary_right = None # Initialize primary right axis
    for s_data in right_axis_series_configs:
        cfg, s_times, s_values = s_data['config'], s_data['times'], s_data['values']
        current_ax = None
        if is_first_on_right:
            ax_primary_right = ax_primary_left.twinx()
            current_ax = ax_primary_right
            is_first_on_right = False
        else:
            current_ax = ax_primary_left.twinx()
            current_ax.spines["right"].set_position(("outward", right_spine_offset))
            current_ax.spines["left"].set_visible(False) # Hide the default left spine
            current_ax.yaxis.tick_right()
            current_ax.yaxis.set_label_position("right")
            right_spine_offset += spine_offset_increment

        # --- Y-axis scaling logic for the current series ---
        data_s_min, data_s_max = min(s_values), max(s_values)
        scale_type = cfg.get('scale_type', 'auto_padded') # Default to auto_padded
        y_lim_min, y_lim_max = data_s_min, data_s_max

        if scale_type == "auto_padded":
            data_range = data_s_max - data_s_min
            occupancy = cfg.get('data_occupancy_factor', 1.0 / 1.2)
            if data_range == 0:
                y_lim_min = data_s_min - 1
                y_lim_max = data_s_max + 1
            else:
                if occupancy <= 0 or occupancy > 1: occupancy = 1.0 / 1.2
                total_axis_span = data_range / occupancy
                total_padding = total_axis_span - data_range
                padding_each_side = total_padding / 2
                y_lim_min = data_s_min - padding_each_side
                y_lim_max = data_s_max + padding_each_side

        elif scale_type == "manual_range":
            cfg_y_min = cfg.get('y_axis_min')
            cfg_y_max = cfg.get('y_axis_max')
            default_padding_abs = 1.0
            default_padding_factor = 0.1

            if cfg_y_min is not None and cfg_y_max is not None:
                y_lim_min, y_lim_max = cfg_y_min, cfg_y_max
                if y_lim_min >= y_lim_max: y_lim_max = y_lim_min + default_padding_abs
            elif cfg_y_min is not None:
                y_lim_min = cfg_y_min
                effective_data_max = max(data_s_max, y_lim_min)
                current_range = effective_data_max - y_lim_min
                padding = default_padding_abs if current_range == 0 else current_range * default_padding_factor
                y_lim_max = effective_data_max + padding
            elif cfg_y_max is not None:
                y_lim_max = cfg_y_max
                effective_data_min = min(data_s_min, y_lim_max)
                current_range = y_lim_max - effective_data_min
                padding = default_padding_abs if current_range == 0 else current_range * default_padding_factor
                y_lim_min = effective_data_min - padding
            else: # Neither min nor max specified for manual_range, so auto-scale with default padding
                data_range = data_s_max - data_s_min
                padding = default_padding_abs if data_range == 0 else data_range * default_padding_factor
                y_lim_min = data_s_min - padding
                y_lim_max = data_s_max + padding
        current_ax.set_ylim(y_lim_min, y_lim_max)

        # Determine label for standard legend (fallback to parameter name)
        std_legend_item_label = cfg.get('legend_label', cfg.get('parameter'))
        plot_args = {
            'color': cfg.get('color', 'black'),
            'label': std_legend_item_label,
            'linewidth': cfg.get('linewidth', 1.5)
            # zorder will be set based on plot_type
        }

        if cfg.get('plot_type') == 'fill_between':
            plot_args['zorder'] = 1.9 # Fills just behind lines
            current_ax.fill_between(s_times, s_values, alpha=cfg.get('alpha', 0.3), **plot_args)
        else:
            plot_args['zorder'] = 2.0 # Lines
            current_ax.plot(s_times, s_values, linestyle=cfg.get('line_style', 'solid'), **plot_args)

        # Set Y-axis label for this series
        y_axis_text_for_series = cfg.get('axis_label', '') # Default to empty string
        if y_axis_text_for_series: # Only set label if axis_label is provided and not empty
            series_plot_side = cfg.get('axis', 'right') # Where the series' spine is (left/right of graph)
            label_text_actual_side = cfg.get('axis_label_side', series_plot_side) # left/right of its own spine
            current_ax.yaxis.set_label_position(label_text_actual_side)
            current_ax.set_ylabel(y_axis_text_for_series, color=cfg.get('color', 'black'), fontsize=axis_label_font_size, fontweight=y_axis_label_fw)
        else:
            current_ax.set_ylabel('') # Explicitly set to empty if not provided or configured empty
        current_ax.tick_params(axis='y', labelcolor=cfg.get('color', 'black'), labelsize=tick_label_font_size)
        # Apply fontweight to y-tick labels individually
        for label in current_ax.get_yticklabels():
            label.set_fontweight(y_axis_tick_fw)
        # Handle tick visibility for this series' axis
        show_ticks = cfg.get('show_y_axis_ticks', True)
        show_tick_labels = cfg.get('show_y_axis_tick_labels', True)

        if show_ticks:
            # auto_padded should determine its own ticks based on its calculated range.
            # Matplotlib will auto-generate ticks based on the y_lim_min and y_lim_max.
            if not show_tick_labels:
                current_ax.set_yticklabels([])
        else: # No ticks means no labels either
            current_ax.set_yticks([])
            current_ax.set_yticklabels([]) # Explicitly clear

        plotted_axes_info.append({'ax': current_ax, 'config': cfg, 'parameter': cfg.get('parameter')})

    if not left_axis_used: ax_primary_left.set_yticks([]); ax_primary_left.set_yticklabels([]) # Clear if no data was ever on left
    if not right_axis_used and ax_primary_right: ax_primary_right.set_visible(False) # Hide primary right if not used
    elif not right_axis_used and not ax_primary_right: pass # No right axis was created

    # Common X-axis settings (apply to the base axis, ax_primary_left)
    all_plotted_times = [t for s_list in (left_axis_series_configs, right_axis_series_configs) for s_data in s_list for t in s_data['times']]
    if not all_plotted_times:
        plt.close(fig)
        print("No data ended up being plotted on the graph.")
        return

    min_time_overall, max_time_overall = min(all_plotted_times), max(all_plotted_times)
    try:
        start_tick_time = (min_time_overall + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0) if min_time_overall.tzinfo else datetime.combine(min_time_overall.date(), datetime.min.time()) + timedelta(hours=min_time_overall.hour + 1)
    except Exception: start_tick_time = min_time_overall

    ax_primary_left.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, graph_plot_config.get('x_axis_hour_interval', 6))))
    ax_primary_left.xaxis.set_major_formatter(mdates.DateFormatter(graph_plot_config.get('x_axis_time_format', '%H:%M')))
    ax_primary_left.set_xlim(left=start_tick_time, right=max_time_overall + timedelta(minutes=30))
    plt.xticks(rotation=graph_plot_config.get('x_axis_tick_rotation', 0), ha="center", fontsize=tick_label_font_size, fontweight=x_axis_tick_fw)
    ax_primary_left.grid(True, which='major', axis='x', linestyle='-', color='grey', alpha=0.3)
    
    # Y-Grids (apply to primary axes only to avoid clutter)
    if graph_plot_config.get('show_y_grid_left', True) and left_axis_used:
        ax_primary_left.grid(True, which='major', axis='y', linestyle=':', color='grey', alpha=0.3)
    if graph_plot_config.get('show_y_grid_right', True) and right_axis_used and ax_primary_right:
        ax_primary_right.grid(True, which='major', axis='y', linestyle=':', color='grey', alpha=0.3)


    # --- Legend Handling ---
    legend_main_cfg = graph_plot_config.get('legend', {})
    peak_display_cfg = legend_main_cfg.get('peak_value_display', {})
    standard_legend_cfg = legend_main_cfg.get('standard_legend', {})
    
    # Font weights for legends
    peak_legend_fw = peak_display_cfg.get('font_weight', 'normal')
    std_legend_fw = standard_legend_cfg.get('font_weight', 'normal')

    peak_display_enabled = peak_display_cfg.get('enabled', False)
    standard_legend_initially_enabled = standard_legend_cfg.get('enabled', True)
    use_standard_legend = standard_legend_initially_enabled and not peak_display_enabled

    if peak_display_enabled:
        location = peak_display_cfg.get('location', 'in_graph')
        layering = peak_display_cfg.get('layering', 'in_front') # Default to in_front
        font_size = peak_display_cfg.get('font_size', tick_label_font_size -1) # Slightly smaller for legend
        text_bbox_config = peak_display_cfg.get('text_bbox', {})
        
        current_bbox_props = None # Initialize to None
        if text_bbox_config.get('enabled', True):
            # If layering is "in_front", force bbox to be opaque. Otherwise, use configured alpha.
            bbox_alpha_value = 1.0 if layering == "in_front" else text_bbox_config.get('alpha', 0.75)
            current_bbox_props = dict(
                boxstyle=text_bbox_config.get('boxstyle', 'round,pad=0.3'),
                fc=text_bbox_config.get('face_color', 'white'),
                alpha=bbox_alpha_value,
                ec=text_bbox_config.get('edge_color', 'none')
            )

        if location == "above_graph":
            print("Using peak value display above graph.")
            reserved_top = peak_display_cfg.get('fig_reserved_top_space', 0.15)
            fig.subplots_adjust(top=(1.0 - reserved_top)) # Make space at the top of the figure

            current_y_pos = peak_display_cfg.get('fig_start_y', 0.97)
            anchor_x = peak_display_cfg.get('fig_x_coordinate', 0.5)
            h_align = peak_display_cfg.get('fig_horizontal_alignment', 'center')
            v_align_line = 'top' # Typically 'top' or 'center' for fig.text lines
            line_y_step = peak_display_cfg.get('fig_line_y_step', 0.035)
        else: # Default to "in_graph"
            print("Using peak value display in graph.")
            current_y_pos = peak_display_cfg.get('axis_start_anchor_y', 0.97)
            anchor_x = peak_display_cfg.get('axis_anchor_x', 0.97)
            h_align = peak_display_cfg.get('axis_horizontal_alignment', 'right')
            v_align_line = peak_display_cfg.get('axis_vertical_alignment_per_line', 'top')
            line_y_step = peak_display_cfg.get('axis_line_y_step', 0.075)

        # Collect all series data for peak legend (from left_axis_series_configs and right_axis_series_configs)
        all_series_data_for_legend = left_axis_series_configs + right_axis_series_configs
        
        for s_data in all_series_data_for_legend: # s_values is part of s_data
            cfg = s_data['config']
            if not s_values: continue
            if not cfg.get('show_peak_in_legend', False) or not s_data['values']:
                continue

            peak_val = max(s_data['values'])
            # Determine descriptive text for peak value display
            # Precedence: legend_label -> parameter
            label_text = cfg.get('legend_label', cfg.get('parameter'))
            unit_text = cfg.get('unit', '')
            
            # Default format: .1f for float, .0f for int, direct for others
            if isinstance(peak_val, float):
                formatted_peak = f"{peak_val:.1f}{unit_text}"
            elif isinstance(peak_val, int):
                formatted_peak = f"{peak_val:.0f}{unit_text}"
            else: # Should ideally be numeric, but handle gracefully
                formatted_peak = f"{peak_val}{unit_text}"
                
            display_text = f"{label_text}: {formatted_peak}"
            
            if location == "above_graph":
                fig.text(anchor_x, current_y_pos, display_text,
                         transform=fig.transFigure,
                         color=cfg.get('color', 'black'),
                         fontsize=font_size,
                         fontweight=peak_legend_fw,
                         ha=h_align,
                         va=v_align_line, # Vertical alignment for the text line itself
                         bbox=current_bbox_props)
                # zorder for fig.text is less critical as it's outside axes, but can be set if needed
            else: # "in_graph"
                # Explicit zorders: fills=1, lines=2.
                # "in_front" legend should be significantly higher, "behind" legend lower.
                legend_zorder = 20 if layering == "in_front" else 0.5 
                ax_primary_left.text(anchor_x, current_y_pos, display_text,
                                     transform=ax_primary_left.transAxes,
                                     color=cfg.get('color', 'black'),
                                     fontsize=font_size,
                                     fontweight=peak_legend_fw,
                                     ha=h_align,
                                     va=v_align_line,
                                     bbox=current_bbox_props,
                                     zorder=legend_zorder)
            current_y_pos -= line_y_step

    elif use_standard_legend: # Standard legend
        # For standard legend, Matplotlib usually handles z-order well,
        # but if needed, legend.set_zorder() could be used after creation.
        handles, labels = [], []
        for ax_info in plotted_axes_info: # Collect handles from all plotted axes
            h, l = ax_info['ax'].get_legend_handles_labels()
            handles.extend(h); labels.extend(l)
        
        if handles:
            ncol = standard_legend_cfg.get('columns', len(handles))
            l_fontsize = standard_legend_cfg.get('fontsize', tick_label_font_size)
            l_pos = standard_legend_cfg.get('position', 'best')
            legend_font_properties = {'weight': std_legend_fw}

            if l_pos == 'bottom':
                fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(0.5, 0.05), ncol=ncol, fontsize=l_fontsize, prop=legend_font_properties, frameon=False)
                fig.subplots_adjust(bottom=0.2) 
            elif l_pos == 'top':
                fig.legend(handles, labels, loc='lower center', bbox_to_anchor=(0.5, 0.95), ncol=ncol, fontsize=l_fontsize, prop=legend_font_properties, frameon=False)
                fig.subplots_adjust(top=0.8) 
            else: 
                ax_primary_left.legend(handles, labels, loc=l_pos, ncol=ncol, fontsize=l_fontsize, prop=legend_font_properties, frameon=False)

    # Wind Arrows
    wind_arrow_cfg = graph_plot_config.get('wind_arrows', {})
    if wind_arrow_cfg.get('enabled', False):
        speed_param = wind_arrow_cfg.get('parameter_speed', 'wind_speed')
        deg_param = wind_arrow_cfg.get('parameter_degrees', 'wind_deg')
        
        arrow_axis_obj = None
        # Find which axis hosts the wind speed parameter
        for ax_info in plotted_axes_info:
            if ax_info['parameter'] == speed_param:
                arrow_axis_obj = ax_info['ax']
                break

        if arrow_axis_obj:
            hourly_data_map = {h['dt']: h for h in parsed_hourly_data if h.get('dt')}
            pointy_arrow_path = Path([(1.0, 0.0), (-0.4, 0.4), (-0.4, -0.4), (1.0, 0.0)], [Path.MOVETO, Path.LINETO, Path.LINETO, Path.CLOSEPOLY])
            
            for tick_num_val in arrow_axis_obj.get_xticks(): # Use ticks from the wind speed axis
                tick_date_utc = mdates.num2date(tick_num_val).astimezone(timezone.utc)
                closest_dt = min(hourly_data_map.keys(), key=lambda dt: abs(dt - tick_date_utc), default=None)
                
                if closest_dt and closest_dt in hourly_data_map:
                    data_at_tick = hourly_data_map[closest_dt]
                    wind_s_val = data_at_tick.get(speed_param)
                    wind_d_val = data_at_tick.get(deg_param)

                    if wind_s_val is not None and wind_d_val is not None:
                        marker_angle = (270 - wind_d_val + 360) % 360
                        custom_marker = pointy_arrow_path.transformed(Affine2D().rotate_deg(marker_angle))
                        arrow_axis_obj.plot(closest_dt, wind_s_val, marker=custom_marker, linestyle='None',
                                            markersize=wind_arrow_cfg.get('size', 12),
                                            color=wind_arrow_cfg.get('color', 'black'),
                                            markeredgecolor=wind_arrow_cfg.get('edge_color', 'grey'),
                                            clip_on=False)
    if not peak_display_enabled and (not use_standard_legend or not handles): # If no legend at all, use standard tight_layout
        fig.tight_layout(pad=0.5)
    # If legend was placed with subplots_adjust, tight_layout might fight it.
    # bbox_inches='tight' in savefig is often the best for final output.

    # Finalize and Paste
    try:
        buf = io.BytesIO()
        # Save with bbox_inches='tight' to prevent clipping of labels/titles.
        # The output image in `buf` might be smaller than the target width/height
        # if the graph content is compact.
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=100) # bbox_inches='tight' is crucial
        plt.close(fig)
        buf.seek(0)
        plot_img_raw = Image.open(buf).convert("RGBA")

        # Resize the raw plot image to the target width and height for pasting.
        # This ensures it fills the allocated space on the canvas.
        plot_img_resized = plot_img_raw.resize((width, height), resample=LANCZOS_FILTER)
        
        image_canvas.paste(plot_img_resized, (x_pos, y_pos), mask=plot_img_resized)
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


def generate_weather_image(weather_data, output_path: str, app_config: dict, project_root_path: str):
    """
    Creates the weather forecast image (600x448).
    weather_data: An instance of WeatherData (from weather_data_parser.py)
    app_config: The full application configuration dictionary.
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
        graph_base_font_size = app_config.get('graph_24h_forecast_config', {}).get('base_font_size', 10)
    except IOError as e:
        print(f"Error loading font: {e}. Using default font.")
        fonts['heading'] = ImageFont.load_default()
        fonts['temp'] = ImageFont.load_default() # Potentially make this larger
        fonts['regular'] = ImageFont.load_default()
        fonts['small'] = ImageFont.load_default()
        font_path = "arial.ttf" if os.name == 'nt' else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" # Fallback for graph
        graph_base_font_size = 10 # Fallback for graph base font size

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
    
    graph_specific_config = app_config.get("graph_24h_forecast_config")

    create_24h_forecast_section(
        weather_data.hourly, graph_specific_config,
        hourly_forecast_x, hourly_forecast_y, hourly_forecast_width, hourly_forecast_height,
        font_path, graph_base_font_size)

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
