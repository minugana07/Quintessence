// ============================================================================
// ESP32 Complete 4-Sensor Lake Water Quality Monitor
// Team Quintessence - RV College of Engineering
// Displays: Temperature (°C), TDS (ppm), Turbidity (NTU), pH, WQI & Status
//
// Wiring Summary (Karthe CSE Hardware Setup):
//   - TDS Sensor       -> Pin D34 (Powered by 3V3, direct signal)
//   - Turbidity Sensor -> Pin D35 (Powered by VIN 5V, R1 10kΩ + R2 22kΩ divider)
//   - pH Sensor        -> Pin D32 (Powered by VIN 5V, R3 10kΩ + R4 22kΩ divider)
//   - DS18B20 Temp     -> Pin D18 (Powered by 3V3, R5 4.7kΩ pull-up to 3V3)
// ============================================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// --- 1. PIN DEFINITIONS ---
#define TDS_PIN        34
#define TURBIDITY_PIN  35
#define PH_PIN         32
#define TEMP_PIN       18
#define LED_PIN        2    // Onboard status LED

// --- 2. ADC & VOLTAGE DIVIDER CONSTANTS ---
const float VREF               = 3.3;
const float R_TOP              = 10000.0;  // R1 and R3 (10kΩ)
const float R_BOTTOM           = 22000.0;  // R2 and R4 (22kΩ)

const float TDS_DIVIDER_RATIO  = 1.0;                            // Direct connection (3V3)
const float TURB_DIVIDER_RATIO = (R_TOP + R_BOTTOM) / R_BOTTOM;  // 1.4545
const float PH_DIVIDER_RATIO   = (R_TOP + R_BOTTOM) / R_BOTTOM;  // 1.4545

// --- 3. CALIBRATION SETTINGS ---
float tdsKValue        = 1.00;  // TDS probe calibration multiplier
float turbClearVoltage = 4.15;  // Clear air / clean water baseline = 0 NTU
float phNeutralVoltage = 2.50;  // PH-4502C 'Po' voltage in pH 7.0 water
float phSlope          = 0.18;  // Volts per pH unit (~0.18V for PH-4502C)

// --- 4. WIFI & DASHBOARD SERVER CONFIG ---
const char* WIFI_SSID     = "YOUR_WIFI_OR_HOTSPOT";  // Replace with your Hotspot Name
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";    // Replace with your Hotspot Password
const char* SERVER_URL    = "http://192.168.1.100:8000/api/telemetry"; // Put your laptop IPv4 here!
const char* BUOY_ID       = "buoy1";                 // Quintessence Buoy #1

// --- 5. FILTERING & TIMING ---
#define SAMPLE_COUNT     30
#define SAMPLE_INTERVAL  40     // Read analog sensors every 40 ms
#define PRINT_INTERVAL   2000   // Print and send readings every 2 seconds

int tdsBuffer[SAMPLE_COUNT];
int turbBuffer[SAMPLE_COUNT];
int phBuffer[SAMPLE_COUNT];
int bufferIndex = 0;

unsigned long lastSampleTime = 0;
unsigned long lastPrintTime  = 0;

OneWire oneWire(TEMP_PIN);
DallasTemperature tempSensor(&oneWire);

// Median filter to strip electrical spikes from analog readings
int getMedian(int data[], int length) {
  int sorted[SAMPLE_COUNT];
  for (int i = 0; i < length; i++) {
    sorted[i] = data[i];
  }
  for (int i = 0; i < length - 1; i++) {
    for (int j = 0; j < length - i - 1; j++) {
      if (sorted[j] > sorted[j + 1]) {
        int temp = sorted[j];
        sorted[j] = sorted[j + 1];
        sorted[j + 1] = temp;
      }
    }
  }
  if (length % 2 == 1) {
    return sorted[length / 2];
  }
  return (sorted[length / 2 - 1] + sorted[length / 2]) / 2;
}

// Compute Weighted Water Quality Index (0 = Worst, 100 = Ideal)
float calculateWQI(float ph, float ntu, float tds, float tempC) {
  float qPh   = constrain(100.0 - (fabs(ph - 7.0) * 40.0), 0.0, 100.0);
  float qTurb = constrain(100.0 - (ntu * 0.8), 0.0, 100.0);
  float qTds  = constrain(100.0 - ((tds / 1000.0) * 100.0), 0.0, 100.0);

  float qTemp = 100.0;
  if (tempC < 15.0) {
    qTemp = 100.0 - ((15.0 - tempC) * 6.0);
  } else if (tempC > 28.0) {
    qTemp = 100.0 - ((tempC - 28.0) * 8.0);
  }
  qTemp = constrain(qTemp, 0.0, 100.0);

  return (qPh * 0.30) + (qTurb * 0.30) + (qTds * 0.25) + (qTemp * 0.15);
}

// Classify overall water condition and likely pollution source
String classifyPollution(float ph, float ntu, float tds, float tempC) {
  if (ph < 6.0) return "ACIDIC POLLUTION (Industrial / Acid Runoff)";
  if (ph > 8.8) return "ALKALINE POLLUTION (Detergent / Agricultural Runoff)";
  if (ntu > 100.0 && tds > 500.0) return "MIXED SEWAGE / URBAN RUNOFF";
  if (ntu > 100.0) return "SEDIMENT / MUD RUNOFF (High Turbidity)";
  if (tds > 500.0) return "DISSOLVED CHEMICAL / SALT CONTAMINATION";
  if (tempC > 32.0) return "THERMAL POLLUTION (Elevated Water Temp)";
  return "HEALTHY / CLEAN LAKE WATER";
}

// Transmit live physical readings to the laptop dashboard
void sendToDashboard(float temp, float ph, float tds, float turb) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");

    char jsonPayload[256];
    snprintf(jsonPayload, sizeof(jsonPayload),
      "{\"lake_id\":\"%s\",\"temp\":%.2f,\"ph\":%.2f,\"tds\":%.1f,\"turbidity\":%.1f}",
      BUOY_ID, temp, ph, tds, turb
    );

    int httpCode = http.POST(jsonPayload);
    if (httpCode == 200 || httpCode == 201) {
      Serial.println("   📡 [WiFi] Streamed live to BBMP Command Portal!");
    } else {
      Serial.printf("   ⚠️ [WiFi] Server responded with code: %d\n", httpCode);
    }
    http.end();
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(TDS_PIN, INPUT);
  pinMode(TURBIDITY_PIN, INPUT);
  pinMode(PH_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);

  tempSensor.begin();

  Serial.println("\n=======================================================");
  Serial.println("🌊 Quintessence Physical IoT Buoy #1 Booting Up...");
  Serial.println("Sensors: DS18B20 (D18), TDS (D34), Turbidity (D35), pH (D32)");
  Serial.println("=======================================================");

  // Connect to WiFi
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Pre-fill analog sample buffers on startup for immediate stability
  for (int i = 0; i < SAMPLE_COUNT; i++) {
    tdsBuffer[i]  = analogRead(TDS_PIN);
    turbBuffer[i] = analogRead(TURBIDITY_PIN);
    phBuffer[i]   = analogRead(PH_PIN);
    delay(10);
  }

  Serial.println("✅ Analog filter buffers primed. Starting measurements...\n");
}

void loop() {
  unsigned long currentMillis = millis();

  // 1. Fill analog sample buffers at 40 ms interval
  if (currentMillis - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentMillis;

    tdsBuffer[bufferIndex]  = analogRead(TDS_PIN);
    turbBuffer[bufferIndex] = analogRead(TURBIDITY_PIN);
    phBuffer[bufferIndex]   = analogRead(PH_PIN);

    bufferIndex = (bufferIndex + 1) % SAMPLE_COUNT;
  }

  // 2. Compute filtered values and print every 2 seconds
  if (currentMillis - lastPrintTime >= PRINT_INTERVAL) {
    lastPrintTime = currentMillis;

    digitalWrite(LED_PIN, HIGH); // Pulse LED

    // Get median filtered ADC values
    int medTdsRaw  = getMedian(tdsBuffer, SAMPLE_COUNT);
    int medTurbRaw = getMedian(turbBuffer, SAMPLE_COUNT);
    int medPhRaw   = getMedian(phBuffer, SAMPLE_COUNT);

    // Convert to probe voltages through voltage dividers
    float vTdsPin  = (medTdsRaw / 4095.0) * VREF;
    float vTurbPin = (medTurbRaw / 4095.0) * VREF;
    float vPhPin   = (medPhRaw / 4095.0) * VREF;

    float vTdsActual  = vTdsPin * TDS_DIVIDER_RATIO;
    float vTurbActual = vTurbPin * TURB_DIVIDER_RATIO;
    float vPhActual   = vPhPin * PH_DIVIDER_RATIO;

    // Read DS18B20 Temperature
    tempSensor.requestTemperatures();
    float waterTemp = tempSensor.getTempCByIndex(0);
    if (waterTemp == DEVICE_DISCONNECTED_C || waterTemp < -10.0 || waterTemp > 60.0) {
      waterTemp = 25.0; // Fallback to 25°C baseline if probe disconnected
    }

    // A. pH Calculation (PH-4502C probe formula)
    float phValue = 7.0 + ((phNeutralVoltage - vPhActual) / phSlope);
    phValue = constrain(phValue, 0.0, 14.0);

    // B. Turbidity Calculation (DFRobot / Keyes formula)
    float ntuValue = 0.0;
    if (vTurbActual >= turbClearVoltage) {
      ntuValue = 0.0;
    } else {
      ntuValue = -1120.4 * pow(vTurbActual, 2) + 5742.3 * vTurbActual - 4352.9;
      ntuValue = constrain(ntuValue, 0.0, 1000.0);
    }

    // C. TDS Calculation with Temperature Compensation
    float compCoefficient = 1.0 + 0.02 * (waterTemp - 25.0);
    float compVoltage = vTdsActual / compCoefficient;
    float tdsValue = (133.42 * pow(compVoltage, 3) - 255.86 * pow(compVoltage, 2) + 857.39 * compVoltage) * 0.5 * tdsKValue;
    tdsValue = max(0.0f, tdsValue);

    // D. Compute WQI and Pollution Status
    float wqi = calculateWQI(phValue, ntuValue, tdsValue, waterTemp);
    String status = classifyPollution(phValue, ntuValue, tdsValue, waterTemp);

    // Print to Serial Monitor
    Serial.println("-------------------------------------------------------");
    Serial.printf("🌡️  Water Temp:  %.2f °C\n", waterTemp);
    Serial.printf("🧪  pH Level:    %.2f  (Sensor Voltage: %.2f V)\n", phValue, vPhActual);
    Serial.printf("⚡  TDS Solids:  %.1f ppm (Sensor Voltage: %.2f V)\n", tdsValue, vTdsActual);
    Serial.printf("🌫️  Turbidity:   %.1f NTU (Sensor Voltage: %.2f V)\n", ntuValue, vTurbActual);
    Serial.printf("📊  WQI Score:   %.1f / 100\n", wqi);
    Serial.printf("🚨  Condition:   %s\n", status.c_str());

    // Stream physical readings to backend portal
    sendToDashboard(waterTemp, phValue, tdsValue, ntuValue);

    digitalWrite(LED_PIN, LOW);
  }
}
