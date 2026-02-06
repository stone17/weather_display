import asyncio
import os
import json
import logging
import yaml
import shutil
import aiohttp
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
from io import BytesIO

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import paho.mqtt.client as mqtt_client
from PIL import Image

# --- PATH SETUP ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

import sys
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from create_weather_info import generate_weather
from dither import DitherProcessor

# --- CONFIG & LOGGING ---
CONFIG_FILE = os.getenv("CONFIG_PATH", os.path.join(PROJECT_ROOT, "config", "config.yaml"))
CACHE_DIR = os.path.join(PROJECT_ROOT, "cache")
IMG_SOURCE_PATH = os.path.join(CACHE_DIR, "latest_source.png")
IMG_DITHERED_PATH = os.path.join(CACHE_DIR, "latest_dithered.png")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("WeatherDocker")

flash_message = None

# --- CONFIG MANAGER ---
class ConfigManager:
    def __init__(self, base_filepath):
        self.base_filepath = base_filepath
        base_dir = os.path.dirname(base_filepath)
        filename = os.path.basename(base_filepath)
        name, ext = os.path.splitext(filename)
        self.local_filepath = os.path.join(base_dir, f"{name}.local{ext}")
        self.data = {}
        self.load()

    def load(self):
        self.data = {}
        if os.path.exists(self.base_filepath):
            try:
                with open(self.base_filepath, 'r') as f:
                    base = yaml.safe_load(f)
                    if base: self.data.update(base)
            except Exception as e:
                logger.error(f"Base Config Error: {e}")

        if os.path.exists(self.local_filepath):
            try:
                with open(self.local_filepath, 'r') as f:
                    local = yaml.safe_load(f)
                    if local: self.data.update(local)
            except Exception as e:
                logger.error(f"Local Config Error: {e}")

    def save_local(self, updates):
        try:
            current = {}
            if os.path.exists(self.local_filepath):
                with open(self.local_filepath, 'r') as f:
                    current = yaml.safe_load(f) or {}
            
            clean_updates = {k: v for k, v in updates.items() if v is not None and v != ""}
            current.update(clean_updates)
            
            with open(self.local_filepath, 'w') as f:
                yaml.dump(current, f, sort_keys=False)
            self.load()
        except Exception as e:
            logger.error(f"Save Error: {e}")

cfg = ConfigManager(CONFIG_FILE)

# --- MQTT HANDLER ---
class MqttHandler:
    def __init__(self):
        self.client = mqtt_client.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.connected = False

    def start(self):
        broker = cfg.data.get('mqtt_broker')
        if not broker: 
            return
        try:
            user = cfg.data.get('mqtt_user')
            pwd = cfg.data.get('mqtt_password')
            if user and pwd: 
                self.client.username_pw_set(user, pwd)
            port = int(cfg.data.get('mqtt_port', 1883))
            self.client.connect(broker, port, 60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"MQTT Connection Failed: {e}")
            self.connected = False

    def stop(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False
        except Exception: pass

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe("weather_display/update")
            self.publish_discovery(client)
        else: 
            self.connected = False

    def publish_discovery(self, client):
        topic = "homeassistant/button/weather_display/update/config"
        payload = {
            "name": "Refresh Weather Display",
            "unique_id": "weather_display_refresh_btn",
            "command_topic": "weather_display/update",
            "payload_press": "TRIGGER",
            "icon": "mdi:weather-cloudy-clock",
            "device": {"identifiers": ["weather_display_docker"], "name": "Weather Display", "manufacturer": "Docker"}
        }
        try:
            client.publish(topic, json.dumps(payload), retain=True)
        except Exception: pass

    def on_message(self, client, userdata, msg):
        if msg.topic == "weather_display/update":
            asyncio.run_coroutine_threadsafe(trigger_weather_update(), loop)

mqtt_handler = MqttHandler()

# --- HELPER: GEOCODING ---
async def search_cities_interactive(city_name):
    """
    Returns (results_list, error_message).
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city_name, "count": 10, "language": "en", "format": "json"}
    # Identify ourselves to the API to avoid generic blocking
    headers = {"User-Agent": "WeatherDisplayDocker/1.0 (internal tool)"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Open-Meteo returns {'results': [...]} or just {} if nothing found
                    return data.get("results", []), None 
                else:
                    text = await resp.text()
                    return [], f"API Error {resp.status}: {text}"
        except aiohttp.ClientError as e:
            logger.error(f"Geocoding network error: {e}")
            return [], f"Network Error: {str(e)}"
        except Exception as e:
            logger.error(f"Geocoding unexpected error: {e}")
            return [], f"Error: {str(e)}"

async def get_lat_lon_from_city(city_name):
    """Legacy helper: returns the first match only."""
    results, error = await search_cities_interactive(city_name)
    if results:
        res = results[0]
        full_name = f"{res.get('name')}, {res.get('country')}"
        return full_name, res["latitude"], res["longitude"]
    return None, None, None

# --- BACKGROUND TASK ---
async def trigger_weather_update():
    global flash_message
    logger.info("Starting weather generation...")
    success, msg = await generate_weather(CONFIG_FILE)
    if success: 
        logger.info("Generation Success")
        flash_message = {"type": "success", "text": "Weather updated successfully."}
    else: 
        logger.error(f"Generation Failed: {msg}")
        flash_message = {"type": "danger", "text": f"Generation Failed: {msg}"}

# --- LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    loop = asyncio.get_running_loop()
    mqtt_handler.start()
    yield
    mqtt_handler.stop()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    global flash_message
    cfg.load()
    last_upd = "Never"
    if os.path.exists(IMG_DITHERED_PATH):
        last_upd = datetime.fromtimestamp(os.path.getmtime(IMG_DITHERED_PATH)).strftime('%Y-%m-%d %H:%M:%S')
    
    msg = flash_message
    flash_message = None

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "config": cfg.data, 
        "providers": ["smhi", "owm", "openmeteo", "meteomatics", "google", "aqicn"], 
        "last_update": last_upd,
        "mqtt_status": mqtt_handler.connected,
        "message": msg
    })

@app.get("/image/source")
async def get_source_image():
    if os.path.exists(IMG_SOURCE_PATH):
        return FileResponse(IMG_SOURCE_PATH, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return HTMLResponse("No source image", status_code=404)

@app.get("/image/dithered")
async def get_dithered_image():
    if os.path.exists(IMG_DITHERED_PATH):
        return FileResponse(IMG_DITHERED_PATH, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return HTMLResponse("No dithered image", status_code=404)

@app.post("/lookup_city")
async def lookup_city(city_name: str = Form(...)):
    """Interactive endpoint for the frontend modal."""
    results, error = await search_cities_interactive(city_name)
    
    if error:
        # Return success=False so frontend can show the specific error
        return JSONResponse({"success": False, "error": error})
        
    return JSONResponse({"success": True, "results": results})

@app.post("/apply_dither")
async def apply_dither(method: str = Form(...)):
    if not os.path.exists(IMG_SOURCE_PATH):
        return JSONResponse({"success": False, "error": "No source image found."})
    try:
        img = Image.open(IMG_SOURCE_PATH).convert("RGB")
        ditherer = DitherProcessor()
        result = ditherer.process(img, method)
        result.save(IMG_DITHERED_PATH)
        cfg.save_local({'dithering_method': method})
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/update_settings")
async def update_settings(
    mqtt_broker: str = Form(""), mqtt_port: int = Form(1883),
    mqtt_user: str = Form(""), mqtt_password: str = Form(""),
    server_ip: str = Form(""), weather_provider: str = Form(...),
    city_name: str = Form(""), lat: str = Form(""), lon: str = Form(""),
    hardware_profile: str = Form(...), dithering_method: str = Form("floyd_steinberg")
):
    global flash_message

    width, height = 600, 448
    if hardware_profile == "spectra_e6" or hardware_profile == "waveshare_73":
        width, height = 800, 480

    updates = {
        'mqtt_broker': mqtt_broker, 'mqtt_port': mqtt_port,
        'mqtt_user': mqtt_user, 'mqtt_password': mqtt_password,
        'server_ip': server_ip, 'weather_provider': weather_provider,
        'hardware_profile': hardware_profile,
        'dithering_method': dithering_method,
        'display_width': width,
        'display_height': height,
        'lat': float(lat) if lat else None,
        'lon': float(lon) if lon else None,
    }

    status_text = "Settings saved."

    # SMART LOOKUP LOGIC:
    if city_name:
        if not lat or not lon:
            resolved_name, new_lat, new_lon = await get_lat_lon_from_city(city_name)
            if resolved_name:
                updates['lat'] = new_lat
                updates['lon'] = new_lon
                status_text = f"Auto-resolved '{city_name}' to {new_lat}, {new_lon}."
            else:
                status_text = f"Could not find city '{city_name}'."
        else:
            status_text = "Settings saved (using provided coordinates)."

    cfg.save_local(updates)
    mqtt_handler.stop()
    mqtt_handler.start()
    
    flash_message = {"type": "info", "text": status_text}
    return RedirectResponse("/", status_code=303)

@app.post("/trigger_now")
async def trigger_now():
    await trigger_weather_update()
    return RedirectResponse("/", status_code=303)