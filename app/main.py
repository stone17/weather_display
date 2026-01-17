import asyncio
import os
import json
import logging
import yaml
import shutil
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
import paho.mqtt.client as mqtt_client

# --- PATH SETUP ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

# Add backend to sys.path to find modules
import sys
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from create_weather_info import generate_weather

# --- CONFIG & LOGGING ---
# Paths are now relative to the mapped volumes
CONFIG_FILE = os.getenv("CONFIG_PATH", os.path.join(PROJECT_ROOT, "config", "config.yaml"))
CACHE_DIR = os.path.join(PROJECT_ROOT, "cache")
IMAGE_PATH = os.path.join(CACHE_DIR, "weather_forecast_graph.png")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("WeatherDocker")

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
        # 1. Base Config
        if os.path.exists(self.base_filepath):
            try:
                with open(self.base_filepath, 'r') as f:
                    base = yaml.safe_load(f)
                    if base: self.data.update(base)
            except Exception as e:
                logger.error(f"Base Config Error: {e}")

        # 2. Local Config
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
            current.update(updates)
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
        if not broker: return
        try:
            user = cfg.data.get('mqtt_user')
            pwd = cfg.data.get('mqtt_password')
            if user and pwd: self.client.username_pw_set(user, pwd)
            self.client.connect(broker, int(cfg.data.get('mqtt_port', 1883)), 60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"MQTT Start Error: {e}")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT Connected")
            client.subscribe("weather_display/update")
            self.publish_discovery(client)
        else: logger.error(f"MQTT Fail: {rc}")

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
        client.publish(topic, json.dumps(payload), retain=True)

    def on_message(self, client, userdata, msg):
        if msg.topic == "weather_display/update":
            logger.info("MQTT Trigger Received")
            asyncio.run_coroutine_threadsafe(trigger_weather_update(), loop)

mqtt_handler = MqttHandler()

# --- BACKGROUND TASK ---
async def trigger_weather_update():
    logger.info("Starting weather generation...")
    # Pass path to config.yaml; script will resolve local config automatically
    success, msg = await generate_weather(CONFIG_FILE)
    if success: logger.info("Generation Success")
    else: logger.error(f"Generation Failed: {msg}")

# --- LIFECYCLE ---
from contextlib import asynccontextmanager
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
    cfg.load()
    last_upd = "Never"
    if os.path.exists(IMAGE_PATH):
        last_upd = datetime.fromtimestamp(os.path.getmtime(IMAGE_PATH)).strftime('%Y-%m-%d %H:%M:%S')
    
    return templates.TemplateResponse("index.html", {
        "request": request, "config": cfg.data, 
        "providers": cfg.data.get('provider_list', []), "last_update": last_upd
    })

@app.get("/image")
async def get_image():
    if os.path.exists(IMAGE_PATH):
        return FileResponse(IMAGE_PATH, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return HTMLResponse("Image not generated yet.", status_code=404)

@app.post("/update_settings")
async def update_settings(
    mqtt_broker: str = Form(""), mqtt_port: int = Form(1883),
    mqtt_user: str = Form(""), mqtt_password: str = Form(""),
    server_ip: str = Form(""), weather_provider: str = Form(...)
):
    cfg.save_local({
        'mqtt_broker': mqtt_broker, 'mqtt_port': mqtt_port,
        'mqtt_user': mqtt_user, 'mqtt_password': mqtt_password,
        'server_ip': server_ip, 'weather_provider': weather_provider
    })
    mqtt_handler.stop()
    mqtt_handler.start()
    return RedirectResponse("/", status_code=303)

@app.post("/trigger_now")
async def trigger_now():
    await trigger_weather_update()
    return RedirectResponse("/", status_code=303)