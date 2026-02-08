#include <WiFi.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <SPI.h>
#include <GxEPD2_BW.h>
#include <GxEPD2_7C.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ==========================================
// ===       USER CONFIGURATION           ===
// ==========================================

// --- POWER MODE ---
// 1 = DC (Always On, MQTT Active)
// 2 = Battery (Deep Sleep, No MQTT)
#define MODE_DC      1
#define MODE_BATTERY 2

#define POWER_MODE   MODE_DC 

// --- DC MODE SETTINGS ---
const bool AUTO_FETCH_ENABLED = true; 

// --- SAFETY TIMERS ---
const unsigned long UPDATE_INTERVAL_MS = 3600000;  // 1 Hour
const unsigned long EMERGENCY_CLEAR_MS = 86400000; // 24 Hours
const unsigned long FAILURE_RETRY_MS   = 3600000;  // 1 Hour

// --- WIFI ---
const char* WIFI_SSID     = "YOUR_SSID";
const char* WIFI_PASSWORD = "YOUR_PWD";

// --- MQTT ---
const char* MQTT_SERVER     = "SERVER_IP"; 
const int   MQTT_PORT       = 1883;
const char* MQTT_USER       = ""; 
const char* MQTT_PASS       = "";

// Device ID for Home Assistant
const char* DEVICE_NAME     = "Weather Display reTerminal 1002";
const char* DEVICE_ID       = "esp32_weather_disp_reterminal_1002"; // Must be unique, no spaces

// --- TOPICS ---
const char* TOPIC_STATUS    = "weather_display/status";
const char* TOPIC_CONTROL   = "weather_display/control"; 
const char* HA_DISCOVERY_PREFIX = "homeassistant"; 

// --- DISPLAY & STORAGE ---
String currentImageUrl      = "IMAGE_URL"; 
const char* CACHE_FILENAME  = "/current.bmp";

// ==========================================
// ===        HARDWARE SETUP              ===
// ==========================================
#define EPD_SCK_PIN  7
#define EPD_MOSI_PIN 9
#define EPD_CS_PIN   10
#define EPD_DC_PIN   11
#define EPD_RES_PIN  12
#define EPD_BUSY_PIN 13
#define SPI_MISO_PIN 8 

// Verify this is the correct driver for your ReTerminal/Spectra E6
// (Often GxEPD2_565c for the 5.65" ACeP, but keeping your setting)
#define GxEPD2_DISPLAY_CLASS GxEPD2_7C
#define GxEPD2_DRIVER_CLASS GxEPD2_730c_GDEP073E01
#define MAX_DISPLAY_BUFFER_SIZE 16000
#define MAX_HEIGHT(EPD) (EPD::HEIGHT <= MAX_DISPLAY_BUFFER_SIZE / (EPD::WIDTH / 8) ? EPD::HEIGHT : MAX_DISPLAY_BUFFER_SIZE / (EPD::WIDTH / 8))

SPIClass hspi(HSPI);
GxEPD2_DISPLAY_CLASS<GxEPD2_DRIVER_CLASS, MAX_HEIGHT(GxEPD2_DRIVER_CLASS)>
    display(GxEPD2_DRIVER_CLASS(/*CS=*/EPD_CS_PIN, /*DC=*/EPD_DC_PIN, /*RST=*/EPD_RES_PIN, /*BUSY=*/EPD_BUSY_PIN));

WiFiClient espClient;
PubSubClient mqtt(espClient);

// Global State
unsigned long lastSuccessfulUpdate = 0; 
unsigned long lastAttemptTime      = 0;
unsigned long lastMqttRetry        = 0;
unsigned long lastWifiRetry        = 0;
bool forceUpdateRequested          = false;
bool inFailureMode                 = false;
String lastStatus                  = "Booting";

// ==========================================
// ===     EUCLIDEAN COLOR MAPPING        ===
// ==========================================
// Standard ACeP 7-Color Palette
const uint8_t REF_PALETTE[7][3] = {
  {0, 0, 0},       // Black
  {255, 255, 255}, // White
  {0, 255, 0},     // Green
  {0, 0, 255},     // Blue
  {255, 0, 0},     // Red
  {255, 255, 0},   // Yellow
  {255, 128, 0}    // Orange
};

const uint16_t EPAPER_CONSTANTS[7] = {
  GxEPD_BLACK, GxEPD_WHITE, GxEPD_GREEN, GxEPD_BLUE, 
  GxEPD_RED,   GxEPD_YELLOW, GxEPD_ORANGE
};

// Robust color finder using Euclidean Distance
uint16_t findNearestColor(uint8_t r, uint8_t g, uint8_t b) {
  long min_dist_sq = -1;
  int best_color_index = 0;
  for (int i = 0; i < 7; i++) {
    long dr = r - REF_PALETTE[i][0];
    long dg = g - REF_PALETTE[i][1];
    long db = b - REF_PALETTE[i][2];
    long dist_sq = dr*dr + dg*dg + db*db;
    
    if (min_dist_sq == -1 || dist_sq < min_dist_sq) {
      min_dist_sq = dist_sq;
      best_color_index = i;
    }
  }
  return EPAPER_CONSTANTS[best_color_index];
}

// ==========================================
// ===        HELPER FUNCTIONS            ===
// ==========================================
uint16_t read16(File &f) { uint16_t r; f.read((uint8_t *)&r, 2); return r; }
uint32_t read32(File &f) { uint32_t r; f.read((uint8_t *)&r, 4); return r; }

// Failure Screen (Built-in Font)
void drawFailureScreen() {
    display.init(115200);
    display.setRotation(0);
    display.firstPage();
    do {
        display.fillScreen(GxEPD_WHITE);
        display.setTextColor(GxEPD_RED);
        display.setCursor(10, 50);
        display.print("REFRESH FAILURE");
        display.setTextColor(GxEPD_BLACK);
        display.setCursor(10, 80);
        display.print("No data received for > 24h");
        display.setCursor(10, 110);
        display.print("Last Success: ");
        display.print((millis() - lastSuccessfulUpdate) / 3600000);
        display.print(" hours ago");
    } while (display.nextPage());
    display.hibernate();
}

bool downloadImage(const char* url) {
    if (WiFi.status() != WL_CONNECTED) return false;
    Serial.printf("[HTTP] Downloading %s\n", url);
    HTTPClient http;
    http.setTimeout(20000); 
    http.begin(url);
    int code = http.GET();
    if (code == HTTP_CODE_OK) {
        if (LittleFS.exists(CACHE_FILENAME)) LittleFS.remove(CACHE_FILENAME);
        File f = LittleFS.open(CACHE_FILENAME, "w");
        if (!f) return false;
        http.writeToStream(&f);
        f.close();
        http.end();
        Serial.println("[HTTP] Success");
        return true;
    }
    Serial.printf("[HTTP] Failed Code: %d\n", code);
    http.end();
    return false;
}

// === STRICT ROW-BY-ROW BMP DRAWER ===
void drawBmpStream(const char *filename) {
    File bmpFile = LittleFS.open(filename, "r");
    if (!bmpFile) { Serial.println("[BMP] Open Failed"); return; }

    if (read16(bmpFile) != 0x4D42) { Serial.println("[BMP] Bad Sig"); bmpFile.close(); return; }
    read32(bmpFile); read32(bmpFile); 
    uint32_t bmpImageoffset = read32(bmpFile);
    read32(bmpFile); 
    int32_t bmpWidth = read32(bmpFile);
    int32_t bmpHeight = read32(bmpFile);
    read16(bmpFile); 
    uint16_t bmpDepth = read16(bmpFile);

    // Row padding to 4 bytes
    uint32_t rowSize = (bmpWidth * bmpDepth / 8 + 3) & ~3;
    uint8_t* sdbuffer = (uint8_t*)malloc(rowSize);
    if (!sdbuffer) { Serial.println("[BMP] RAM Fail"); bmpFile.close(); return; }

    bool flip = true;
    if (bmpHeight < 0) { bmpHeight = -bmpHeight; flip = false; }

    // Read Palette (8-bit) - Converts BGR file data to RGB internal
    uint8_t filePalette[256][3];
    if (bmpDepth == 8) {
        bmpFile.seek(54);
        for (int i=0; i<256; i++) {
            filePalette[i][2] = bmpFile.read(); // Blue
            filePalette[i][1] = bmpFile.read(); // Green
            filePalette[i][0] = bmpFile.read(); // Red
            bmpFile.read(); // Reserved
        }
    }

    display.init(115200);
    display.setRotation(0);
    display.firstPage();
    do {
        for (int16_t row = 0; row < bmpHeight; row++) {
            // Strict seek logic (from user snippet)
            uint32_t rowpos = flip ? (bmpImageoffset + (bmpHeight - 1 - row) * rowSize) : (bmpImageoffset + row * rowSize);
            bmpFile.seek(rowpos);
            bmpFile.read(sdbuffer, rowSize);

            for (int16_t col = 0; col < bmpWidth; col++) {
                uint8_t r, g, b;
                
                if (bmpDepth == 24) {
                    // BMP is BGR
                    b = sdbuffer[col * 3];
                    g = sdbuffer[col * 3 + 1];
                    r = sdbuffer[col * 3 + 2];
                } 
                else if (bmpDepth == 8) {
                    uint8_t idx = sdbuffer[col];
                    r = filePalette[idx][0];
                    g = filePalette[idx][1];
                    b = filePalette[idx][2];
                }

                // Map using Euclidean Distance (Robust)
                uint16_t color = findNearestColor(r, g, b);
                display.drawPixel(col, row, color);
            }
        }
    } while (display.nextPage());

    free(sdbuffer);
    bmpFile.close();
    display.hibernate(); 
}

// ==========================================
// ===           MQTT & HA LOGIC          ===
// ==========================================

void publishStatus() {
    if (!mqtt.connected()) return;
    StaticJsonDocument<512> doc;
    doc["ip"] = WiFi.localIP().toString();
    doc["rssi"] = WiFi.RSSI();
    doc["status"] = lastStatus;
    doc["last_success_sec"] = (millis() - lastSuccessfulUpdate) / 1000;
    doc["failure_mode"] = inFailureMode ? "YES" : "NO";

    char buffer[512];
    serializeJson(doc, buffer);
    mqtt.publish(TOPIC_STATUS, buffer, true); 
}

void sendDiscovery() {
    if (!mqtt.connected()) return;
    Serial.println("[MQTT] Sending HA Discovery...");

    StaticJsonDocument<600> doc;
    char buffer[1024];
    String baseTopic = String("homeassistant/sensor/") + DEVICE_ID;

    // --- Helper to add Device Info (Must be called for EACH msg) ---
    auto addDeviceInfo = [&](JsonDocument& d) {
        JsonObject dev = d.createNestedObject("dev");
        dev["ids"] = DEVICE_ID;
        dev["name"] = DEVICE_NAME;
        dev["mdl"] = "ESP32-S3 ePaper";
        dev["mf"] = "Custom";
    };

    // 1. Status Sensor
    doc.clear();
    doc["name"] = "Status";
    doc["uniq_id"] = String(DEVICE_ID) + "_status";
    doc["stat_t"] = TOPIC_STATUS;
    doc["val_tpl"] = "{{ value_json.status }}";
    doc["ic"] = "mdi:monitor-dashboard";
    addDeviceInfo(doc); // <--- Re-add device info fresh
    
    serializeJson(doc, buffer);
    mqtt.publish((baseTopic + "/status/config").c_str(), buffer, true);

    // 2. RSSI Sensor
    doc.clear();
    doc["name"] = "WiFi Signal";
    doc["uniq_id"] = String(DEVICE_ID) + "_rssi";
    doc["stat_t"] = TOPIC_STATUS;
    doc["val_tpl"] = "{{ value_json.rssi }}";
    doc["unit_of_meas"] = "dBm";
    doc["dev_cla"] = "signal_strength";
    doc["ic"] = "mdi:wifi";
    addDeviceInfo(doc); // <--- Re-add device info fresh

    serializeJson(doc, buffer);
    mqtt.publish((baseTopic + "/rssi/config").c_str(), buffer, true);

    // 3. IP Address Sensor (To match your logs)
    doc.clear();
    doc["name"] = "IP Address";
    doc["uniq_id"] = String(DEVICE_ID) + "_ip";
    doc["stat_t"] = TOPIC_STATUS;
    doc["val_tpl"] = "{{ value_json.ip }}";
    doc["ic"] = "mdi:ip-network";
    addDeviceInfo(doc); // <--- Re-add device info fresh

    serializeJson(doc, buffer);
    mqtt.publish((baseTopic + "/ip/config").c_str(), buffer, true);

    // 4. Force Update Button
    doc.clear();
    doc["name"] = "Force Refresh";
    doc["uniq_id"] = String(DEVICE_ID) + "_refresh";
    doc["cmd_t"] = TOPIC_CONTROL;
    doc["pl_prs"] = "{\"command\":\"update\"}";
    doc["ic"] = "mdi:refresh";
    addDeviceInfo(doc); // <--- Re-add device info fresh
    
    String btnTopic = String("homeassistant/button/") + DEVICE_ID + "/refresh/config";
    serializeJson(doc, buffer);
    mqtt.publish(btnTopic.c_str(), buffer, true);
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, payload, length);
    if (!error) {
        const char* cmd = doc["command"];
        if (cmd && strcmp(cmd, "update") == 0) {
            Serial.println("[MQTT] Force Update Command");
            if (doc.containsKey("url")) currentImageUrl = doc["url"].as<String>();
            forceUpdateRequested = true;
        }
    }
}

void reconnectMqtt() {
    unsigned long now = millis();
    if (lastMqttRetry > 0 && (now - lastMqttRetry < 10000)) return;
    
    Serial.print("[MQTT] Connecting... ");
    if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS)) {
        Serial.println("Connected");
        mqtt.subscribe(TOPIC_CONTROL);
        sendDiscovery();
        publishStatus();
        lastMqttRetry = 0; 
    } else {
        Serial.println("Failed");
        lastMqttRetry = now; 
    }
}

// ==========================================
// ===           MAIN LOGIC               ===
// ==========================================

void performUpdate() {
    Serial.println("[SYS] Updating...");
    lastStatus = "Downloading";
    publishStatus();

    if (downloadImage(currentImageUrl.c_str())) {
        lastStatus = "Drawing";
        publishStatus();
        drawBmpStream(CACHE_FILENAME);
        lastStatus = "Idle";
        Serial.println("[SYS] Success");
        lastSuccessfulUpdate = millis();
        inFailureMode = false;
    } else {
        lastStatus = "Download Failed";
        Serial.println("[SYS] Download Failed");
    }
    
    lastAttemptTime = millis();
    publishStatus();
}

void setup() {
    // 1. USB Serial Init (Wait for Monitor)
    Serial.begin(115200);
    unsigned long s = millis();
    while(!Serial && (millis()-s < 3000)) delay(10);
    
    Serial.println("\n--- WEATHER DISPLAY BOOT ---");
    
    hspi.begin(EPD_SCK_PIN, SPI_MISO_PIN, EPD_MOSI_PIN, -1);
    LittleFS.begin(true);
    display.epd2.selectSPI(hspi, SPISettings(4000000, MSBFIRST, SPI_MODE0));
    display.init(115200);

    // 2. WiFi
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED) {
        delay(500); Serial.print(".");
        if (++attempts > 40) {
            if (POWER_MODE == MODE_BATTERY) {
                Serial.println("Fail -> Sleep");
                ESP.deepSleep(UPDATE_INTERVAL_MS * 1000ULL);
            }
            break;
        }
    }
    Serial.println("\n[WiFi] Connected");

    // 3. Modes
    if (POWER_MODE == MODE_BATTERY) {
        if (downloadImage(currentImageUrl.c_str())) drawBmpStream(CACHE_FILENAME);
        ESP.deepSleep(UPDATE_INTERVAL_MS * 1000ULL);
    }

    if (POWER_MODE == MODE_DC) {
        mqtt.setServer(MQTT_SERVER, MQTT_PORT);
        mqtt.setCallback(mqttCallback);
        mqtt.setBufferSize(2048); 
        
        lastSuccessfulUpdate = millis(); 
        if (AUTO_FETCH_ENABLED) forceUpdateRequested = true;
    }
}

void loop() {
    unsigned long now = millis();

    // 1. Connection Maintenance
    if (WiFi.status() != WL_CONNECTED) {
        if (now - lastWifiRetry > 30000) {
            WiFi.disconnect(); WiFi.reconnect();
            lastWifiRetry = now;
        }
        return; 
    }

    if (!mqtt.connected()) reconnectMqtt();
    else mqtt.loop();

    // 2. Failure Watchdog
    if (!inFailureMode && (now - lastSuccessfulUpdate > EMERGENCY_CLEAR_MS)) {
        Serial.println("[SYS] CRITICAL: 24h No Data -> Clear Screen");
        inFailureMode = true;
        drawFailureScreen();
        lastAttemptTime = now;
    }

    // 3. Triggers
    bool timeForAutoUpdate = AUTO_FETCH_ENABLED && (now - lastAttemptTime > UPDATE_INTERVAL_MS);
    bool timeForRetry      = inFailureMode && (now - lastAttemptTime > FAILURE_RETRY_MS);

    if (forceUpdateRequested || timeForAutoUpdate || timeForRetry) {
        performUpdate();
        forceUpdateRequested = false;
    }
}