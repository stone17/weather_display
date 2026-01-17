# backend/create_weather_info.py
import argparse
import json
import traceback
from IPy import IP
import asyncio
import sys
import os
import yaml

# --- PATH SETUP ---
# backend_dir is where this script lives
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# root_dir is one level up (where config/ and cache/ live)
root_dir = os.path.dirname(backend_dir)
config_dir = os.path.join(root_dir, "config")
cache_dir = os.path.join(root_dir, "cache")

# Import logic from backend
import upload
from weather_provider_base import get_weather_provider
from weather_data_parser import WeatherData
from image_generator import generate_weather_image

async def generate_weather(config_path_arg=None):
    # 1. Path Resolution
    if not config_path_arg:
        config_path = os.path.join(config_dir, "config.yaml")
    else:
        config_path = config_path_arg

    # Local config is sibling to config.yaml
    base_cfg_dir = os.path.dirname(config_path)
    local_config_path = os.path.join(base_cfg_dir, "config.local.yaml")
    
    # 2. Load Config
    config = load_configuration(config_path, local_config_path)
    if not config: return False, "Config failed"

    # 3. Define Outputs
    # Image output
    output_image_path = os.path.join(cache_dir, "weather_forecast_graph.png")
    
    # NEW: Define Icon Cache Path (inside cache folder)
    icon_cache_path = os.path.join(cache_dir, "icon_cache")
    if not os.path.exists(icon_cache_path):
        os.makedirs(icon_cache_path)

    # 4. Fetch Data
    # NOTE: We pass backend_dir as project_root so providers can find 'images' folder for icons
    raw_data = await fetch_weather_data(config, backend_dir) 
    if not raw_data: return False, "Fetch failed"
    cur, hr, day = raw_data

    # 5. Generate Image
    wdata = prepare_weather_data(cur, hr, day, config.get("temperature_unit", "C"), config.get('graph_24h_forecast_config', {}))
    
    # NEW: Pass icon_cache_path explicitly
    img = generate_weather_image(wdata, output_image_path, config, backend_dir, icon_cache_path=icon_cache_path)
    if img is None: return False, "Image Gen failed"

    # 6. Upload (Legacy)
    try: process_and_upload_image(img, config)
    except Exception as e: print(f"Upload warning: {e}")

    return True, "Success"

async def main():
    default_cfg = os.path.join(config_dir, "config.yaml")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", dest="config_path", default=default_cfg)
    args = parser.parse_args()
    
    success, msg = await generate_weather(args.config_path)
    if success: print(msg)
    else: 
        print(f"Error: {msg}")
        exit(1)

# --- Helpers ---
def load_configuration(base, local):
    cfg = {}
    try:
        with open(base, 'r') as f: cfg.update(yaml.safe_load(f) or {})
    except Exception as e: print(f"Base Config Error: {e}")
    
    if os.path.exists(local):
        try:
            with open(local, 'r') as f: cfg.update(yaml.safe_load(f) or {})
        except Exception as e: print(f"Local Config Error: {e}")
    return cfg

async def fetch_weather_data(cfg, root):
    prov = get_weather_provider(cfg, root)
    if not prov: return None
    if not await prov.fetch_data() and not prov.get_all_data(): return None
    return prov.get_current_data(), prov.get_hourly_data(), prov.get_daily_data()

def prepare_weather_data(c, h, d, u, g=None):
    return WeatherData(c, h, d, u, graph_config=g)

def process_and_upload_image(img, cfg):
    sip = cfg.get("server_ip")
    if not sip: 
        print("Skipping upload (No IP).")
        return
    try: IP(sip)
    except: 
        print("Skipping upload (Invalid IP).")
        return

    print(f"Uploading to {sip}...")
    data, w, h = upload.process_image(img)
    if data: upload.upload_processed_data(data, w, h, sip, upload.DEFAULT_UPLOAD_URL)

if __name__ == "__main__":
    asyncio.run(main())