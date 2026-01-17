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
from fastapi.staticfiles import StaticFiles
import paho.mqtt.client as mqtt_client

# --- PATH SETUP ---
# Get the absolute path of the 'app' directory
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Get the Project Root (one level up from app)
PROJECT_ROOT = os.path.dirname(APP_DIR)

# Add Project Root to sys.path so we can import create_weather_info
import sys
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from create_weather_info import generate_weather

# --- CONFIG & LOGGING ---
# Config is expected in the Project Root
CONFIG_FILE = os.getenv("CONFIG_PATH", os.path.join(PROJECT_ROOT, "config.yaml"))
IMAGE_PATH = os.path.join(PROJECT_ROOT, "weather_forecast_graph.png")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("WeatherDocker")

# --- CONFIG MANAGER ---
class ConfigManager:
    def __init__(self, base_filepath):
        self.base_filepath = base_filepath
        # Determine local config path (e.g., config.local.yaml)
        base_dir = os.path.dirname(base_filepath)
        filename = os.path.basename(base_filepath)
        name, ext = os.path.splitext(filename)
        self.local_filepath = os.path.join(base_dir, f"{name}.local{ext}")
        
        self.data = {}
        self.load()

    def load(self):
        """Loads base config and merges local config on top."""
        self.data = {}
        
        # 1. Load Base Config
        if os.path.exists(self.base_filepath):
            try:
                with open(self.base_filepath, 'r') as f:
                    base_data = yaml.safe_load(f)
                    if base_data: self.data.update(base_data)
            except Exception as e:
                logger.error(f"Base Config Load Error: {e}")

        # 2. Merge Local Config (overrides base)
        if os.path.exists(self.local_filepath):
            try:
                with open(self.local_filepath, 'r') as f:
                    local_data = yaml.safe_load(f)
                    if local_data: self.data.update(local_data)
            except Exception as e:
                logger.error(f"Local Config Load Error: {e}")

    def save_local(self, updates: dict):
        """Reads existing local config, updates specific fields, and writes back."""
        try:
            current_local = {}
            if os.path.exists(self.local_filepath):
                with open(self.local_filepath, 'r') as f:
                    current_local = yaml.safe_load(f) or {}
            
            # Apply updates
            current_local.update(updates)
            
            with open(self.local_filepath, 'w') as f:
                yaml.dump(current_local, f, sort_keys=False)
            
            logger.info(f"Saved updates to {self.local_filepath}")
            
            # Reload to refresh runtime data
            self.load()
        except Exception as e:
            logger.error(f"Config Save Error: {e}")

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
            logger.warning("MQTT Broker not configured.")
            return

        try:
            user = cfg.data.get('mqtt_user')
            passwd = cfg.data.get('mqtt_password')
            if user and passwd:
                self.client.username_pw_set(user, passwd)
            
            port = cfg.data.get('mqtt_port', 1883)
            logger.info(f"Connecting to MQTT {broker}:{port}")
            self.client.connect(broker, port, 60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"MQTT Start Error: {e}")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info("MQTT Connected.")
            client.subscribe("weather_display/update")
            self.publish_discovery(client)
        else:
            logger.error(f"MQTT Connection failed code {rc}")

    def publish_discovery(self, client):
        discovery_topic = "homeassistant/button/weather_display/update/config"
        payload = {
            "name": "Refresh Weather Display",
            "unique_id": "weather_display_refresh_btn",
            "command_topic": "weather_display/update",
            "payload_press": "TRIGGER",
            "icon": "mdi:weather-cloudy-clock",
            "device": {
                "identifiers": ["weather_display_docker"],
                "name": "Weather Display Service",
                "manufacturer": "Docker Container",
                "model": "v1.0"
            }
        }
        client.publish(discovery_topic, json.dumps(payload), retain=True)

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        if topic == "weather_display/update":
            logger.info("Received MQTT update trigger.")
            asyncio.run_coroutine_threadsafe(trigger_weather_update(), loop)

mqtt_handler = MqttHandler()

# --- BACKGROUND TASK ---
async def trigger_weather_update():
    logger.info("Starting weather generation...")
    success, msg = await generate_weather(CONFIG_FILE)
    if success:
        logger.info("Weather generation successful.")
    else:
        logger.error(f"Weather generation failed: {msg}")

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
# Ensure templates are found correctly relative to APP_DIR
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    cfg.load()
    
    # Calculate Last Update String
    last_update_str = "Never"
    if os.path.exists(IMAGE_PATH):
        try:
            mtime = os.path.getmtime(IMAGE_PATH)
            # Use %X for locale's appropriate time representation, or explicit format
            last_update_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logger.error(f"Error reading image time: {e}")
            last_update_str = "Error"

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "config": cfg.data,
        "providers": cfg.data.get('provider_list', []),
        "last_update": last_update_str
    })

@app.get("/image")
async def get_image():
    if os.path.exists(IMAGE_PATH):
        return FileResponse(IMAGE_PATH, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return HTMLResponse("Image not generated yet.", status_code=404)

@app.post("/update_settings")
async def update_settings(
    mqtt_broker: str = Form(""), 
    mqtt_port: int = Form(1883),
    mqtt_user: str = Form(""),
    mqtt_password: str = Form(""),
    server_ip: str = Form(""), 
    weather_provider: str = Form(...)
):
    updates = {
        'mqtt_broker': mqtt_broker,
        'mqtt_port': int(mqtt_port),
        'mqtt_user': mqtt_user,
        'mqtt_password': mqtt_password,
        'server_ip': server_ip,
        'weather_provider': weather_provider
    }
    
    cfg.save_local(updates)
    
    mqtt_handler.stop()
    mqtt_handler.start()
    
    return RedirectResponse(url="/", status_code=303)

@app.post("/trigger_now")
async def trigger_now():
    await trigger_weather_update()
    return RedirectResponse(url="/", status_code=303)