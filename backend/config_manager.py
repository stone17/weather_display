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
        # 1. Load Base
        if os.path.exists(self.base_path):
            try:
                with open(self.base_path, 'r') as f:
                    base = yaml.safe_load(f)
                    if base: self.data.update(base)
            except Exception: pass
        
        # 2. Load Local (Overrides)
        if os.path.exists(self.local_path):
            try:
                with open(self.local_path, 'r') as f:
                    local = yaml.safe_load(f)
                    if local: self.data.update(local)
            except Exception: pass
            
        # --- MIGRATION: Fix legacy plural 'wind_gusts' ---
        graph_cfg = self.data.get('graph_24h_forecast_config', {})
        series = graph_cfg.get('series', [])
        changed = False
        for s in series:
            if s.get('parameter') == 'wind_gusts':
                s['parameter'] = 'wind_gust'
                if s.get('legend_label') == 'Gusts': s['legend_label'] = 'Gust'
                changed = True
        
        if changed:
            logger.info("Migrated legacy 'wind_gusts' to 'wind_gust' in memory.")

    def update_from_form(self, form_data: dict):
        # 1. Sanitize Inputs
        clean_data = {}
        for k, v in form_data.items():
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                 clean_data[k] = v
        form_data = clean_data

        # 2. Hardware Profile
        hw = form_data.get('hardware_profile', 'generic')
        if hw in ["spectra_e6", "waveshare_73"]:
            form_data['display_width'] = 800; form_data['display_height'] = 480
        elif hw == "waveshare_565":
            form_data['display_width'] = 600; form_data['display_height'] = 448
            
        # 3. Coordinate Normalization
        for coord in ['latitude', 'longitude']:
            val = form_data.get(coord)
            if val is not None and str(val).strip() != "":
                try: form_data[coord] = float(val)
                except ValueError: form_data.pop(coord, None)
            else:
                form_data.pop(coord, None)

        # --- Supplemental Providers Logic ---
        supp_providers = []
        
        # 1. Open-Meteo
        if form_data.get('supp_om_enabled'):
            params = []
            if form_data.get('supp_om_p_uvi'): params.append('uvi')
            if form_data.get('supp_om_p_rain'): params.append('rain')
            # Save even if params is empty, so toggle stays on
            supp_providers.append({'provider_name': 'open-meteo', 'parameters': params})
        
        # 2. AQICN
        if form_data.get('supp_aqi_enabled'):
            params = []
            if form_data.get('supp_aqi_p_aqi'): params.append('aqi')
            if form_data.get('supp_aqi_p_pm25'): params.append('aqi_pm25_avg')
            # Save even if params is empty
            supp_providers.append({'provider_name': 'AQICN', 'parameters': params})
                
        form_data['supplemental_providers'] = supp_providers
        
        # Cleanup temp UI keys
        for k in ['supp_om_enabled', 'supp_om_p_uvi', 'supp_om_p_rain', 
                  'supp_aqi_enabled', 'supp_aqi_p_aqi', 'supp_aqi_p_pm25']:
            form_data.pop(k, None)

        # --- Daily Forecast Colors ---
        daily_colors = self.data.get('daily_forecast_colors', {})
        if form_data.get('daily_color_text'): daily_colors['text'] = form_data.get('daily_color_text')
        if form_data.get('daily_color_rain'): daily_colors['blue'] = form_data.get('daily_color_rain')
        if form_data.get('daily_color_wind'): daily_colors['green'] = form_data.get('daily_color_wind')
        if form_data.get('daily_color_uvi'): daily_colors['orange'] = form_data.get('daily_color_uvi')
        form_data['daily_forecast_colors'] = daily_colors
        
        for k in ['daily_color_text', 'daily_color_rain', 'daily_color_wind', 'daily_color_uvi']:
            form_data.pop(k, None)

        # 4. Graph Series Parsing
        current_graph_cfg = self.data.get('graph_24h_forecast_config', {})
        existing_series_list = current_graph_cfg.get('series', [])
        
        graph_hours = form_data.pop('graph_time_range_hours', 24)
        supported_params = ['temp', 'feels_like', 'rain', 'wind_speed', 'wind_gust', 'humidity', 'pressure']
        new_series_config = []
        
        for param in supported_params:
            if form_data.get(f"series_{param}_enabled"):
                existing_conf = next((s for s in existing_series_list if s.get('parameter') == param), None)
                
                if existing_conf:
                    template = existing_conf.copy()
                else:
                    template = GRAPH_SERIES_DEFAULTS.get(param, {}).copy()
                    template['parameter'] = param 

                # Basic
                if form_data.get(f"series_{param}_color"): template['color'] = form_data.get(f"series_{param}_color")
                if form_data.get(f"series_{param}_style"): template['line_style'] = form_data.get(f"series_{param}_style")
                try: template['linewidth'] = float(form_data.get(f"series_{param}_width", template.get('linewidth', 2.0)))
                except: pass

                # Text / Legend
                lbl = form_data.get(f"series_{param}_legend_label")
                if lbl is not None: template['legend_label'] = lbl
                
                unit = form_data.get(f"series_{param}_unit")
                if unit is not None: template['unit'] = unit

                # Checkbox presence determines state
                template['show_peak_in_legend'] = bool(form_data.get(f"series_{param}_peak"))

                # Advanced Styling (Dual Color, Alpha, Z)
                if form_data.get(f"series_{param}_dual_color_enabled"):
                    neg_col = form_data.get(f"series_{param}_color_neg")
                    if neg_col: template['color_negative'] = neg_col
                else:
                    template.pop('color_negative', None)

                try: template['zorder'] = float(form_data.get(f"series_{param}_zorder", template.get('zorder', 2.0)))
                except: pass
                try: template['alpha'] = float(form_data.get(f"series_{param}_alpha", template.get('alpha', 0.3)))
                except: pass

                # Axis
                axis_raw = form_data.get(f"series_{param}_axis", "left")
                if "_hidden" in axis_raw:
                    template['axis'] = axis_raw.replace("_hidden", "")
                    template['show_y_axis_tick_labels'] = False
                    template['axis_label'] = ""
                else:
                    template['axis'] = axis_raw
                    template['show_y_axis_tick_labels'] = True
                    
                # Scaling & Occupancy
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
                else:
                    template['scale_type'] = "auto_padded"

                # Fill Logic
                fill_mode = form_data.get(f"series_{param}_fill", "none")
                if template.get('plot_type') in ['fill_between', 'fill_between_two_series']:
                    template.pop('plot_type', None)
                template.pop('fill_to_zero', None)

                if fill_mode == "fill_to_zero":
                    template['plot_type'] = 'fill_between'
                    if 'alpha' not in template: template['alpha'] = 0.3
                elif fill_mode == "fill_from_wind":
                    template['plot_type'] = 'fill_between_two_series'
                    template['series1_param_name'] = 'wind_speed'
                    template['series2_param_name'] = 'wind_gust'
                    template['zorder'] = 1.5 
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

        # 5. Global Config Updates
        current_graph_cfg['graph_time_range_hours'] = int(graph_hours)
        current_graph_cfg['series'] = new_series_config
        
        # Grid & Axis
        current_graph_cfg['show_y_grid_left'] = form_data.get('show_y_grid_left') == 'true'
        current_graph_cfg['show_y_grid_right'] = form_data.get('show_y_grid_right') == 'true'
        current_graph_cfg['show_x_grid'] = form_data.get('show_x_grid', 'true') == 'true'
        
        # Fonts
        try: current_graph_cfg['base_font_size'] = int(form_data.get('base_font_size', 10))
        except: pass
        current_graph_cfg['x_axis_tick_font_weight'] = form_data.get('x_axis_tick_font_weight', 'normal')
        current_graph_cfg['y_axis_tick_font_weight'] = form_data.get('y_axis_tick_font_weight', 'normal')
        
        # X-Axis
        try: current_graph_cfg['x_axis_hour_interval'] = int(form_data.get('x_axis_hour_interval', 6))
        except: pass
        current_graph_cfg['x_axis_time_format'] = form_data.get('x_axis_time_format', '%H:%M')
        try: current_graph_cfg['x_axis_tick_rotation'] = int(form_data.get('x_axis_tick_rotation', 0))
        except: pass
        
        # Legend
        leg_cfg = current_graph_cfg.get('legend', {})
        std_leg = leg_cfg.get('standard_legend', {})
        std_leg['position'] = form_data.get('legend_position', 'best')
        try: std_leg['columns'] = int(form_data.get('legend_columns', 2))
        except: pass
        leg_cfg['standard_legend'] = std_leg
        current_graph_cfg['legend'] = leg_cfg
        
        # Peak Legend (Restored)
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

        # Wind Arrows
        if form_data.get('wa_enabled'):
             current_graph_cfg['wind_arrows'] = {
                 'enabled': True, 
                 'color': form_data.get('wa_color', '#000000'), 
                 'size': int(form_data.get('wa_size', 10)), 
                 'parameter_speed': 'wind_speed', 
                 'parameter_degrees': 'wind_deg'
             }
        else: current_graph_cfg['wind_arrows'] = {'enabled': False}
        
        # Day/Night
        if form_data.get('dn_enabled'):
            current_graph_cfg['day_night_highlight'] = {
                'enabled': True, 
                'color': form_data.get('dn_color', '#D3D3D3'), 
                'alpha': float(form_data.get('dn_alpha', 0.3)), 
                'mode': 'civil_twilight'
            }
        else: current_graph_cfg['day_night_highlight'] = {'enabled': False}

        keys_to_clean = [
            'wa_enabled', 'wa_color', 'wa_size', 'dn_enabled', 'dn_color', 'dn_alpha', 
            'base_font_size', 'show_y_grid_left', 'show_y_grid_right', 'show_x_grid',
            'x_axis_hour_interval', 'x_axis_time_format', 'x_axis_tick_rotation',
            'x_axis_tick_font_weight', 'y_axis_tick_font_weight',
            'legend_position', 'legend_columns',
            'peak_leg_enabled', 'peak_leg_location', 'peak_leg_align', 'peak_leg_anchor_y', 'peak_leg_box'
        ]
        for k in keys_to_clean: form_data.pop(k, None)
            
        form_data['graph_24h_forecast_config'] = current_graph_cfg

        clean_updates = {k: v for k, v in form_data.items() if v is not None}
        self.save_local(clean_updates)

    def save_local(self, updates):
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