import time
import random
import json
import urllib.request

API_URL = "http://localhost:8000/api/telemetry"

print("=========================================================")
print("🤖 Quintessence Buoy #1 Telemetry Simulator Running...")
print("Transmitting live lake data to:", API_URL)
print("Press Ctrl+C to stop.")
print("=========================================================\n")

# Single physical hardware buoy deployed at Bellandur Lake pilot station
buoy = {
    "id": "buoy1",
    "name": "Quintessence IoT Buoy #1 (Bellandur Lake)",
    "base_temp": 24.8,
    "base_ph": 7.4,
    "base_tds": 275,
    "base_turb": 10
}

step = 0

while True:
    step += 1
    
    # Natural sensor variance
    temp = round(buoy["base_temp"] + random.uniform(-0.4, 0.4), 2)
    ph = round(buoy["base_ph"] + random.uniform(-0.15, 0.15), 2)
    tds = round(buoy["base_tds"] + random.uniform(-10, 10), 1)
    turb = round(buoy["base_turb"] + random.uniform(-1.5, 1.5), 1)

    # Realistic scenario testing every few cycles:
    # 1. Anomaly A: Sewage Ingress spike
    if step % 8 == 0:
        tds = round(random.uniform(620, 780), 1)
        turb = round(random.uniform(42, 65), 1)
        event_tag = "⚠️ SIMULATING SEWAGE INFLOW"
    # 2. Anomaly B: Algal bloom pH shift
    elif step % 12 == 0:
        ph = round(random.uniform(9.0, 9.4), 2)
        event_tag = "⚠️ SIMULATING ALGAL BLOOM"
    else:
        event_tag = "✅ NORMAL BASELINE"

    payload = {
        "lake_id": buoy["id"],
        "temp": temp,
        "ph": ph,
        "tds": tds,
        "turbidity": turb
    }

    try:
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            ai = res_data.get("ai_result", {})
            print(f"[{buoy['name']}] Sent -> Temp: {temp}°C | pH: {ph} | TDS: {tds} ppm | Turb: {turb} NTU")
            print(f"   ↳ AI Engine: Status={ai.get('status')} | Color={ai.get('color')} | LHI={ai.get('lhi')} | {event_tag}\n")
    except Exception as e:
        print(f"❌ Failed to reach backend: {e}")
        print("   (Make sure 'python backend_server.py' is running in another terminal!)")

    time.sleep(3)
