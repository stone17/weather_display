import os
import io
import numpy as np
from PIL import Image, ImageDraw, ImageFont
try:
    from PIL.Image import Resampling
    LANCZOS_FILTER = Resampling.LANCZOS
except ImportError:
    LANCZOS_FILTER = Image.LANCZOS

# --- CRITICAL FIX: Set Backend for Headless/Docker ---
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
# -----------------------------------------------------

import matplotlib.dates as mdates
from matplotlib.path import Path
from matplotlib.ticker import MaxNLocator
from matplotlib.transforms import Affine2D
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from datetime import datetime, timedelta, timezone

from icon_handling import download_and_cache_icon
import sun_utils

# Global variable for image
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
    return Image.open(image_path).convert("RGBA")

def _plot_dual_color_line(ax, times, values, color_pos, color_neg, **kwargs):
    x_nums = mdates.date2num(times)
    y_vals = np.array(values)
    line_style = kwargs.get('linestyle', 'solid')
    linewidth = kwargs.get('linewidth', 1.5)
    zorder = kwargs.get('zorder', 2.0)

    for i in range(len(x_nums) - 1):
        x0, x1 = x_nums[i], x_nums[i+1]
        y0, y1 = y_vals[i], y_vals[i+1]

        if (y0 >= 0 and y1 >= 0) or (y0 < 0 and y1 < 0):
            seg_color = color_pos if y0 >= 0 else color_neg
            ax.plot([x0, x1], [y0, y1], color=seg_color, linestyle=line_style, linewidth=linewidth, zorder=zorder)
        else:
            t = -y0 / (y1 - y0)
            x_cross = x0 + t * (x1 - x0)
            color1 = color_pos if y0 >= 0 else color_neg
            ax.plot([x0, x_cross], [y0, 0], color=color1, linestyle=line_style, linewidth=linewidth, zorder=zorder)
            color2 = color_pos if y1 >= 0 else color_neg
            ax.plot([x_cross, x1], [0, y1], color=color2, linestyle=line_style, linewidth=linewidth, zorder=zorder)

def _plot_weather_symbols_for_series(current_ax, series_times, series_values, parsed_hourly_data_all, series_symbol_config, icon_provider_preference_from_config, project_root_path_for_icons, app_config_for_icons, icon_cache_path=None):
    if not series_times or not series_values: return

    icon_size_px = series_symbol_config.get('icon_size_pixels', 20)
    vertical_offset_px = series_symbol_config.get('vertical_offset_pixels', 10)
    time_interval_hrs = series_symbol_config.get('time_interval_hours', 3)

    icon_configs_all = app_config_for_icons.get('icon_configs', DEFAULT_ICON_DISPLAY_CONFIGS)
    graph_icon_configs = icon_configs_all.get('graph_icons', DEFAULT_ICON_DISPLAY_CONFIGS['graph_icons'])
    provider_scale_factor = graph_icon_configs.get(f"{icon_provider_preference_from_config}_scale_factor", 1.0)
    effective_icon_size_px = int(icon_size_px * provider_scale_factor)
    
    current_series_y_values_map = {dt: val for dt, val in zip(series_times, series_values)}
    icon_display_step = max(1, int(time_interval_hrs)) 
    
    for idx, h_data_dict in enumerate(parsed_hourly_data_all):
        if idx % icon_display_step == 0:
            current_h_dt = h_data_dict['dt']
            y_data_val = current_series_y_values_map.get(current_h_dt)

            if y_data_val is not None:
                raw_owm_icon_code = h_data_dict.get('weather_icon')
                if raw_owm_icon_code and raw_owm_icon_code != 'na':
                    icon_file_path = download_and_cache_icon(raw_owm_icon_code, icon_provider_preference_from_config, project_root_path_for_icons, icon_cache_dir=icon_cache_path)
                    if icon_file_path:
                        try:
                            pil_icon = _load_image_from_path(icon_file_path)
                            if pil_icon:
                                original_icon_w, _ = pil_icon.size
                                zoom_factor = effective_icon_size_px / original_icon_w if original_icon_w > 0 else 1.0
                                imagebox = OffsetImage(pil_icon, zoom=zoom_factor)
                                ab = AnnotationBbox(imagebox, (current_h_dt, y_data_val), xybox=(0., vertical_offset_px), xycoords='data', boxcoords="offset points", frameon=False, pad=0, zorder=10)
                                current_ax.add_artist(ab)
                        except Exception: pass

def create_24h_forecast_section(parsed_hourly_data, graph_plot_config, x_pos, y_pos, width, height, default_font_path, base_font_size, project_root_path_for_icons, icon_provider_preference_from_config, app_config, icon_cache_path=None):
    global image_canvas

    if not parsed_hourly_data:
        print("Warning: No hourly forecast data provided for graph.")
        return

    if not graph_plot_config or not graph_plot_config.get('series'):
        print("Warning: No graph series configured.")
        return

    original_times = [h['dt'] for h in parsed_hourly_data if h.get('dt')]
    if not original_times: return

    try:
        axis_label_font_size = max(9, base_font_size)
        tick_label_font_size = max(8, base_font_size -1)
    except IOError:
        axis_label_font_size = 10; tick_label_font_size = 9

    y_axis_label_fw = graph_plot_config.get('y_axis_label_font_weight', 'normal')
    x_axis_tick_fw = graph_plot_config.get('x_axis_tick_font_weight', 'normal')
    y_axis_tick_fw = graph_plot_config.get('y_axis_tick_font_weight', 'normal')

    fig, ax_primary_left = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_alpha(0) 

    left_axis_series_configs, right_axis_series_configs = [], []
    processed_series_data = {} 
    deferred_fill_between_two_series_configs = []

    for series_cfg in graph_plot_config.get('series', []):
        if series_cfg.get('plot_type') == 'fill_between_two_series':
            deferred_fill_between_two_series_configs.append(series_cfg)
            continue
        param_name = series_cfg.get('parameter')
        if not param_name: continue
        values = [h.get(param_name) for h in parsed_hourly_data]
        series_times_filtered, series_values_filtered = [], []
        for t, v in zip(original_times, values):
            if t is not None and v is not None:
                series_times_filtered.append(t); series_values_filtered.append(v)
        
        if not series_values_filtered: continue
        series_data_package = {'config': series_cfg, 'times': series_times_filtered, 'values': series_values_filtered}
        if series_cfg.get('axis') == 'left':
            left_axis_series_configs.append(series_data_package)
            processed_series_data[param_name] = {'times': series_times_filtered, 'values': series_values_filtered, 'config': series_cfg}
        elif series_cfg.get('axis') == 'right':
            right_axis_series_configs.append(series_data_package)
            processed_series_data[param_name] = {'times': series_times_filtered, 'values': series_values_filtered, 'config': series_cfg}

    plotted_axes_info = []
    left_spine_offset = 0
    right_spine_offset = 0
    spine_offset_increment = 60

    # --- Process Left Axis Series ---
    is_first_on_left = True
    left_axis_used = False
    
    for s_data in left_axis_series_configs:
        cfg, s_times, s_values = s_data['config'], s_data['times'], s_data['values']
        current_ax = None
        left_axis_used = True
        
        if is_first_on_left:
            current_ax = ax_primary_left
            is_first_on_left = False
        else:
            current_ax = ax_primary_left.twinx()
            current_ax.spines["left"].set_position(("outward", left_spine_offset))
            current_ax.spines["right"].set_visible(False)
            current_ax.yaxis.tick_left()
            current_ax.yaxis.set_label_position("left")
            left_spine_offset += spine_offset_increment

        data_s_min, data_s_max = min(s_values), max(s_values)
        scale_type = cfg.get('scale_type', 'auto_padded')
        y_lim_min, y_lim_max = data_s_min, data_s_max

        if scale_type == "auto_padded":
            data_range = data_s_max - data_s_min
            occupancy = cfg.get('data_occupancy_factor', 0.83)
            if data_range == 0: y_lim_min = data_s_min - 1; y_lim_max = data_s_max + 1
            else:
                pad = ((data_range / occupancy) - data_range) / 2
                y_lim_min = data_s_min - pad; y_lim_max = data_s_max + pad
        elif scale_type == "manual_range":
            cfg_y_min = cfg.get('y_axis_min'); cfg_y_max = cfg.get('y_axis_max')
            if cfg_y_min is not None and cfg_y_max is not None: y_lim_min, y_lim_max = cfg_y_min, cfg_y_max
            elif cfg_y_min is not None: y_lim_min = cfg_y_min; y_lim_max = max(data_s_max, y_lim_min) * 1.1
            elif cfg_y_max is not None: y_lim_max = cfg_y_max; y_lim_min = min(data_s_min, y_lim_max) * 0.9
            else: y_lim_min = data_s_min * 0.9; y_lim_max = data_s_max * 1.1

        current_ax.set_ylim(y_lim_min, y_lim_max)
        
        std_legend_item_label = cfg.get('legend_label') if cfg.get('legend_label') is not None else cfg.get('parameter')

        plot_args = {'color': cfg.get('color', 'black'), 'label': std_legend_item_label, 'linewidth': cfg.get('linewidth', 1.5)}

        color_negative = cfg.get('color_negative')
        if color_negative and cfg.get('plot_type') != 'fill_between':
            _plot_dual_color_line(current_ax, s_times, s_values, color_pos=cfg.get('color', 'black'), color_neg=color_negative, linestyle=cfg.get('line_style', 'solid'), linewidth=cfg.get('linewidth', 1.5), zorder=2.0)
            current_ax.plot([], [], color=cfg.get('color', 'black'), label=std_legend_item_label, linestyle=cfg.get('line_style', 'solid'), linewidth=cfg.get('linewidth', 1.5))
        elif cfg.get('plot_type') == 'fill_between':
            plot_args['zorder'] = 1.9
            current_ax.fill_between(s_times, s_values, alpha=cfg.get('alpha', 0.3), **plot_args)
        else:
            plot_args['zorder'] = 2.0
            current_ax.plot(s_times, s_values, linestyle=cfg.get('line_style', 'solid'), **plot_args)

        y_axis_text = cfg.get('axis_label', '')
        if y_axis_text:
            series_plot_side = 'left'
            label_side = cfg.get('axis_label_side', series_plot_side)
            current_ax.yaxis.set_label_position(label_side)
            current_ax.set_ylabel(y_axis_text, color=cfg.get('color', 'black'), fontsize=axis_label_font_size, fontweight=y_axis_label_fw)
        
        current_ax.tick_params(axis='y', labelcolor=cfg.get('color', 'black'), labelsize=tick_label_font_size)
        for label in current_ax.get_yticklabels(): label.set_fontweight(y_axis_tick_fw)
        
        if not cfg.get('show_y_axis_ticks', True): current_ax.set_yticks([])
        elif not cfg.get('show_y_axis_tick_labels', True): current_ax.set_yticklabels([])

        plotted_axes_info.append({'ax': current_ax, 'config': cfg, 'parameter': cfg.get('parameter')})
        if cfg.get('parameter') in processed_series_data:
            processed_series_data[cfg.get('parameter')]['axis'] = current_ax

        if cfg.get('weather_symbols', {}).get('enabled', False):
            _plot_weather_symbols_for_series(current_ax, s_times, s_values, parsed_hourly_data, cfg.get('weather_symbols'), icon_provider_preference_from_config, project_root_path_for_icons, app_config, icon_cache_path)

    # --- Process Right Axis Series ---
    is_first_on_right = True
    right_axis_used = False
    ax_primary_right = None
    
    for s_data in right_axis_series_configs:
        cfg, s_times, s_values = s_data['config'], s_data['times'], s_data['values']
        current_ax = None
        right_axis_used = True
        
        if is_first_on_right:
            ax_primary_right = ax_primary_left.twinx()
            current_ax = ax_primary_right
            is_first_on_right = False
        else:
            if not ax_primary_right: ax_primary_right = ax_primary_left.twinx()
            current_ax = ax_primary_left.twinx()
            current_ax.spines["right"].set_position(("outward", right_spine_offset))
            current_ax.spines["left"].set_visible(False)
            current_ax.yaxis.tick_right()
            current_ax.yaxis.set_label_position("right")
            right_spine_offset += spine_offset_increment

        data_s_min, data_s_max = min(s_values), max(s_values)
        scale_type = cfg.get('scale_type', 'auto_padded')
        y_lim_min, y_lim_max = data_s_min, data_s_max
        if scale_type == "auto_padded":
            data_range = data_s_max - data_s_min
            occupancy = cfg.get('data_occupancy_factor', 0.83)
            if data_range == 0: y_lim_min = data_s_min - 1; y_lim_max = data_s_max + 1
            else:
                pad = ((data_range / occupancy) - data_range) / 2
                y_lim_min = data_s_min - pad; y_lim_max = data_s_max + pad
        elif scale_type == "manual_range":
            cfg_y_min = cfg.get('y_axis_min'); cfg_y_max = cfg.get('y_axis_max')
            if cfg_y_min is not None and cfg_y_max is not None: y_lim_min, y_lim_max = cfg_y_min, cfg_y_max
            elif cfg_y_min is not None: y_lim_min = cfg_y_min; y_lim_max = max(data_s_max, y_lim_min) * 1.1
            elif cfg_y_max is not None: y_lim_max = cfg_y_max; y_lim_min = min(data_s_min, y_lim_max) * 0.9
            else: y_lim_min = data_s_min * 0.9; y_lim_max = data_s_max * 1.1

        current_ax.set_ylim(y_lim_min, y_lim_max)

        std_legend_item_label = cfg.get('legend_label') if cfg.get('legend_label') is not None else cfg.get('parameter')
        
        plot_args = {'color': cfg.get('color', 'black'), 'label': std_legend_item_label, 'linewidth': cfg.get('linewidth', 1.5)}

        color_negative = cfg.get('color_negative')
        if color_negative and cfg.get('plot_type') != 'fill_between':
            _plot_dual_color_line(current_ax, s_times, s_values, color_pos=cfg.get('color', 'black'), color_neg=color_negative, linestyle=cfg.get('line_style', 'solid'), linewidth=cfg.get('linewidth', 1.5), zorder=2.0)
            current_ax.plot([], [], color=cfg.get('color', 'black'), label=std_legend_item_label, linestyle=cfg.get('line_style', 'solid'), linewidth=cfg.get('linewidth', 1.5))
        elif cfg.get('plot_type') == 'fill_between':
            plot_args['zorder'] = 1.9
            current_ax.fill_between(s_times, s_values, alpha=cfg.get('alpha', 0.3), **plot_args)
        else:
            plot_args['zorder'] = 2.0
            current_ax.plot(s_times, s_values, linestyle=cfg.get('line_style', 'solid'), **plot_args)

        y_axis_text = cfg.get('axis_label', '')
        if y_axis_text:
            series_plot_side = 'right'
            label_side = cfg.get('axis_label_side', series_plot_side)
            current_ax.yaxis.set_label_position(label_side)
            current_ax.set_ylabel(y_axis_text, color=cfg.get('color', 'black'), fontsize=axis_label_font_size, fontweight=y_axis_label_fw)
        
        current_ax.tick_params(axis='y', labelcolor=cfg.get('color', 'black'), labelsize=tick_label_font_size)
        for label in current_ax.get_yticklabels(): label.set_fontweight(y_axis_tick_fw)

        if not cfg.get('show_y_axis_ticks', True): current_ax.set_yticks([])
        elif not cfg.get('show_y_axis_tick_labels', True): current_ax.set_yticklabels([])

        plotted_axes_info.append({'ax': current_ax, 'config': cfg, 'parameter': cfg.get('parameter')})
        if cfg.get('parameter') in processed_series_data:
            processed_series_data[cfg.get('parameter')]['axis'] = current_ax
        
        if cfg.get('weather_symbols', {}).get('enabled', False):
            _plot_weather_symbols_for_series(current_ax, s_times, s_values, parsed_hourly_data, cfg.get('weather_symbols'), icon_provider_preference_from_config, project_root_path_for_icons, app_config, icon_cache_path)

    if not left_axis_used: ax_primary_left.set_yticks([])
    if not right_axis_used and ax_primary_right: ax_primary_right.set_visible(False)

    # --- Fill Between Areas ---
    for fill_cfg in deferred_fill_between_two_series_configs:
        s1 = fill_cfg.get('series1_param_name'); s2 = fill_cfg.get('series2_param_name')
        if s1 in processed_series_data and s2 in processed_series_data:
            d1 = processed_series_data[s1]; d2 = processed_series_data[s2]
            if d1.get('axis'):
                common_ts = sorted(list(set(d1['times']) & set(d2['times'])))
                if common_ts:
                    d1_map = dict(zip(d1['times'], d1['values'])); d2_map = dict(zip(d2['times'], d2['values']))
                    v1 = [d1_map[ts] for ts in common_ts]; v2 = [d2_map[ts] for ts in common_ts]
                    d1['axis'].fill_between(common_ts, v1, v2, color=fill_cfg.get('color', 'gray'), alpha=fill_cfg.get('alpha', 0.3), zorder=fill_cfg.get('zorder', 1.8), interpolate=True)

    # --- Common X Axis ---
    all_times = [t for s_list in (left_axis_series_configs, right_axis_series_configs) for s in s_list for t in s['times']]
    if not all_times: 
        plt.close(fig); return

    min_time, max_time = min(all_times), max(all_times)
    ax_primary_left.set_xlim(left=min_time, right=max_time + timedelta(minutes=30))
    ax_primary_left.xaxis.set_major_locator(mdates.HourLocator(interval=graph_plot_config.get('x_axis_hour_interval', 6)))
    ax_primary_left.xaxis.set_major_formatter(mdates.DateFormatter(graph_plot_config.get('x_axis_time_format', '%H:%M')))
    plt.xticks(rotation=graph_plot_config.get('x_axis_tick_rotation', 0), ha="center", fontsize=tick_label_font_size, fontweight=x_axis_tick_fw)
    
    ax_primary_left.grid(True, which='major', axis='x', linestyle='-', color='grey', alpha=0.3)
    if graph_plot_config.get('show_y_grid_left', True) and left_axis_used:
        ax_primary_left.grid(True, which='major', axis='y', linestyle=':', color='grey', alpha=0.3)
    if graph_plot_config.get('show_y_grid_right', True) and right_axis_used and ax_primary_right:
        ax_primary_right.grid(True, which='major', axis='y', linestyle=':', color='grey', alpha=0.3)

    # --- Day/Night Highlight ---
    dn_cfg = graph_plot_config.get('day_night_highlight', {})
    if dn_cfg.get('enabled', True):
        lat = app_config.get('latitude'); lon = app_config.get('longitude')
        if lat is not None and lon is not None:
            intervals = sun_utils.get_night_intervals(lat, lon, min_time - timedelta(hours=12), max_time + timedelta(hours=12), mode=dn_cfg.get('mode', 'civil_twilight'))
            for start, end in intervals:
                ax_primary_left.axvspan(start, end, color=dn_cfg.get('color', 'lightgrey'), alpha=dn_cfg.get('alpha', 0.3), zorder=0.5, lw=0)

    # --- RESTORED COMPLEX LEGEND/PEAK LOGIC ---
    legend_main_cfg = graph_plot_config.get('legend', {})
    peak_display_cfg = legend_main_cfg.get('peak_value_display', {})
    standard_legend_cfg = legend_main_cfg.get('standard_legend', {})
    
    peak_legend_fw = peak_display_cfg.get('font_weight', 'normal')
    std_legend_fw = standard_legend_cfg.get('font_weight', 'normal')

    peak_display_enabled = peak_display_cfg.get('enabled', False)
    standard_legend_initially_enabled = standard_legend_cfg.get('enabled', True)
    use_standard_legend = standard_legend_initially_enabled and not peak_display_enabled
    handles = [] 

    if peak_display_enabled:
        location = peak_display_cfg.get('location', 'in_graph')
        layering = peak_display_cfg.get('layering', 'in_front') 
        font_size = peak_display_cfg.get('font_size', tick_label_font_size -1) 
        text_bbox_config = peak_display_cfg.get('text_bbox', {})
        
        peak_legend_actual_zorder = 25 if layering == "in_front" else 0.5

        current_bbox_props = None 
        if text_bbox_config.get('enabled', True):
            bbox_alpha_value = 1.0 if layering == "in_front" else text_bbox_config.get('alpha', 0.75)
            current_bbox_props = dict(
                boxstyle=text_bbox_config.get('boxstyle', 'round,pad=0.3'),
                fc=text_bbox_config.get('face_color', 'white'),
                alpha=bbox_alpha_value,
                ec=text_bbox_config.get('edge_color', 'none')
            )

        h_align_fig_default = peak_display_cfg.get('fig_horizontal_alignment', 'center') 
        h_align_axis_default = peak_display_cfg.get('horizontal_alignment', 'right') # Use generic horizontal_alignment

        if location == "above_graph":
            reserved_top = peak_display_cfg.get('fig_reserved_top_space', 0.15)
            fig.subplots_adjust(top=(1.0 - reserved_top)) 
            current_y_pos = peak_display_cfg.get('fig_start_y', 0.97)
            anchor_x = peak_display_cfg.get('fig_x_coordinate', 0.5)
            h_align_to_use = h_align_fig_default
            v_align_line = 'top' 
            line_y_step = peak_display_cfg.get('fig_line_y_step', 0.035)
        else: # "in_graph"
            current_y_pos = peak_display_cfg.get('axis_start_anchor_y', 0.97)
            anchor_x = peak_display_cfg.get('axis_anchor_x', 0.97)
            h_align_to_use = h_align_axis_default
            v_align_line = peak_display_cfg.get('vertical_alignment_per_line', 'top')
            line_y_step = peak_display_cfg.get('axis_line_y_step', 0.075)

        all_series_data_for_legend = left_axis_series_configs + right_axis_series_configs
        
        for s_data in all_series_data_for_legend: 
            cfg = s_data['config']
            s_values = s_data['values'] 
            if not s_values: continue 
            if not cfg.get('show_peak_in_legend', False): continue

            param_name = cfg.get('parameter')
            label_text = cfg.get('legend_label') if cfg.get('legend_label') is not None else param_name
            unit_text = cfg.get('unit', '')
            
            if param_name == 'rain':
                value_to_display = sum(s_values)
            else:
                value_to_display = max(s_values)
            
            if isinstance(value_to_display, float):
                formatted_val = f"{value_to_display:.1f}{unit_text}"
            elif isinstance(value_to_display, int):
                formatted_val = f"{value_to_display:.0f}{unit_text}"
            else: 
                formatted_val = f"{value_to_display}{unit_text}"
                
            display_text = f"{label_text}: {formatted_val}"
            
            if location == "above_graph":
                fig.text(anchor_x, current_y_pos, display_text, transform=fig.transFigure, color=cfg.get('color', 'black'), fontsize=font_size, fontweight=peak_legend_fw, ha=h_align_to_use, va=v_align_line, bbox=current_bbox_props, zorder=peak_legend_actual_zorder)
            else: # "in_graph"
                if layering == "in_front":
                    display_coords_in_axes_pixels = ax_primary_left.transAxes.transform((anchor_x, current_y_pos))
                    figure_coords_normalized = fig.transFigure.inverted().transform(display_coords_in_axes_pixels)
                    fig.text(figure_coords_normalized[0], figure_coords_normalized[1], display_text, transform=fig.transFigure, color=cfg.get('color', 'black'), fontsize=font_size, fontweight=peak_legend_fw, ha=h_align_to_use, va=v_align_line, bbox=current_bbox_props, zorder=peak_legend_actual_zorder)
                else: 
                    ax_primary_left.text(anchor_x, current_y_pos, display_text, transform=ax_primary_left.transAxes, color=cfg.get('color', 'black'), fontsize=font_size, fontweight=peak_legend_fw, ha=h_align_to_use, va=v_align_line, bbox=current_bbox_props, zorder=peak_legend_actual_zorder)
            current_y_pos -= line_y_step

    elif use_standard_legend: 
        handles, labels = [], []
        for ax_info in plotted_axes_info: 
            h, l = ax_info['ax'].get_legend_handles_labels()
            handles.extend(h); labels.extend(l)
        
        if handles:
            ncol = standard_legend_cfg.get('columns', len(handles))
            l_fontsize = standard_legend_cfg.get('fontsize', tick_label_font_size)
            l_pos = standard_legend_cfg.get('position', 'best')
            legend_font_properties = {'weight': std_legend_fw}
            legend_frame_on = standard_legend_cfg.get('frame_on', False)
            legend_frame_alpha = standard_legend_cfg.get('frame_alpha', 0.5) 
            legend_frame_face_color = standard_legend_cfg.get('frame_face_color', 'white')
            legend_frame_edge_color = standard_legend_cfg.get('frame_edge_color', 'grey')
            
            legend_obj = None
            if l_pos == 'bottom':
                legend_obj = fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(0.5, 0.05), ncol=ncol, fontsize=l_fontsize, prop=legend_font_properties, frameon=legend_frame_on)
                fig.subplots_adjust(bottom=0.2) 
            elif l_pos == 'top':
                legend_obj = fig.legend(handles, labels, loc='lower center', bbox_to_anchor=(0.5, 0.95), ncol=ncol, fontsize=l_fontsize, prop=legend_font_properties, frameon=legend_frame_on)
                fig.subplots_adjust(top=0.8) 
            else: 
                legend_obj = ax_primary_left.legend(handles, labels, loc=l_pos, ncol=ncol, fontsize=l_fontsize, prop=legend_font_properties, frameon=legend_frame_on)
            
            if legend_obj:
                legend_obj.set_zorder(25) 
                if legend_frame_on and legend_obj.get_frame() is not None:
                    frame = legend_obj.get_frame()
                    frame.set_alpha(legend_frame_alpha)
                    frame.set_facecolor(legend_frame_face_color)
                    frame.set_edgecolor(legend_frame_edge_color)

    # --- Wind Arrows ---
    wind_cfg = graph_plot_config.get('wind_arrows', {})
    if wind_cfg.get('enabled', False):
        sp_p = wind_cfg.get('parameter_speed', 'wind_speed'); deg_p = wind_cfg.get('parameter_degrees', 'wind_deg')
        arrow_ax = next((i['ax'] for i in plotted_axes_info if i['parameter'] == sp_p), None)
        if arrow_ax:
            h_map = {h['dt']: h for h in parsed_hourly_data if h.get('dt')}
            path = Path([(1,0), (-0.4,0.4), (-0.4,-0.4), (1,0)], [Path.MOVETO, Path.LINETO, Path.LINETO, Path.CLOSEPOLY])
            for tick_val in arrow_ax.get_xticks():
                dt = mdates.num2date(tick_val).astimezone(timezone.utc)
                match = min(h_map.keys(), key=lambda d: abs(d-dt), default=None)
                if match and match in h_map:
                    ws = h_map[match].get(sp_p); wd = h_map[match].get(deg_p)
                    if ws is not None and wd is not None:
                        angle = (270 - wd + 360) % 360
                        marker = path.transformed(Affine2D().rotate_deg(angle))
                        arrow_ax.plot(match, ws, marker=marker, linestyle='None', markersize=wind_cfg.get('size', 12), color=wind_cfg.get('color', 'black'), clip_on=False)

    if not peak_display_enabled and (not use_standard_legend or not handles):
         fig.tight_layout(pad=0.5)

    # --- Finalize and Paste ---
    try:
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=100, transparent=True)
        plt.close(fig)
        buf.seek(0)
        plot_img_raw = Image.open(buf).convert("RGBA")
        plot_img_resized = plot_img_raw.resize((width, height), resample=LANCZOS_FILTER)
        image_canvas.paste(plot_img_resized, (x_pos, y_pos), mask=plot_img_resized)
    except Exception as e:
        print(f"Error creating/pasting graph: {e}")
        if 'fig' in locals() and fig: plt.close(fig)


def create_daily_forecast_display(weather_data_daily, temperature_unit_pref, project_root_path, icon_provider_preference, app_config, fonts, colors, icon_cache_path=None):
    global image_canvas, draw_context
    
    image_width = image_canvas.width
    image_height = image_canvas.height
    
    daily_start_y = int(image_height * 0.60)
    daily_start_x = 25
    temp_unit_symbol = "°" + temperature_unit_pref.upper()

    icon_configs_all = app_config.get('icon_configs', DEFAULT_ICON_DISPLAY_CONFIGS)
    daily_icon_display_map = icon_configs_all.get('daily_display', DEFAULT_ICON_DISPLAY_CONFIGS['daily_display'])
    icon_props = daily_icon_display_map.get(icon_provider_preference, daily_icon_display_map['default'])
    
    default_daily_details_config = ['temp', 'rain', 'wind', 'uvi', 'aqi_pm25']
    daily_details_to_show = app_config.get('daily_forecast_display_details', default_daily_details_config)

    if not weather_data_daily:
        return

    daily_width = (image_width - 10) // len(weather_data_daily) if weather_data_daily else (image_width - 10) // 5

    for i, day_forecast in enumerate(weather_data_daily):
        daily_x = daily_start_x + i * daily_width
        day_str = day_forecast.get('day_name', '???')
        draw_context.text((daily_x + 20, daily_start_y - 5), day_str, font=fonts['heading'], fill=colors['text'])

        owm_icon_code = day_forecast.get('weather_icon')
        if owm_icon_code and owm_icon_code != 'na':
            icon_path = download_and_cache_icon(owm_icon_code, icon_provider_preference, project_root_path, icon_cache_dir=icon_cache_path)
            if icon_path:
                try:
                    target_icon_size = (icon_props['width'], icon_props['height'])
                    paste_pos = (daily_x + icon_props['x_offset'], daily_start_y + icon_props['y_offset'])
                    icon_img = _load_image_from_path(icon_path)
                    if icon_img:
                        icon_img_resized = icon_img.resize(target_icon_size, resample=LANCZOS_FILTER)
                        image_canvas.paste(icon_img_resized, paste_pos, mask=icon_img_resized)
                except Exception: pass

        current_detail_y_pos = daily_start_y + 90 
        detail_text_x = daily_x + 10
        detail_line_height = 20

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
            wind_str = f"{wind_val:.1f} m/s" if wind_val is not None else "? m/s"
            draw_context.text((detail_text_x, current_detail_y_pos), wind_str, font=fonts['small'], fill=colors['green'])
            current_detail_y_pos += detail_line_height

        if 'uvi' in daily_details_to_show:
            uvi_val = day_forecast.get('uvi')
            uvi_str = f"UV {uvi_val:.1f}" if uvi_val is not None else "UV ?"
            draw_context.text((detail_text_x, current_detail_y_pos), uvi_str, font=fonts['small'], fill=colors['orange'])
            current_detail_y_pos += detail_line_height


def generate_weather_image(weather_data, output_path, app_config, project_root_path, icon_cache_path=None):
    global image_canvas, draw_context
    
    if not weather_data or not weather_data.has_sufficient_data():
        return None

    image_width = app_config.get('display_width', 600)
    image_height = app_config.get('display_height', 448)
    
    image_canvas = Image.new("RGB", (image_width, image_height), "white")
    draw_context = ImageDraw.Draw(image_canvas)

    if os.name == 'nt':
        font_path="arial.ttf"; bold_font_path="arialbd.ttf"
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
    except IOError:
        fonts['heading'] = ImageFont.load_default()
        fonts['temp'] = ImageFont.load_default()
        fonts['regular'] = ImageFont.load_default()
        fonts['small'] = ImageFont.load_default()
        graph_base_font_size = 10

    colors = {'bg': (255, 255, 255), 'text': (50, 50, 50), 'blue': (0, 0, 200), 'green': (0, 180, 0), 'orange': (255, 140, 0), 'grey': (100, 100, 100)}
    draw_context.rectangle(((0, 0), (image_width, image_height)), fill=colors['bg'])

    # --- Current Weather ---
    current_weather_width = int(image_width * 0.25)
    current_temp_text = weather_data.current.get('temp_display', '?°')
    temp_x = 25; temp_y = 10
    draw_context.text((temp_x, temp_y), current_temp_text, font=fonts['temp'], fill=colors['text'])

    # Draw Current Icon
    display_icon_provider_pref = app_config.get("icon_provider_display", "openweathermap").lower()
    icon_configs_all = app_config.get('icon_configs', DEFAULT_ICON_DISPLAY_CONFIGS)
    current_icon_display_map = icon_configs_all.get('current_display', DEFAULT_ICON_DISPLAY_CONFIGS['current_display'])
    current_icon_props = current_icon_display_map.get(display_icon_provider_pref, current_icon_display_map['default'])
    
    owm_icon_code_current = weather_data.current.get('weather_icon')
    if owm_icon_code_current and owm_icon_code_current != 'na':
        icon_path = download_and_cache_icon(owm_icon_code_current, display_icon_provider_pref, project_root_path, icon_cache_dir=icon_cache_path)
        if icon_path:
            try:
                target_size = (current_icon_props['width'], current_icon_props['height'])
                paste_pos = (temp_x + current_icon_props['x_offset'], temp_y + current_icon_props['y_offset'])
                icon_img = _load_image_from_path(icon_path)
                if icon_img:
                    icon_img_resized = icon_img.resize(target_size, resample=LANCZOS_FILTER)
                    image_canvas.paste(icon_img_resized, paste_pos, mask=icon_img_resized)
            except Exception: pass

    # Draw Current Details
    details_y = 135; details_x = 20; line_height = 25
    default_current_details = ['feels_like', 'humidity', 'wind_speed', 'aqi']
    details_to_show_config = app_config.get('current_weather_display_details', default_current_details)
    current_detail_map = {
        "feels_like": f"Feel  : {weather_data.current.get('feels_like_display', '?°')}",
        "humidity":   f"Hum.: {weather_data.current.get('humidity_display', '?%')}",
        "wind_speed": f"Wind: {weather_data.current.get('wind_speed_display', '? m/s')}",
        "aqi":        f"AQI:  {weather_data.current.get('aqi_display', ' ?')}"
    }
    for i, k in enumerate(details_to_show_config):
        if k in current_detail_map:
            draw_context.text((details_x, details_y + i * line_height), current_detail_map[k], font=fonts['regular'], fill=colors['text'])

    # --- Hourly Graph ---
    hourly_forecast_x = current_weather_width
    hourly_forecast_y = 0
    hourly_forecast_height = int(image_height * 0.55) 
    hourly_forecast_width = image_width - current_weather_width - 15
    
    graph_specific_config = app_config.get("graph_24h_forecast_config")
    graph_icon_provider_pref = app_config.get("icon_provider_graph", "openweathermap").lower()

    create_24h_forecast_section(
        weather_data.hourly, graph_specific_config,
        hourly_forecast_x, hourly_forecast_y, hourly_forecast_width, hourly_forecast_height,
        font_path, graph_base_font_size,
        project_root_path, graph_icon_provider_pref, app_config,
        icon_cache_path=icon_cache_path
    ) 

    # --- Daily Forecast ---
    create_daily_forecast_display(
        weather_data.daily, weather_data.temperature_unit, 
        project_root_path, display_icon_provider_pref, app_config,
        fonts, colors, icon_cache_path=icon_cache_path
    )

    try:
        image_canvas.save(output_path)
        return image_canvas
    except Exception as e:
        print(f"Error saving image: {e}")
        return None