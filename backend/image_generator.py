# image_generator.py
import os
import io
import numpy as np
from PIL import Image, ImageDraw, ImageFont
try:
    from PIL.Image import Resampling
    LANCZOS_FILTER = Resampling.LANCZOS
except ImportError:
    LANCZOS_FILTER = Image.LANCZOS
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.path import Path
from matplotlib.ticker import MaxNLocator # Added for integer ticks
from matplotlib.transforms import Affine2D
from matplotlib.offsetbox import OffsetImage, AnnotationBbox # Moved to top-level imports
from datetime import datetime, timedelta, timezone

# Local application imports (assuming weather_data_parser is in the same directory or accessible via sys.path)
# If WeatherData is needed here for type hinting, it would be imported.
# For now, it's passed as an object, so direct import might not be strictly necessary
# from weather_data_parser import WeatherData # If type hinting WeatherData object
from icon_handling import download_and_cache_icon # Moved to icon_handling.py
import sun_utils

# Global variable for image, used by create_24h_forecast_section and create_daily_forecast_display
# This will be initialized within generate_weather_image
image_canvas = None
draw_context = None

DEFAULT_ICON_DISPLAY_CONFIGS = {
    "daily_display": {
        "google": {"width": 60, "height": 60, "x_offset": 0, "y_offset": 20},
        "openweathermap": {"width": 100, "height": 100, "x_offset": -12, "y_offset": 5},
        "meteomatics": {"width": 100, "height": 100, "x_offset": -12, "y_offset": 5},
        "default": {"width": 80, "height": 80, "x_offset": -10, "y_offset": 10}
    },
    "current_display": {
        "google": {"width": 90, "height": 90, "x_offset": 0, "y_offset": 45},
        "openweathermap": {"width": 100, "height": 100, "x_offset": -15, "y_offset": 35},
        "meteomatics": {"width": 100, "height": 100, "x_offset": -15, "y_offset": 35},
        "default": {"width": 90, "height": 90, "x_offset": -10, "y_offset": 40}
    },
    "graph_icons": {
        "google_scale_factor": 0.8,
        "openweathermap_scale_factor": 1.0,
        "meteomatics_scale_factor": 1.0,
        "default_scale_factor": 1.0
    }
}

def _load_image_from_path(image_path):
    """
    Loads an image from path. Assumes raster formats like PNG that PIL can handle directly.
    """
    # SVG handling code removed as icon_handling.py is expected to provide raster images.
    return Image.open(image_path).convert("RGBA")

def _plot_dual_color_line(ax, times, values, color_pos, color_neg, **kwargs):
    """
    Plots a line with different colors for positive and negative values.
    Intersects the line at y=0.
    """
    x_nums = mdates.date2num(times)
    y_vals = np.array(values)

    line_style = kwargs.get('linestyle', 'solid')
    linewidth = kwargs.get('linewidth', 1.5)
    zorder = kwargs.get('zorder', 2.0)

    for i in range(len(x_nums) - 1):
        x0, x1 = x_nums[i], x_nums[i+1]
        y0, y1 = y_vals[i], y_vals[i+1]

        if (y0 >= 0 and y1 >= 0) or (y0 < 0 and y1 < 0):
            # No crossing
            seg_color = color_pos if y0 >= 0 else color_neg
            ax.plot([x0, x1], [y0, y1], color=seg_color, linestyle=line_style, linewidth=linewidth, zorder=zorder)
        else:
            # Crossing zero
            t = -y0 / (y1 - y0)
            x_cross = x0 + t * (x1 - x0)

            # Segment 1
            color1 = color_pos if y0 >= 0 else color_neg
            ax.plot([x0, x_cross], [y0, 0], color=color1, linestyle=line_style, linewidth=linewidth, zorder=zorder)

            # Segment 2
            color2 = color_pos if y1 >= 0 else color_neg
            ax.plot([x_cross, x1], [0, y1], color=color2, linestyle=line_style, linewidth=linewidth, zorder=zorder)

def _plot_weather_symbols_for_series(
    current_ax, # The Matplotlib axis object for the current series
    series_times, # List of datetime objects for the current series' X-values
    series_values, # List of numerical values for the current series' Y-values
    parsed_hourly_data_all, # Full list of hourly data dicts (contains icon codes)
    series_symbol_config, # The 'weather_symbols' dict from the current series' config
    icon_provider_preference_from_config, # Global icon preference ("google" or "openweathermap")
    project_root_path_for_icons, # Path to project root for icon caching
    app_config_for_icons, # Full app config or relevant icon_configs section
    icon_cache_path=None # MODIFIED: Added new argument
):
    """
    Plots weather symbols on the graph for a specific series.
    """
    if not series_times or not series_values:
        return # No data in the series to attach symbols to

    # prefer_day_owm = series_symbol_config.get('prefer_day_owm_icons', True) # This setting will no longer affect graph icons
    icon_size_px = series_symbol_config.get('icon_size_pixels', 20)
    vertical_offset_px = series_symbol_config.get('vertical_offset_pixels', 10)
    time_interval_hrs = series_symbol_config.get('time_interval_hours', 3)

    # Get graph icon scale factor from app_config_for_icons
    icon_configs_all = app_config_for_icons.get('icon_configs', DEFAULT_ICON_DISPLAY_CONFIGS)
    graph_icon_configs = icon_configs_all.get('graph_icons', DEFAULT_ICON_DISPLAY_CONFIGS['graph_icons'])
    provider_scale_factor = graph_icon_configs.get(
        f"{icon_provider_preference_from_config}_scale_factor", # e.g., "google_scale_factor"
        graph_icon_configs.get('default_scale_factor', 1.0)
    )
    effective_icon_size_px = int(icon_size_px * provider_scale_factor)
    
    # Create a lookup for the current series' Y-values by timestamp for quick access
    current_series_y_values_map = {dt: val for dt, val in zip(series_times, series_values)}
    
    icon_display_step = max(1, int(time_interval_hrs)) # Determine how often to show an icon
    # Iterate through the complete hourly data to get icon codes and respect overall time interval
    for idx, h_data_dict in enumerate(parsed_hourly_data_all):
        if idx % icon_display_step == 0: # Check if this index matches the desired interval
            current_h_dt = h_data_dict['dt'] # Datetime object for the current hour from all data
            y_data_val = current_series_y_values_map.get(current_h_dt) # Get Y-value if this hour is in the current series

            if y_data_val is not None: # If this timestamp exists in the current series
                raw_owm_icon_code = h_data_dict.get('weather_icon')
                # weather_description = h_data_dict.get('weather_description') # Available if needed for more complex mapping

                # Always use the OWM icon code as provided by the parsed hourly data,
                # as it should already be day/night specific.
                if raw_owm_icon_code and raw_owm_icon_code != 'na':
                    chosen_owm_icon_code_for_graph = raw_owm_icon_code
                else:
                    chosen_owm_icon_code_for_graph = None                
                if chosen_owm_icon_code_for_graph:
                    # MODIFIED: Pass icon_cache_dir
                    icon_file_path = download_and_cache_icon(
                        chosen_owm_icon_code_for_graph, 
                        icon_provider_preference_from_config, # This is the global provider preference
                        project_root_path_for_icons, 
                        icon_cache_dir=icon_cache_path
                    )
                    if icon_file_path:
                        try:
                            pil_icon = _load_image_from_path(icon_file_path)
                            if not pil_icon: 
                                print(f"Warning: Failed to load/convert icon {icon_file_path} for graph.")
                                continue # Skip if loading/conversion failed

                            original_icon_w, _ = pil_icon.size
                            zoom_factor = effective_icon_size_px / original_icon_w if original_icon_w > 0 else 1.0
                            imagebox = OffsetImage(pil_icon, zoom=zoom_factor)
                            
                            ab = AnnotationBbox(imagebox, (current_h_dt, y_data_val), # type: ignore
                                                xybox=(0., vertical_offset_px), xycoords='data', # xy is data coords
                                                boxcoords="offset points", frameon=False, pad=0, zorder=10) # xybox is offset in points
                            current_ax.add_artist(ab)
                        except Exception as e_icon:
                            print(f"Error processing/plotting graph icon {chosen_owm_icon_code_for_graph} (provider: {icon_provider_preference_from_config}) for series at {current_h_dt}: {e_icon}")

def create_24h_forecast_section(
    parsed_hourly_data,
    graph_plot_config, # New: from config.yaml section graph_24h_forecast_config
    x_pos, y_pos, # Renamed for clarity, position to paste the graph
    width, height, # Dimensions for the graph area
    default_font_path, base_font_size, # Base font settings
    project_root_path_for_icons, icon_provider_preference_from_config, app_config, # Added app_config
    icon_cache_path=None # MODIFIED: Added new argument
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
    processed_series_data = {} # To store data of plotted series for reuse by fills
    deferred_fill_between_two_series_configs = [] # Store configs for fills between two other series

    for series_cfg in graph_plot_config.get('series', []):
        # Check for the new fill_between_two_series type first
        if series_cfg.get('plot_type') == 'fill_between_two_series':
            deferred_fill_between_two_series_configs.append(series_cfg)
            continue # This series type doesn't plot its own line from a 'parameter'

        param_name = series_cfg.get('parameter')
        if not param_name: continue # Skip if no parameter defined (and not a special type like above)

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
            # Store processed data for potential use in fill_between_areas
            processed_series_data[param_name] = {
                'times': series_times_filtered, 'values': series_values_filtered, 'config': series_cfg
            }
            left_axis_used = True
        elif series_cfg.get('axis') == 'right':
            # if ax_right is None: ax_right = ax_primary_left.twinx() # Logic moved
            right_axis_series_configs.append(series_data_package)
            # Store processed data
            processed_series_data[param_name] = {
                'times': series_times_filtered, 'values': series_values_filtered, 'config': series_cfg
            }
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

        color_negative = cfg.get('color_negative')
        if color_negative and cfg.get('plot_type') != 'fill_between':
            # Dual-color line plot logic
            _plot_dual_color_line(current_ax, s_times, s_values,
                                  color_pos=cfg.get('color', 'black'),
                                  color_neg=color_negative,
                                  linestyle=cfg.get('line_style', 'solid'),
                                  linewidth=cfg.get('linewidth', 1.5),
                                  zorder=2.0)
            # Add a dummy plot for legend if needed
            current_ax.plot([], [], color=cfg.get('color', 'black'), label=std_legend_item_label, linestyle=cfg.get('line_style', 'solid'), linewidth=cfg.get('linewidth', 1.5))

        elif cfg.get('plot_type') == 'fill_between':
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

        # --- Per-Series Weather Symbols (Left Axis) ---
        series_weather_symbols_cfg = cfg.get('weather_symbols', {})
        if series_weather_symbols_cfg.get('enabled', False):
            _plot_weather_symbols_for_series(
                current_ax,
                s_times,
                s_values,
                parsed_hourly_data, # Full hourly data list
                series_weather_symbols_cfg,
                icon_provider_preference_from_config,
                project_root_path_for_icons,
                app_config, # Pass app_config for icon scaling
                icon_cache_path=icon_cache_path # MODIFIED: Pass new arg
            )

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
            if not ax_primary_right: # Should not happen if right_axis_series_configs is not empty
                ax_primary_right = ax_primary_left.twinx()
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

        color_negative = cfg.get('color_negative')
        if color_negative and cfg.get('plot_type') != 'fill_between':
            # Dual-color line plot logic
            _plot_dual_color_line(current_ax, s_times, s_values,
                                  color_pos=cfg.get('color', 'black'),
                                  color_neg=color_negative,
                                  linestyle=cfg.get('line_style', 'solid'),
                                  linewidth=cfg.get('linewidth', 1.5),
                                  zorder=2.0)
            # Add a dummy plot for legend if needed
            current_ax.plot([], [], color=cfg.get('color', 'black'), label=std_legend_item_label, linestyle=cfg.get('line_style', 'solid'), linewidth=cfg.get('linewidth', 1.5))

        elif cfg.get('plot_type') == 'fill_between':
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
        force_integer_ticks = cfg.get('y_axis_integer_ticks', False)

        if show_ticks:
            if force_integer_ticks and show_tick_labels: # Apply locator only if labels are shown
                current_ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins='auto'))
            # If not forcing integer ticks, Matplotlib auto-generates based on y_lim.
            if not show_tick_labels:
                current_ax.set_yticklabels([]) # Hide labels if configured
        else: # No ticks means no labels either
            current_ax.set_yticks([])
            current_ax.set_yticklabels([]) # Explicitly clear

        plotted_axes_info.append({'ax': current_ax, 'config': cfg, 'parameter': cfg.get('parameter')})
        # Update processed_series_data with the axis object for this series
        if cfg.get('parameter') in processed_series_data:
            processed_series_data[cfg.get('parameter')]['axis'] = current_ax
        
        # --- Per-Series Weather Symbols (Right Axis) ---
        series_weather_symbols_cfg = cfg.get('weather_symbols', {})
        if series_weather_symbols_cfg.get('enabled', False):
            _plot_weather_symbols_for_series(
                current_ax,
                s_times,
                s_values,
                parsed_hourly_data, # Full hourly data list
                series_weather_symbols_cfg,
                icon_provider_preference_from_config,
                project_root_path_for_icons,
                app_config, # Pass app_config for icon scaling
                icon_cache_path=icon_cache_path # MODIFIED: Pass new arg
            )

    # Update axis information in processed_series_data after all axes are created
    for ax_info in plotted_axes_info:
        param_name = ax_info['parameter']
        if param_name in processed_series_data:
            processed_series_data[param_name]['axis'] = ax_info['ax']

    if not left_axis_used: ax_primary_left.set_yticks([]); ax_primary_left.set_yticklabels([]) # Clear if no data was ever on left
    if not right_axis_used and ax_primary_right: ax_primary_right.set_visible(False) # Hide primary right if not used
    elif not right_axis_used and not ax_primary_right: pass # No right axis was created

    # --- Fill Between Areas ---
    # The old 'fill_between_areas' top-level config is removed.
    # Now process the deferred 'fill_between_two_series' plot types.
    for fill_cfg in deferred_fill_between_two_series_configs:
        # These keys are specific to 'fill_between_two_series' plot type
        series1_param_name = fill_cfg.get('series1_param_name')
        series2_param_name = fill_cfg.get('series2_param_name')
        fill_color = fill_cfg.get('color', 'gray')
        fill_alpha = fill_cfg.get('alpha', 0.3)
        fill_zorder = fill_cfg.get('zorder', 1.8) # Default below lines

        if not series1_param_name or not series2_param_name:
            print(f"Warning: Skipping 'fill_between_two_series' due to missing series1_param_name or series2_param_name: {fill_cfg}")
            continue
        if series1_param_name not in processed_series_data or series2_param_name not in processed_series_data:
            print(f"Warning: Data for one or both params ('{series1_param_name}', '{series2_param_name}') not found in processed_series_data for 'fill_between_two_series'. Ensure they are defined as regular series. Skipping.")
            continue

        data1 = processed_series_data[series1_param_name]
        data2 = processed_series_data[series2_param_name]

        if not data1.get('axis') or not data2.get('axis'):
            print(f"Warning: Axis information missing for '{series1_param_name}' or '{series2_param_name}'. Skipping fill.")
            continue

        # Align data to common timestamps
        dict1_lookup = {dt: val for dt, val in zip(data1['times'], data1['values'])}
        dict2_lookup = {dt: val for dt, val in zip(data2['times'], data2['values'])}
        common_timestamps = sorted(list(set(data1['times']) & set(data2['times'])))

        if not common_timestamps:
            print(f"Warning: No common timestamps for '{series1_param_name}' and '{series2_param_name}'. Skipping fill.")
            continue

        aligned_values1 = [dict1_lookup[ts] for ts in common_timestamps]
        aligned_values2 = [dict2_lookup[ts] for ts in common_timestamps]

        target_axis = data1['axis'] # Plot fill on the axis of the first parameter
        target_axis.fill_between(common_timestamps, aligned_values1, aligned_values2, 
                                 color=fill_color, alpha=fill_alpha, zorder=fill_zorder, interpolate=True) # interpolate=True is good
        print(f"Filled area between '{series1_param_name}' and '{series2_param_name}'.")

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

    # --- Day/Night Highlighting ---
    day_night_cfg = graph_plot_config.get('day_night_highlight', {})
    if day_night_cfg.get('enabled', True):
        lat = app_config.get('latitude')
        lon = app_config.get('longitude')
        if lat is not None and lon is not None:
            # Calculate night intervals
            night_intervals = sun_utils.get_night_intervals(
                lat, lon, 
                min_time_overall - timedelta(hours=12), 
                max_time_overall + timedelta(hours=12),
                mode=day_night_cfg.get('mode', 'nautical_twilight')
            )
            
            dn_color = day_night_cfg.get('color', 'lightgrey')
            dn_alpha = day_night_cfg.get('alpha', 0.3)
            for start, end in night_intervals:
                # Increased zorder to ensure visibility (was 0.1)
                ax_primary_left.axvspan(start, end, color=dn_color, alpha=dn_alpha, zorder=0.5, lw=0)
        else:
            print("Warning: latitude or longitude not found in configuration. Skipping day/night highlighting.")


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
    handles = [] # Initialize handles for standard legend

    if peak_display_enabled:
        location = peak_display_cfg.get('location', 'in_graph')
        layering = peak_display_cfg.get('layering', 'in_front') # Default to in_front
        font_size = peak_display_cfg.get('font_size', tick_label_font_size -1) # Slightly smaller for legend
        text_bbox_config = peak_display_cfg.get('text_bbox', {})
        
        # Determine zorder for peak legend based on layering config
        # This zorder will be applied to fig.text or ax.text
        peak_legend_actual_zorder = 25 if layering == "in_front" else 0.5

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

        # Alignment settings for peak display text (used if converting to fig.text)
        h_align_fig_default = peak_display_cfg.get('fig_horizontal_alignment', 'center') # For location: above_graph
        h_align_axis_default = peak_display_cfg.get('axis_horizontal_alignment', 'right') # For location: in_graph

        if location == "above_graph":
            print("Using peak value display above graph.")
            reserved_top = peak_display_cfg.get('fig_reserved_top_space', 0.15)
            fig.subplots_adjust(top=(1.0 - reserved_top)) # Make space at the top of the figure

            current_y_pos = peak_display_cfg.get('fig_start_y', 0.97)
            anchor_x = peak_display_cfg.get('fig_x_coordinate', 0.5)
            h_align_to_use = h_align_fig_default
            v_align_line = 'top' # Typically 'top' or 'center' for fig.text lines
            line_y_step = peak_display_cfg.get('fig_line_y_step', 0.035)
        else: # Default to "in_graph"
            print("Using peak value display in graph.")
            current_y_pos = peak_display_cfg.get('axis_start_anchor_y', 0.97)
            anchor_x = peak_display_cfg.get('axis_anchor_x', 0.97)
            h_align_to_use = h_align_axis_default
            v_align_line = peak_display_cfg.get('axis_vertical_alignment_per_line', 'top')
            line_y_step = peak_display_cfg.get('axis_line_y_step', 0.075)

        # Collect all series data for peak legend (from left_axis_series_configs and right_axis_series_configs)
        all_series_data_for_legend = left_axis_series_configs + right_axis_series_configs
        
        for s_data in all_series_data_for_legend: # s_values is part of s_data
            cfg = s_data['config']
            s_values = s_data['values'] # Correctly access s_values
            if not s_values: continue # Check if s_values is empty
            if not cfg.get('show_peak_in_legend', False):
                continue

            param_name = cfg.get('parameter')
            # Determine descriptive text for peak value display
            # Precedence: legend_label -> parameter
            label_text = cfg.get('legend_label', param_name)
            unit_text = cfg.get('unit', '')
            value_to_display = 0

            # If the parameter is 'rain', sum the values for total; otherwise, take max for peak.
            # Assumes 'rain' parameter in series config corresponds to hourly precipitation amounts.
            if param_name == 'rain':
                value_to_display = sum(s_values)
            else:
                value_to_display = max(s_values)
            
            # Default format: .1f for float, .0f for int, direct for others
            if isinstance(value_to_display, float):
                formatted_val = f"{value_to_display:.1f}{unit_text}"
            elif isinstance(value_to_display, int):
                formatted_val = f"{value_to_display:.0f}{unit_text}"
            else: # Should ideally be numeric, but handle gracefully
                formatted_val = f"{value_to_display}{unit_text}"
                
            display_text = f"{label_text}: {formatted_val}"
            
            if location == "above_graph":
                fig.text(anchor_x, current_y_pos, display_text,
                         transform=fig.transFigure,
                         color=cfg.get('color', 'black'),
                         fontsize=font_size,
                         fontweight=peak_legend_fw, # type: ignore
                         ha=h_align_to_use,
                         va=v_align_line, # Vertical alignment for the text line itself
                         bbox=current_bbox_props,
                         zorder=peak_legend_actual_zorder) # Apply zorder
            else: # "in_graph"
                if layering == "in_front":
                    # Convert ax.transAxes coordinates to fig.transFigure coordinates
                    # (anchor_x, current_y_pos) are in ax_primary_left.transAxes
                    display_coords_in_axes_pixels = ax_primary_left.transAxes.transform((anchor_x, current_y_pos))
                    figure_coords_normalized = fig.transFigure.inverted().transform(display_coords_in_axes_pixels)
                    
                    fig.text(figure_coords_normalized[0], figure_coords_normalized[1], display_text,
                             transform=fig.transFigure, # Now using figure coordinates
                             color=cfg.get('color', 'black'),
                             fontsize=font_size,
                             fontweight=peak_legend_fw, # type: ignore
                             ha=h_align_to_use, # Use axis-derived alignment as anchor point was from axis
                             va=v_align_line,
                             bbox=current_bbox_props,
                             zorder=peak_legend_actual_zorder) # High zorder
                else: # layering == "behind" for "in_graph"
                    ax_primary_left.text(anchor_x, current_y_pos, display_text, # type: ignore
                                         transform=ax_primary_left.transAxes,
                                         color=cfg.get('color', 'black'),
                                         fontsize=font_size,
                                         fontweight=peak_legend_fw, # type: ignore
                                         ha=h_align_to_use,
                                         va=v_align_line,
                                         bbox=current_bbox_props,
                                         zorder=peak_legend_actual_zorder) # Low zorder (0.5)
            current_y_pos -= line_y_step

    elif use_standard_legend: # Standard legend
        handles, labels = [], []
        for ax_info in plotted_axes_info: # Collect handles from all plotted axes
            h, l = ax_info['ax'].get_legend_handles_labels()
            handles.extend(h); labels.extend(l)
        
        if handles:
            ncol = standard_legend_cfg.get('columns', len(handles))
            l_fontsize = standard_legend_cfg.get('fontsize', tick_label_font_size)
            l_pos = standard_legend_cfg.get('position', 'best')
            legend_font_properties = {'weight': std_legend_fw}

            # New: Configuration for legend frame
            legend_frame_on = standard_legend_cfg.get('frame_on', False)
            legend_frame_alpha = standard_legend_cfg.get('frame_alpha', 0.5) # Default alpha for semi-transparency
            legend_frame_face_color = standard_legend_cfg.get('frame_face_color', 'white')
            legend_frame_edge_color = standard_legend_cfg.get('frame_edge_color', 'grey')

            legend_obj = None # Initialize legend object
            
            if l_pos == 'bottom':
                legend_obj = fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(0.5, 0.05), 
                                        ncol=ncol, fontsize=l_fontsize, prop=legend_font_properties, 
                                        frameon=legend_frame_on) # type: ignore
                fig.subplots_adjust(bottom=0.2) 
            elif l_pos == 'top':
                legend_obj = fig.legend(handles, labels, loc='lower center', bbox_to_anchor=(0.5, 0.95), 
                                        ncol=ncol, fontsize=l_fontsize, prop=legend_font_properties, 
                                        frameon=legend_frame_on) # type: ignore
                fig.subplots_adjust(top=0.8) 
            else: 
                legend_obj = ax_primary_left.legend(handles, labels, loc=l_pos, ncol=ncol, fontsize=l_fontsize, 
                                                    prop=legend_font_properties, frameon=legend_frame_on) # type: ignore
            
            if legend_obj:
                legend_obj.set_zorder(25) # Set high zorder upon creation.
                if legend_frame_on and legend_obj.get_frame() is not None:
                    frame = legend_obj.get_frame()
                    frame.set_alpha(legend_frame_alpha)
                    frame.set_facecolor(legend_frame_face_color)
                    frame.set_edgecolor(legend_frame_edge_color)

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

    # --- Legend Workaround: Start ---
    # Move all legends created with ax.legend() to be children of the last (top-most) axis.
    # Also ensure any legends created with fig.legend() have a high z-order.
    all_figure_axes = fig.get_axes()
    if all_figure_axes: # Check if there are any axes in the figure
        top_most_axis = all_figure_axes[-1] # Last axis is generally drawn on top
        
        legends_from_axes = []
        # Collect legends from individual axes
        for current_axis_in_loop in all_figure_axes:
            ax_legend_obj = current_axis_in_loop.get_legend()
            if ax_legend_obj:
                legends_from_axes.append(ax_legend_obj)
                ax_legend_obj.remove() # Detach from original axis

        # Re-parent collected axes legends to the top-most axis
        for legend_to_reparent in legends_from_axes:
            top_most_axis.add_artist(legend_to_reparent)
            legend_to_reparent.set_zorder(25) # Ensure high z-order on the new parent

    # Ensure figure-level legends also have a high z-order
    if hasattr(fig, 'legends') and fig.legends:
        for fig_level_legend in fig.legends:
            fig_level_legend.set_zorder(25)
    # --- Legend Workaround: End ---

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


def create_daily_forecast_display(
    weather_data_daily, 
    temperature_unit_pref: str, 
    project_root_path: str, 
    icon_provider_preference: str, 
    app_config: dict, # Added app_config to get icon display properties
    fonts: dict, colors: dict,
    icon_cache_path=None # MODIFIED: Added new argument
):
    """Draws the daily forecast section onto the global image_canvas."""
    global image_canvas, draw_context # Uses global image_canvas and draw_context

    daily_start_x = 25
    daily_start_y = 270
    image_width = image_canvas.width
    temp_unit_symbol = "°" + temperature_unit_pref.upper()

    # Get daily icon display configurations
    icon_configs_all = app_config.get('icon_configs', DEFAULT_ICON_DISPLAY_CONFIGS)
    daily_icon_display_map = icon_configs_all.get('daily_display', DEFAULT_ICON_DISPLAY_CONFIGS['daily_display'])
    icon_props = daily_icon_display_map.get(icon_provider_preference, daily_icon_display_map['default'])

    # Get daily forecast display details from config
    default_daily_details_config = ['temp', 'rain', 'wind', 'uvi', 'aqi_pm25']
    daily_details_to_show = app_config.get('daily_forecast_display_details', default_daily_details_config)

    if not weather_data_daily:
        draw_context.text((daily_start_x, daily_start_y + 50), "Daily data unavailable", font=fonts['regular'], fill=(255,0,0))
        return

    daily_width = (image_width - 10) // len(weather_data_daily) if weather_data_daily else (image_width - 10) // 5

    for i, day_forecast in enumerate(weather_data_daily):
        daily_x = daily_start_x + i * daily_width

        day_str = day_forecast.get('day_name', '???')
        draw_context.text((daily_x + 20, daily_start_y - 5), day_str, font=fonts['heading'], fill=colors['text'])

        owm_icon_code = day_forecast.get('weather_icon') # Expecting OWM icon code
        if not owm_icon_code or owm_icon_code == 'na':
            original_code_debug = day_forecast.get('original_provider_icon_code', 'N/A')
            print(f"Warning: No suitable daily icon (OWM code) for day {i}. OWM code: '{owm_icon_code}', Original from provider: '{original_code_debug}'.")

        if owm_icon_code and owm_icon_code != 'na':
            # MODIFIED: Pass icon_cache_dir
            icon_path = download_and_cache_icon(
                owm_icon_code, 
                icon_provider_preference, 
                project_root_path,
                icon_cache_dir=icon_cache_path
            )
            if icon_path:
                try:
                    target_icon_size = (icon_props['width'], icon_props['height'])
                    paste_pos = (daily_x + icon_props['x_offset'], daily_start_y + icon_props['y_offset'])
                    icon_img = _load_image_from_path(icon_path)
                    if not icon_img: # Check if loading/conversion failed
                        print(f"Warning: Failed to load/convert icon {icon_path} for daily forecast (day {i}).")
                        # Draw a placeholder if it's an SVG and we can't rasterize it here
                        draw_context.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="red", fill="lightgrey")
                        continue # Skip pasting this icon
                    
                    icon_img_resized = icon_img.resize(target_icon_size, resample=LANCZOS_FILTER) # type: ignore
                    image_canvas.paste(icon_img_resized, paste_pos, mask=icon_img_resized) # type: ignore
                except Exception as e:
                    print(f"Error displaying daily icon for day {i}: {e}")
                    target_icon_size = (icon_props['width'], icon_props['height']) # Fallback size from props
                    paste_pos = (daily_x + icon_props['x_offset'], daily_start_y + icon_props['y_offset']) # Fallback pos
                    draw_context.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")
            else: # icon_path is None (download failed or skipped by handler)
                 target_icon_size = (icon_props['width'], icon_props['height'])
                 paste_pos = (daily_x + icon_props['x_offset'], daily_start_y + icon_props['y_offset'])
                 draw_context.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")
        else: # owm_icon_code is None or 'na'
            target_icon_size = (icon_props['width'], icon_props['height']); paste_pos = (daily_x + icon_props['x_offset'], daily_start_y + icon_props['y_offset'])
            draw_context.rectangle((paste_pos[0], paste_pos[1], paste_pos[0] + target_icon_size[0], paste_pos[1] + target_icon_size[1]), outline="grey")

        # Dynamically draw daily details based on config
        current_detail_y_pos = daily_start_y + 90 # Starting Y position for the first detail
        detail_line_height = 20
        detail_text_x = daily_x + 10

        if 'temp' in daily_details_to_show:
            high_temp_val = day_forecast.get('temp_max')
            low_temp_val = day_forecast.get('temp_min')
            high_temp_str = f"{high_temp_val:.0f}" if high_temp_val is not None else "?"
            low_temp_str = f"{low_temp_val:.0f}" if low_temp_val is not None else "?"
            temp_text = f"{high_temp_str}{temp_unit_symbol} / {low_temp_str}{temp_unit_symbol}"
            draw_context.text((detail_text_x, current_detail_y_pos), temp_text, font=fonts['small'], fill=colors['text'])
            current_detail_y_pos += detail_line_height

        if 'rain' in daily_details_to_show:
            rain_val = day_forecast.get('rain')
            rain_text = f"{rain_val:.1f} mm" if rain_val is not None else "? mm"
            draw_context.text((detail_text_x, current_detail_y_pos), rain_text, font=fonts['small'], fill=colors['blue'])
            current_detail_y_pos += detail_line_height

        if 'wind' in daily_details_to_show:
            wind_val = day_forecast.get('wind_speed')
            wind_str = f"{wind_val:.1f} m/s" if wind_val is not None and isinstance(wind_val, (int, float)) else "? m/s"
            draw_context.text((detail_text_x, current_detail_y_pos), wind_str, font=fonts['small'], fill=colors['green'])
            current_detail_y_pos += detail_line_height

        if 'uvi' in daily_details_to_show:
            uvi_val = day_forecast.get('uvi')
            uvi_str = ""
            if uvi_val is not None:
                if isinstance(uvi_val, (int, float)):
                    uvi_str = f"UV {uvi_val:.1f}"
                else:
                    uvi_str = f"UV {uvi_val}"
            else:
                uvi_str = "UV ?"
            draw_context.text((detail_text_x, current_detail_y_pos), uvi_str, font=fonts['small'], fill=colors['orange'])
            current_detail_y_pos += detail_line_height

        if 'aqi_pm25' in daily_details_to_show:
            aqi_pm25_avg_val = day_forecast.get('aqi_pm25_avg')
            aqi_pm25_str = f"PM2.5: {aqi_pm25_avg_val}" if aqi_pm25_avg_val is not None else "PM2.5: ?"
            draw_context.text((detail_text_x, current_detail_y_pos), aqi_pm25_str, font=fonts['small'], fill=colors.get('grey', (100,100,100)))
            # current_detail_y_pos += detail_line_height # No increment if it's the last possible item


def generate_weather_image(weather_data, output_path: str, app_config: dict, project_root_path: str, icon_cache_path=None): # MODIFIED: Added new argument
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
        'orange': (255, 140, 0),
        'grey': (100, 100, 100) # Added grey for AQI text
    }
    draw_context.rectangle(((0, 0), (image_width, image_height)), fill=colors['bg'])

    # --- Current Weather Section ---
    current_weather_width = 150
    current_temp_text = weather_data.current.get('temp_display', '?°') # Use temp_display
    temp_x = 25
    temp_y = 10
    draw_context.text((temp_x, temp_y), current_temp_text, font=fonts['temp'], fill=colors['text'])

    # Get icon_provider_preference from the main app_config for consistent icon handling
    # main_icon_provider_pref = app_config.get("icon_provider", "openweathermap").lower() # Not used directly here

    owm_icon_code_current = weather_data.current.get('weather_icon') # Expecting OWM icon code
    # Use the new specific config for display icons (current weather, daily forecast)
    display_icon_provider_pref = app_config.get("icon_provider_display", "openweathermap").lower()

    # Get current weather icon display configurations
    icon_configs_all = app_config.get('icon_configs', DEFAULT_ICON_DISPLAY_CONFIGS)
    current_icon_display_map = icon_configs_all.get('current_display', DEFAULT_ICON_DISPLAY_CONFIGS['current_display'])
    current_icon_props = current_icon_display_map.get(display_icon_provider_pref, current_icon_display_map['default'])
    target_icon_size_current = (current_icon_props['width'], current_icon_props['height'])
    paste_pos_current = (temp_x + current_icon_props['x_offset'], temp_y + current_icon_props['y_offset'])

    if owm_icon_code_current and owm_icon_code_current != 'na':
        # MODIFIED: Pass icon_cache_dir
        icon_path = download_and_cache_icon(
            owm_icon_code_current, 
            display_icon_provider_pref, 
            project_root_path,
            icon_cache_dir=icon_cache_path
        )
        if icon_path:
            try:
                icon_image_obj = _load_image_from_path(icon_path) 
                if not icon_image_obj : 
                    print(f"Warning: Failed to load/convert icon {icon_path} for current weather.")
                    draw_context.rectangle((paste_pos_current[0], paste_pos_current[1], paste_pos_current[0] + target_icon_size_current[0], paste_pos_current[1] + target_icon_size_current[1]), outline="red", fill="lightgrey")
                else:
                    icon_image_obj_resized = icon_image_obj.resize(target_icon_size_current, resample=LANCZOS_FILTER) # type: ignore
                    image_canvas.paste(icon_image_obj_resized, paste_pos_current, mask=icon_image_obj_resized) # type: ignore
            except Exception as e:
                print(f"Error displaying current icon: {e}")
                draw_context.rectangle((paste_pos_current[0], paste_pos_current[1], paste_pos_current[0] + target_icon_size_current[0], paste_pos_current[1] + target_icon_size_current[1]), outline="grey")
        else: # icon_path is None
             draw_context.rectangle((paste_pos_current[0], paste_pos_current[1], paste_pos_current[0] + target_icon_size_current[0], paste_pos_current[1] + target_icon_size_current[1]), outline="grey")
    else: # owm_icon_code_current is None or 'na'
        draw_context.rectangle((paste_pos_current[0], paste_pos_current[1], paste_pos_current[0] + target_icon_size_current[0], paste_pos_current[1] + target_icon_size_current[1]), outline="grey")

    details_y = 135
    details_x = 20
    line_height = 25

    # Dynamically build current weather details based on config
    default_current_details = ['feels_like', 'humidity', 'wind_speed', 'aqi']
    details_to_show_config = app_config.get('current_weather_display_details', default_current_details)
    details = []
    current_detail_map = {
        "feels_like": f"Feel  : {weather_data.current.get('feels_like_display', '?°')}",
        "humidity":   f"Hum.: {weather_data.current.get('humidity_display', '?%')}",
        "wind_speed": f"Wind: {weather_data.current.get('wind_speed_display', '? m/s')}",
        "aqi":        f"AQI:  {weather_data.current.get('aqi_display', ' ?')}", # Assuming aqi_display is a string like "AQI: 42"
    }

    for detail_key in details_to_show_config:
        if detail_key in current_detail_map:
            details.append(current_detail_map[detail_key])
        else:
            print(f"Warning: Unknown current weather detail key '{detail_key}' in config. Skipping.")

    for i, text in enumerate(details):
        text_color = colors['text']
        draw_context.text((details_x, details_y + i * line_height), text, font=fonts['regular'], fill=text_color)

    # --- Hourly Forecast Graph Section ---
    hourly_forecast_x = current_weather_width
    hourly_forecast_y = 0
    hourly_forecast_height = 250
    hourly_forecast_width = image_width - current_weather_width - 15
    
    graph_specific_config = app_config.get("graph_24h_forecast_config")

    # Use the new specific config for graph icons
    graph_icon_provider_pref = app_config.get("icon_provider_graph", "openweathermap").lower()

    create_24h_forecast_section(
        weather_data.hourly, graph_specific_config,
        hourly_forecast_x, hourly_forecast_y, hourly_forecast_width, hourly_forecast_height,
        font_path, graph_base_font_size, # For graph text
        project_root_path, graph_icon_provider_pref, app_config,
        icon_cache_path=icon_cache_path # MODIFIED: Added new argument
    ) 

    # --- Daily Forecast Section ---
    create_daily_forecast_display(
        weather_data.daily, weather_data.temperature_unit, 
        project_root_path, display_icon_provider_pref, app_config, # Pass display_icon_provider_pref
        fonts, colors,
        icon_cache_path=icon_cache_path # MODIFIED: Added new argument
    )

    # --- Save Final Image ---
    try:
        image_canvas.save(output_path)
        print(f"Weather image saved to {output_path}")
        return image_canvas
    except Exception as e:
        print(f"Error saving final image: {e}")
        return None