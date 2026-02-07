import os
import yaml
import logging
from weather_graph_defaults import GRAPH_SERIES_DEFAULTS

logger = logging.getLogger("ConfigManager")

class ConfigManager:
    def __init__(self, config_path):
        self.base_path = config_path
        base_dir = os.path.dirname(config_path)
        filename = os.path.basename(config_path)
        name, ext = os.path.splitext(filename)
        self.local_path = os.path.join(base_dir, f"{name}.local{ext}")
        self.data = {}
        self.reload()

    def reload(self):
        self.data = {}
        if os.path.exists(self.base_path):
            try:
                with open(self.base_path, 'r') as f:
                    base = yaml.safe_load(f)
                    if base: self.data.update(base)
            except Exception: pass
        
        if os.path.exists(self.local_path):
            try:
                with open(self.local_path, 'r') as f:
                    local = yaml.safe_load(f)
                    if local: self.data.update(local)
            except Exception: pass
            
        # Migration
        graph_cfg = self.data.get('graph_24h_forecast_config', {})
        series = graph_cfg.get('series', [])
        changed = False
        for s in series:
            if s.get('parameter') == 'wind_gusts':
                s['parameter'] = 'wind_gust'
                if s.get('legend_label') == 'Gusts': s['legend_label'] = 'Gust'
                changed = True
        if changed: logger.info("Migrated legacy 'wind_gusts'.")

    def update_from_form(self, form_data: dict):
        clean_data = {}
        for k, v in form_data.items():
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                 clean_data[k] = v
        form_data = clean_data

        hw = form_data.get('hardware_profile', 'generic')
        if hw in ["spectra_e6", "waveshare_73"]:
            form_data['display_width'] = 800; form_data['display_height'] = 480
        elif hw == "waveshare_565":
            form_data['display_width'] = 600; form_data['display_height'] = 448
            
        for coord in ['latitude', 'longitude']:
            val = form_data.get(coord)
            if val is not None and str(val).strip() != "":
                try: form_data[coord] = float(val)
                except ValueError: form_data.pop(coord, None)
            else: form_data.pop(coord, None)

        current_graph_cfg = self.data.get('graph_24h_forecast_config', {})
        existing_series_list = current_graph_cfg.get('series', [])
        
        graph_hours = form_data.pop('graph_time_range_hours', 24)
        supported_params = ['temp', 'feels_like', 'rain', 'wind_speed', 'wind_gust', 'humidity', 'pressure']
        new_series_config = []
        extra_fill_series = [] # Store separated fill entries here
        
        for param in supported_params:
            if form_data.get(f"series_{param}_enabled"):
                existing_conf = next((s for s in existing_series_list if s.get('parameter') == param), None)
                template = existing_conf.copy() if existing_conf else GRAPH_SERIES_DEFAULTS.get(param, {}).copy()
                template['parameter'] = param 

                if form_data.get(f"series_{param}_color"): template['color'] = form_data.get(f"series_{param}_color")
                if form_data.get(f"series_{param}_style"): template['line_style'] = form_data.get(f"series_{param}_style")
                try: template['linewidth'] = float(form_data.get(f"series_{param}_width", template.get('linewidth', 2.0)))
                except: pass

                lbl = form_data.get(f"series_{param}_legend_label")
                if lbl is not None: template['legend_label'] = lbl
                
                unit = form_data.get(f"series_{param}_unit")
                if unit is not None: template['unit'] = unit

                template['show_peak_in_legend'] = bool(form_data.get(f"series_{param}_peak"))

                if form_data.get(f"series_{param}_dual_color_enabled"):
                    neg_col = form_data.get(f"series_{param}_color_neg")
                    if neg_col: template['color_negative'] = neg_col
                else: template.pop('color_negative', None)

                try: template['zorder'] = float(form_data.get(f"series_{param}_zorder", template.get('zorder', 2.0)))
                except: pass
                try: template['alpha'] = float(form_data.get(f"series_{param}_alpha", template.get('alpha', 0.3)))
                except: pass

                axis_raw = form_data.get(f"series_{param}_axis", "left")
                if "_hidden" in axis_raw:
                    template['axis'] = axis_raw.replace("_hidden", "")
                    template['show_y_axis_tick_labels'] = False
                    template['axis_label'] = ""
                else:
                    template['axis'] = axis_raw
                    template['show_y_axis_tick_labels'] = True
                    
                try: template['data_occupancy_factor'] = float(form_data.get(f"series_{param}_occupancy", 0.8))
                except: pass

                if form_data.get(f"series_{param}_scale_mode") == "manual":
                    template['scale_type'] = "manual_range"
                    try:
                        vmin = form_data.get(f"series_{param}_min")
                        vmax = form_data.get(f"series_{param}_max")
                        if vmin not in [None, ""]: template['y_axis_min'] = float(vmin)
                        if vmax not in [None, ""]: template['y_axis_max'] = float(vmax)
                    except: pass
                else: template['scale_type'] = "auto_padded"

                fill_mode = form_data.get(f"series_{param}_fill", "none")
                
                # Cleanup potential old plot_type on the line series
                if template.get('plot_type') in ['fill_between', 'fill_between_two_series']: 
                    template.pop('plot_type', None)
                template.pop('fill_to_zero', None)

                if fill_mode == "fill_to_zero":
                    template['plot_type'] = 'fill_between'
                    if 'alpha' not in template: template['alpha'] = 0.3
                elif fill_mode == "fill_from_wind":
                    # CORRECT FIX: Keep the line series as-is, create a SEPARATE fill entry
                    template['plot_type'] = 'line' # Force current series to line
                    
                    # Try to preserve existing fill color/alpha if it existed
                    existing_fill = next((s for s in existing_series_list 
                                          if s.get('plot_type') == 'fill_between_two_series' 
                                          and s.get('series2_param_name') == 'wind_gust'), {})
                    
                    fill_entry = {
                        'plot_type': 'fill_between_two_series',
                        'series1_param_name': 'wind_speed',
                        'series2_param_name': 'wind_gust',
                        'color': existing_fill.get('color', 'lightgreen'),
                        'alpha': existing_fill.get('alpha', 0.4),
                        'zorder': 1.8
                    }
                    extra_fill_series.append(fill_entry)
                else: 
                    template['plot_type'] = 'line'
                
                # Weather Symbols
                sym_en = form_data.get(f"series_{param}_sym_enabled")
                if sym_en or form_data.get(f"series_{param}_sym_size"):
                    if 'weather_symbols' not in template: template['weather_symbols'] = {}
                    template['weather_symbols']['enabled'] = bool(sym_en)
                    try: template['weather_symbols']['icon_size_pixels'] = int(form_data.get(f"series_{param}_sym_size", 20))
                    except: pass
                    try: template['weather_symbols']['vertical_offset_pixels'] = int(form_data.get(f"series_{param}_sym_offset", 10))
                    except: pass
                    try: template['weather_symbols']['time_interval_hours'] = int(form_data.get(f"series_{param}_sym_interval", 4))
                    except: pass

                new_series_config.append(template)
            
            keys_to_remove = [k for k in form_data.keys() if k.startswith(f"series_{param}_")]
            for k in keys_to_remove: form_data.pop(k, None)

        current_graph_cfg['graph_time_range_hours'] = int(graph_hours)
        # Combine standard series with the separated fill entries
        current_graph_cfg['series'] = new_series_config + extra_fill_series
        
        current_graph_cfg['show_y_grid_left'] = form_data.get('show_y_grid_left') == 'true'
        current_graph_cfg['show_y_grid_right'] = form_data.get('show_y_grid_right') == 'true'
        current_graph_cfg['show_x_grid'] = form_data.get('show_x_grid', 'true') == 'true'
        
        try: current_graph_cfg['base_font_size'] = int(form_data.get('base_font_size', 10))
        except: pass
        
        try: current_graph_cfg['x_axis_hour_interval'] = int(form_data.get('x_axis_hour_interval', 6))
        except: pass
        current_graph_cfg['x_axis_time_format'] = form_data.get('x_axis_time_format', '%H:%M')
        try: current_graph_cfg['x_axis_tick_rotation'] = int(form_data.get('x_axis_tick_rotation', 0))
        except: pass
        
        # Legend Config
        leg_cfg = current_graph_cfg.get('legend', {})
        std_leg = leg_cfg.get('standard_legend', {})
        std_leg['enabled'] = bool(form_data.get('std_leg_enabled'))
        std_leg['position'] = form_data.get('legend_position', 'best')
        std_leg['frame_on'] = bool(form_data.get('std_leg_frame'))
        try: std_leg['columns'] = int(form_data.get('legend_columns', 2))
        except: pass
        leg_cfg['standard_legend'] = std_leg
        
        pk_leg = leg_cfg.get('peak_value_display', {})
        pk_leg['enabled'] = bool(form_data.get('peak_leg_enabled'))
        pk_leg['location'] = form_data.get('peak_leg_location', 'in_graph')
        pk_leg['horizontal_alignment'] = form_data.get('peak_leg_align', 'right')
        try: pk_leg['axis_start_anchor_y'] = float(form_data.get('peak_leg_anchor_y', 0.97))
        except: pass
        
        bbox = pk_leg.get('text_bbox', {})
        bbox['enabled'] = bool(form_data.get('peak_leg_box'))
        pk_leg['text_bbox'] = bbox
        leg_cfg['peak_value_display'] = pk_leg
        current_graph_cfg['legend'] = leg_cfg

        # Wind Arrows / DayNight
        current_graph_cfg['wind_arrows'] = {'enabled': bool(form_data.get('wa_enabled')), 'color': form_data.get('wa_color', '#000000'), 'size': int(form_data.get('wa_size', 10)), 'parameter_speed': 'wind_speed', 'parameter_degrees': 'wind_deg'}
        current_graph_cfg['day_night_highlight'] = {'enabled': bool(form_data.get('dn_enabled')), 'color': form_data.get('dn_color', '#D3D3D3'), 'alpha': float(form_data.get('dn_alpha', 0.3)), 'mode': 'civil_twilight'}

        keys_to_clean = [
            'wa_enabled', 'wa_color', 'wa_size', 'dn_enabled', 'dn_color', 'dn_alpha', 
            'base_font_size', 'show_y_grid_left', 'show_y_grid_right', 'show_x_grid',
            'x_axis_hour_interval', 'x_axis_time_format', 'x_axis_tick_rotation',
            'legend_position', 'legend_columns', 'std_leg_enabled', 'std_leg_frame',
            'peak_leg_enabled', 'peak_leg_location', 'peak_leg_align', 'peak_leg_anchor_y', 'peak_leg_box'
        ]
        for k in keys_to_clean: form_data.pop(k, None)
            
        form_data['graph_24h_forecast_config'] = current_graph_cfg
        clean_updates = {k: v for k, v in form_data.items() if v is not None}
        self._save_to_local(clean_updates)

    def _save_to_local(self, updates):
        try:
            current = {}
            if os.path.exists(self.local_path):
                try:
                    with open(self.local_path, 'r') as f: current = yaml.safe_load(f) or {}
                except: current = {}
            current.update(updates)
            
            if 'lat' in current: current.pop('lat')
            if 'lon' in current: current.pop('lon')

            with open(self.local_path, 'w') as f: yaml.dump(current, f, sort_keys=False)
            self.reload()
        except Exception as e: logger.error(f"Config Save Error: {e}")