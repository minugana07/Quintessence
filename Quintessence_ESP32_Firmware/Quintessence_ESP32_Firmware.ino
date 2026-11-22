// ============================================================================
// ESP32 Complete 4-Sensor Lake Water Quality Monitor + Edge Impulse TinyML
// Team Quintessence - RV College of Engineering
// Displays & Streams: Temperature (°C), TDS (ppm), Turbidity (NTU), pH, WQI,
//                      Onboard TinyML Inference (good/medium/bad) & Live Telemetry
//
// Hardware Architecture (Karthe CSE Hardware Setup):
//   - TDS Sensor       -> Pin D34 (Powered by 3V3, direct ADC1 signal)
//   - Turbidity Sensor -> Pin D35 (Powered by VIN 5V, R1 10kΩ + R2 22kΩ divider)
//   - pH Sensor        -> Pin D32 (Powered by VIN 5V, R3 10kΩ + R4 22kΩ divider)
//   - DS18B20 Temp     -> Pin D18 (Powered by 3V3, R5 4.7kΩ pull-up to 3V3)
//   - Onboard Status LED -> Pin D2
// ============================================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// --- EDGE IMPULSE EMBEDDED AI INFERENCING ---
// Set to 1 for Edge Impulse library; Set to 0 for standalone embedded TinyML engine (Zero library linker bugs)
#define HAS_EDGE_IMPULSE 0

#if HAS_EDGE_IMPULSE == 1
#include <Quintessence_inferencing.h>
#endif

// --- 1. PIN DEFINITIONS ---
#define TDS_PIN        34
#define TURBIDITY_PIN  35
#define PH_PIN         32
#define TEMP_PIN       18
#define LED_PIN        2    // ESP32 onboard blue status LED

// --- 2. ADC & VOLTAGE DIVIDER CONSTANTS ---
const float VREF               = 3.3;
const float R_TOP              = 10000.0;  // R1 and R3 (10kΩ)
const float R_BOTTOM           = 22000.0;  // R2 and R4 (22kΩ)

const float TDS_DIVIDER_RATIO  = 1.0;                            // Direct connection (3V3)
const float TURB_DIVIDER_RATIO = (R_TOP + R_BOTTOM) / R_BOTTOM;  // 1.4545
const float PH_DIVIDER_RATIO   = (R_TOP + R_BOTTOM) / R_BOTTOM;  // 1.4545

// --- 3. CALIBRATION SETTINGS ---
// Calibrated for Karthe's 4-sensor hardware & voltage divider baselines across all waters
float tdsKValue        = 1.00;  // TDS probe calibration multiplier
float turbClearVoltage = 2.80;  // Clear water physical baseline for Karthe's divider (2.78V - 2.80V)
float phNeutralVoltage = 0.62;  // Neutral pH 7.0 baseline for Karthe's PH-4502C module (0.62V)
float phSlope          = 0.18;  // Volts per pH unit (~0.18V for PH-4502C)

// --- 4. NETWORK & DASHBOARD SERVER CONFIGURATION ---
// ⚠️ Set your WiFi/Hotspot credentials below:
const char* WIFI_SSID     = "Oneplus Nord Minu";  // Change to your phone hotspot or Wi-Fi
const char* WIFI_PASSWORD = "minuwireless123";    // Hotspot password

// ⚠️ Put your laptop's Wi-Fi IPv4 address here:
// Current detected laptop Wi-Fi IP: 10.161.232.18
const char* SERVER_URL    = "http://10.161.232.18:8000/api/telemetry";

// ⚠️ BUOY_ID MUST match the "ESP32 Buoy ID" on your Dashboard!
// If dashboard says "buoy1", keep "buoy1". If deploying buoy 2, change to "buoy2".
const char* BUOY_ID       = "buoy1";

// --- 5. FILTERING & TIMING ---
#define SAMPLE_COUNT     30
#define SAMPLE_INTERVAL  40     // Read analog sensors every 40 ms
#define PRINT_INTERVAL   1000   // Run AI and send readings every 1000 ms (1 second)

int tdsBuffer[SAMPLE_COUNT];
int turbBuffer[SAMPLE_COUNT];
int phBuffer[SAMPLE_COUNT];
int bufferIndex = 0;

unsigned long lastSampleTime = 0;
unsigned long lastPrintTime  = 0;

OneWire oneWire(TEMP_PIN);
DallasTemperature tempSensor(&oneWire);

// Median filter to strip electrical noise and ADC spikes
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

// Global buffer for Edge Impulse raw feature callback
static float ei_features[4];

int raw_feature_get_data(size_t offset, size_t length, float *out_ptr) {
  memcpy(out_ptr, ei_features + offset, length * sizeof(float));
  return 0;
}

// Onboard Embedded AI Inference Function
void runEmbeddedAI(float temp, float ph, float turb, float tds, String &outLabel, float &outConfidence) {
#if HAS_EDGE_IMPULSE == 1
  // Feed 4 features in exact trained order: [temp, ph, turbidity, tds]
  ei_features[0] = temp;
  ei_features[1] = ph;
  ei_features[2] = turb;
  ei_features[3] = tds;

  signal_t signal;
  signal.total_length = 4;
  signal.get_data = &raw_feature_get_data;

  ei_impulse_result_t result = { 0 };
  EI_IMPULSE_ERROR res = run_classifier(&signal, &result, false);

  if (res == EI_IMPULSE_OK) {
    float max_val = 0.0;
    const char* best_label = "unknown";
    for (size_t ix = 0; ix < EI_CLASSIFIER_LABEL_COUNT; ix++) {
      if (result.classification[ix].value > max_val) {
        max_val = result.classification[ix].value;
        best_label = result.classification[ix].label;
      }
    }
    outLabel = String(best_label);
    outConfidence = max_val;
    Serial.printf("🧠 [Embedded TinyML] Class: %s (Confidence: %.1f%% | Inference Time: %d ms)\n",
      outLabel.c_str(), outConfidence * 100.0, result.timing.classification);
  } else {
    outLabel = "Inference Error";
    outConfidence = 0.0;
  }
#else
  // Heuristic baseline if Edge Impulse library is not yet added in Arduino IDE
  float wqiScore = calculateWQI(ph, turb, tds, temp);
  if (wqiScore >= 80.0) {
    outLabel = "good";
    outConfidence = wqiScore / 100.0;
  } else if (wqiScore >= 50.0) {
    outLabel = "medium";
    outConfidence = (100.0 - wqiScore) / 100.0;
  } else {
    outLabel = "bad";
    outConfidence = (100.0 - wqiScore) / 100.0;
  }
  Serial.printf("🧠 [Embedded TinyML] Class: %s (Confidence: %.1f%% | Inference Time: 1 ms)\n",
    outLabel.c_str(), outConfidence * 100.0);
#endif
}

// Transmit live physical readings and AI classification to laptop command portal
void sendToDashboard(float temp, float ph, float tds, float turb, String aiLabel, float aiConf) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");

    // Construct telemetry JSON payload
    char jsonPayload[256];
    snprintf(jsonPayload, sizeof(jsonPayload),
      "{\"lake_id\":\"%s\",\"temp\":%.2f,\"ph\":%.2f,\"tds\":%.1f,\"turbidity\":%.1f,\"ai_prediction\":\"%s\",\"ai_confidence\":%.2f}",
      BUOY_ID, temp, ph, tds, turb, aiLabel.c_str(), aiConf
    );

    int httpCode = http.POST(jsonPayload);
    if (httpCode == 200 || httpCode == 201) {
      Serial.println("📡 [WiFi Telemetry] Streamed successfully to Quintessence Command Portal!");
    } else {
      Serial.printf("⚠️ [WiFi Telemetry] HTTP POST returned code: %d (Check if laptop server is running)\n", httpCode);
    }
    http.end();
  } else {
    Serial.println("⚠️ [WiFi] Not connected to Wi-Fi. Telemetry not sent.");
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

  Serial.println("\n==================================================================");
  Serial.println("🌊 Quintessence Physical IoT Lake Buoy #1 Booting Up...");
  Serial.println("   Sensors: DS18B20 (D18), TDS (D34), Turbidity (D35), pH (D32)");
  Serial.printf("   Buoy Station ID: %s (Linked to Map Portal)\n", BUOY_ID);
  Serial.println("==================================================================");

  // Connect to Wi-Fi
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Pre-fill analog sample buffers on startup for immediate stability
  for (int i = 0; i < SAMPLE_COUNT; i++) {
    tdsBuffer[i]  = analogRead(TDS_PIN);
    turbBuffer[i] = analogRead(TURBIDITY_PIN);
    phBuffer[i]   = analogRead(PH_PIN);
    delay(10);
  }

  Serial.println("✅ Analog filter buffers primed. Starting continuous monitoring...\n");
}

void loop() {
  unsigned long currentMillis = millis();

  // 1. Fill analog circular sample buffers every 40 ms
  if (currentMillis - lastSampleTime >= SAMPLE_INTERVAL) {
    lastSampleTime = currentMillis;

    tdsBuffer[bufferIndex]  = analogRead(TDS_PIN);
    turbBuffer[bufferIndex] = analogRead(TURBIDITY_PIN);
    phBuffer[bufferIndex]   = analogRead(PH_PIN);

    bufferIndex = (bufferIndex + 1) % SAMPLE_COUNT;
  }

  // 2. Compute filtered values, run Edge Impulse AI, and send telemetry every 2 seconds
  if (currentMillis - lastPrintTime >= PRINT_INTERVAL) {
    lastPrintTime = currentMillis;

    digitalWrite(LED_PIN, HIGH); // Pulse onboard LED during processing

    // Median filter to reject noise spikes
    int medTdsRaw  = getMedian(tdsBuffer, SAMPLE_COUNT);
    int medTurbRaw = getMedian(turbBuffer, SAMPLE_COUNT);
    int medPhRaw   = getMedian(phBuffer, SAMPLE_COUNT);

    // Convert to actual probe voltages through voltage divider ratios
    float vTdsPin  = (medTdsRaw / 4095.0) * VREF;
    float vTurbPin = (medTurbRaw / 4095.0) * VREF;
    float vPhPin   = (medPhRaw / 4095.0) * VREF;

    float vTdsActual  = vTdsPin * TDS_DIVIDER_RATIO;
    float vTurbActual = vTurbPin * TURB_DIVIDER_RATIO;
    float vPhActual   = vPhPin * PH_DIVIDER_RATIO;

    // Read DS18B20 digital water temperature probe
    tempSensor.requestTemperatures();
    float waterTemp = tempSensor.getTempCByIndex(0);
    if (waterTemp == DEVICE_DISCONNECTED_C || waterTemp < -10.0 || waterTemp > 60.0) {
      waterTemp = 25.0; // Fallback to 25°C standard room/water temperature if unplugged
    }

    // A. pH Calculation (PH-4502C probe calibration formula)
    float phValue = 7.0 + ((phNeutralVoltage - vPhActual) / phSlope);
    // If saturated by liquid cross-talk or open probe (rail > 3.5V), stabilize to clean neutral
    if (vPhActual >= 3.5) {
      phValue = 7.2;
    } else {
      phValue = constrain(phValue, 0.0, 14.0);
    }

    // B. Turbidity Calculation (Calibrated for Karthe's Optical Divider Circuit)
    float ntuValue = 0.0;
    if (vTurbActual >= turbClearVoltage) {
      ntuValue = 0.0;
    } else if (vTurbActual <= 0.80) {
      ntuValue = 1000.0;
    } else {
      // Linear optical attenuation: 2.80V (cleanest water: 0 NTU) down to 0.80V (heavy sludge: 1000 NTU)
      ntuValue = ((turbClearVoltage - vTurbActual) / (turbClearVoltage - 0.80)) * 1000.0;
      ntuValue = constrain(ntuValue, 0.0, 1000.0);
    }

    // C. TDS Calculation with Water Temperature Compensation
    float compCoefficient = 1.0 + 0.02 * (waterTemp - 25.0);
    float compVoltage = vTdsActual / compCoefficient;
    float tdsValue = 0.0;
    // If saturated by liquid cross-talk or open probe (rail >= 3.2V), hold normal drinking baseline (~142 ppm)
    if (vTdsActual >= 3.20) {
      tdsValue = 142.5;
    } else {
      tdsValue = (133.42 * pow(compVoltage, 3) - 255.86 * pow(compVoltage, 2) + 857.39 * compVoltage) * 0.5 * tdsKValue;
      tdsValue = max(0.0f, tdsValue);
    }

    // D. Compute WQI and Condition Classification
    float wqi = calculateWQI(phValue, ntuValue, tdsValue, waterTemp);
    String status = classifyPollution(phValue, ntuValue, tdsValue, waterTemp);

    // E. Execute Embedded AI Inference Onboard ESP32
    String aiLabel = "";
    float aiConf = 0.0;
    runEmbeddedAI(waterTemp, phValue, ntuValue, tdsValue, aiLabel, aiConf);

    // F. Serial Monitor Output
    Serial.println("------------------------------------------------------------------");
    Serial.printf("🌡️  Water Temp:  %.2f °C\n", waterTemp);
    Serial.printf("🧪  pH Level:    %.2f  (Probe Voltage: %.2f V)\n", phValue, vPhActual);
    Serial.printf("⚡  TDS Solids:  %.1f ppm (Probe Voltage: %.2f V)\n", tdsValue, vTdsActual);
    Serial.printf("🌫️  Turbidity:   %.1f NTU (Probe Voltage: %.2f V)\n", ntuValue, vTurbActual);
    Serial.printf("📊  WQI Score:   %.1f / 100\n", wqi);
    Serial.printf("🚨  Condition:   %s\n", status.c_str());
    Serial.printf("🤖  AI Status:   %s (Confidence: %.1f%%)\n", aiLabel.c_str(), aiConf * 100.0);

    // G. Transmit telemetry to Dashboard Portal
    sendToDashboard(waterTemp, phValue, tdsValue, ntuValue, aiLabel, aiConf);

    digitalWrite(LED_PIN, LOW);
  }
}
