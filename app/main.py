import asyncio
import os
import json
import logging
import shutil
import aiohttp
from typing import Optional, List
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import paho.mqtt.client as mqtt_client
from PIL import Image

# --- PATH SETUP & DEBUGGING ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
PHOTOS_DIR = os.path.join(PROJECT_ROOT, "photos")
CACHE_DIR = os.path.join(PROJECT_ROOT, "cache")
IMG_SOURCE_PATH = os.path.join(CACHE_DIR, "latest_source.png")

# Create dirs if missing
if not os.path.exists(PHOTOS_DIR): os.makedirs(PHOTOS_DIR)
if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)

import sys
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

# --- IMPORTS ---
from create_weather_info import WeatherService
from dither import DitherProcessor
from display_manager import DisplayOrchestrator
from config_manager import ConfigManager

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("WeatherDocker")

flash_message = None
CONFIG_FILE = os.getenv("CONFIG_PATH", os.path.join(PROJECT_ROOT, "config", "config.yaml"))
cfg = ConfigManager(CONFIG_FILE)

# --- HELPER: PATH RESOLUTION ---
def get_current_dithered_path():
    """Checks for BMP first (ESP preferred), then PNG."""
    bmp_path = os.path.join(CACHE_DIR, "latest_dithered.bmp")
    if os.path.exists(bmp_path): 
        return bmp_path
    
    png_path = os.path.join(CACHE_DIR, "latest_dithered.png")
    if os.path.exists(png_path): 
        return png_path
    
    return None

# --- SERVICES ---
class UpdateScheduler:
    def __init__(self): self.task = None
    def restart(self):
        self.stop()
        try:
            interval = int(cfg.data.get('update_interval_minutes', 0))
            if interval > 0: 
                logger.info(f"Scheduler: Auto-update every {interval} min.")
                self.task = asyncio.create_task(self._loop(interval))
        except ValueError: pass
    def stop(self):
        if self.task: self.task.cancel(); self.task = None
    async def _loop(self, interval):
        try:
            while True:
                await asyncio.sleep(interval * 60)
                await trigger_weather_update()
        except asyncio.CancelledError: pass

scheduler = UpdateScheduler()

class MqttHandler:
    def __init__(self):
        self.client = mqtt_client.Client()
        self.client.on_connect = self.on_connect; self.client.on_message = self.on_message
        self.connected = False
    def start(self):
        if not cfg.data.get('enable_mqtt', False): return
        try:
            user = cfg.data.get('mqtt_user'); pwd = cfg.data.get('mqtt_password')
            if user and pwd: self.client.username_pw_set(user, pwd)
            self.client.connect(cfg.data.get('mqtt_broker'), int(cfg.data.get('mqtt_port', 1883)), 60)
            self.client.loop_start()
        except: self.connected = False
    def stop(self):
        try: self.client.loop_stop(); self.client.disconnect(); self.connected = False
        except: pass
    def on_connect(self, c, u, f, rc):
        if rc == 0: self.connected = True; c.subscribe("weather_display/update")
        else: self.connected = False
    def on_message(self, c, u, m): asyncio.run_coroutine_threadsafe(trigger_weather_update(), loop)

mqtt_handler = MqttHandler()

async def search_cities_interactive(city_name):
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city_name, "count": 10, "language": "en", "format": "json"}
    headers = {"User-Agent": "WeatherDisplayDocker/1.0"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200: return (await resp.json()).get("results", []), None
                return [], f"API Error {resp.status}"
        except Exception as e: return [], str(e)

async def get_lat_lon_from_city(city_name):
    res, err = await search_cities_interactive(city_name)
    if res: return f"{res[0]['name']}", res[0]['latitude'], res[0]['longitude']
    return None, None, None

async def trigger_weather_update():
    global flash_message
    logger.info("Triggering Display Orchestrator...")
    orchestrator = DisplayOrchestrator(cfg.data, PROJECT_ROOT)
    success, msg = await orchestrator.update_display()
    if success: 
        flash_message = {"type": "success", "text": "Display updated successfully."}
    else: 
        logger.error(f"Update Failed: {msg}")
        flash_message = {"type": "danger", "text": f"Update Failed: {msg}"}

# --- LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    loop = asyncio.get_running_loop()
    
    # --- DEBUG: PRINT PATHS ON STARTUP ---
    print("--- PATH DIAGNOSTICS ---")
    print(f"App Directory:    {APP_DIR}")
    print(f"Project Root:     {PROJECT_ROOT}")
    print(f"Cache Directory:  {CACHE_DIR}")
    print(f"Config File:      {CONFIG_FILE}")
    print(f"Source Image Exp: {IMG_SOURCE_PATH}")
    print("------------------------")
    
    mqtt_handler.start()
    scheduler.restart()
    yield
    scheduler.stop()
    mqtt_handler.stop()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    global flash_message
    cfg.reload()
    last_upd = "Never"
    
    dpath = get_current_dithered_path()
    if dpath:
        # datetime is now available
        last_upd = datetime.fromtimestamp(os.path.getmtime(dpath)).strftime('%Y-%m-%d %H:%M:%S')
    
    msg = flash_message
    flash_message = None
    
    photos = []
    if os.path.exists(PHOTOS_DIR):
        photos = [f for f in os.listdir(PHOTOS_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))]

    g_conf = cfg.data.get('graph_24h_forecast_config', {})
    active_series = [s.get('parameter') for s in g_conf.get('series', [])] if g_conf else []

    return templates.TemplateResponse("index.html", {
        "request": request, "config": cfg.data, 
        "providers": ["smhi", "owm", "openmeteo", "meteomatics", "google", "aqicn"], 
        "last_update": last_upd, "mqtt_status": mqtt_handler.connected, "message": msg,
        "photos": photos, "active_graph_series": active_series
    })

@app.get("/image")
async def get_image():
    """Serves the final dithered image for the ESP."""
    path = get_current_dithered_path()
    if path:
        return FileResponse(path, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache", "Expires": "0"
        })
    return HTMLResponse("No image generated.", status_code=404)

@app.get("/image/source")
async def get_source_image():
    """Serves raw RGB source for preview."""
    if os.path.exists(IMG_SOURCE_PATH):
        return FileResponse(IMG_SOURCE_PATH, headers={"Cache-Control": "no-cache"})
    
    logger.warning(f"404 Source Image. Checked: {IMG_SOURCE_PATH}")
    return HTMLResponse("No source image", status_code=404)

@app.get("/image/dithered")
async def get_dithered_image():
    """Serves dithered image for preview."""
    path = get_current_dithered_path()
    if path: 
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    
    logger.warning(f"404 Dithered Image. Checked dir: {CACHE_DIR}")
    return HTMLResponse("No dithered image", status_code=404)

@app.post("/trigger_now")
async def trigger_now():
    await trigger_weather_update()
    return RedirectResponse("/", status_code=303)

@app.post("/apply_dither")
async def apply_dither(method: str = Form(...)):
    if not os.path.exists(IMG_SOURCE_PATH): 
        return JSONResponse({"success": False, "error": "No source image found."})
    try:
        img = Image.open(IMG_SOURCE_PATH).convert("RGB")
        ditherer = DitherProcessor()
        result = ditherer.process(img, method)
        
        fmt = cfg.data.get("output_format", "png")
        
        # Cleanup
        for f in ["latest_dithered.png", "latest_dithered.bmp"]:
            p = os.path.join(CACHE_DIR, f)
            if os.path.exists(p): os.remove(p)

        if fmt == "bmp8":
            result.save(os.path.join(CACHE_DIR, "latest_dithered.bmp"))
        elif fmt == "bmp24":
            result.convert("RGB").save(os.path.join(CACHE_DIR, "latest_dithered.bmp"))
        else:
            result.save(os.path.join(CACHE_DIR, "latest_dithered.png"))

        cfg.save_local({'dithering_method': method})
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/upload_photos")
async def upload_photos(files: List[UploadFile] = File(...)):
    global flash_message
    saved_count = 0
    for file in files:
        if file.filename:
            file_path = os.path.join(PHOTOS_DIR, file.filename)
            try:
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                saved_count += 1
            except Exception as e:
                logger.error(f"Error saving {file.filename}: {e}")
    
    flash_message = {"type": "success", "text": f"Uploaded {saved_count} photos."}
    return RedirectResponse("/", status_code=303)

@app.post("/delete_photo")
async def delete_photo(filename: str = Form(...)):
    global flash_message
    path = os.path.join(PHOTOS_DIR, filename)
    if os.path.commonpath([path, PHOTOS_DIR]) == PHOTOS_DIR and os.path.exists(path):
        os.remove(path)
        flash_message = {"type": "info", "text": f"Deleted {filename}."}
    else:
        flash_message = {"type": "danger", "text": "File not found or invalid path."}
    return RedirectResponse("/", status_code=303)

@app.post("/display_photo")
async def display_specific_photo(filename: str = Form(...)):
    global flash_message
    logger.info(f"Manual trigger: Displaying specific photo {filename}")
    
    orchestrator = DisplayOrchestrator(cfg.data, PROJECT_ROOT)
    success, msg = await orchestrator.update_display(specific_photo=filename)
    
    if success:
        flash_message = {"type": "success", "text": f"Displaying {filename}"}
    else:
        flash_message = {"type": "danger", "text": f"Error: {msg}"}
        
    return RedirectResponse("/", status_code=303)

@app.post("/lookup_city")
async def lookup_city(city_name: str = Form(...)):
    results, error = await search_cities_interactive(city_name)
    if error: return JSONResponse({"success": False, "error": error})
    return JSONResponse({"success": True, "results": results})

@app.post("/update_settings")
async def update_settings(
    request: Request,
    enable_mqtt: bool = Form(False), enable_server_push: bool = Form(False),
    current_details: List[str] = Form([]), daily_details: List[str] = Form([]),
    graph_series: List[str] = Form([])
):
    global flash_message
    form_data = await request.form()
    
    # CRITICAL FIX: SANITIZE FORM DATA
    data_dict = {
        k: v for k, v in form_data.items() 
        if not isinstance(v, UploadFile)
    }
    
    data_dict['enable_mqtt'] = enable_mqtt
    data_dict['enable_server_push'] = enable_server_push
    data_dict['current_weather_display_details'] = current_details
    data_dict['daily_forecast_display_details'] = daily_details
    data_dict['graph_series'] = graph_series

    # Auto-City Lookup
    city_name = data_dict.get('city_name')
    # Standardized on latitude/longitude
    lat = data_dict.get('latitude'); lon = data_dict.get('longitude')
    
    status_text = "Settings Saved."
    if city_name and (not lat or not lon):
        res_name, n_lat, n_lon = await get_lat_lon_from_city(city_name)
        if res_name:
            data_dict['latitude'] = n_lat; data_dict['longitude'] = n_lon
            status_text = f"Saved. Auto-resolved: {res_name}"

    # Save
    cfg.update_from_form(data_dict)
    
    mqtt_handler.stop(); mqtt_handler.start()
    scheduler.restart()
    
    if request.headers.get("X-Auto-Save") == "true":
        return JSONResponse({"success": True, "message": status_text})

    flash_message = {"type": "info", "text": status_text}
    return RedirectResponse("/", status_code=303)