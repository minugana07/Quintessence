import time
import random
import json
import urllib.request

API_URL = "http://localhost:8000/api/telemetry"

print("=========================================================")
print("🤖 ESP32 Virtual Telemetry Simulator Running...")
print("Transmitting live lake data to:", API_URL)
print("Press Ctrl+C to stop.")
print("=========================================================\n")

# Simulated lakes and their baseline characteristics
lakes = [
    {"id": "bellandur", "name": "Bellandur Lake", "base_temp": 24.5, "base_ph": 7.3, "base_tds": 280, "base_turb": 12},
    {"id": "varthur", "name": "Varthur Lake", "base_temp": 25.0, "base_ph": 7.6, "base_tds": 310, "base_turb": 15},
    {"id": "sankey", "name": "Sankey Tank", "base_temp": 23.8, "base_ph": 7.2, "base_tds": 180, "base_turb": 4},
    {"id": "ulsoor", "name": "Ulsoor Lake", "base_temp": 24.1, "base_ph": 7.4, "base_tds": 220, "base_turb": 6},
    {"id": "agara", "name": "Agara Lake", "base_temp": 24.0, "base_ph": 7.3, "base_tds": 200, "base_turb": 5},
]

step = 0

while True:
    step += 1
    # Pick a lake to send a packet from
    lake = random.choice(lakes)
    lake_id = lake["id"]
    
    # Add small random natural fluctuations
    temp = round(lake["base_temp"] + random.uniform(-0.5, 0.5), 2)
    ph = round(lake["base_ph"] + random.uniform(-0.15, 0.15), 2)
    tds = round(lake["base_tds"] + random.uniform(-10, 10), 1)
    turb = round(lake["base_turb"] + random.uniform(-1.5, 1.5), 1)

    # Inject specific realistic scenarios for testing:
    # 1. Every 4th step on Bellandur, simulate a Sewage Spike (High TDS + High Turbidity)
    if lake_id == "bellandur" and (step % 3 == 0):
        tds = round(random.uniform(620, 780), 1)
        turb = round(random.uniform(42, 65), 1)
        event_tag = "⚠️ SIMULATING SEWAGE INFLOW"
    # 2. Every 5th step on Varthur, simulate an Algal Bloom (High basic pH)
    elif lake_id == "varthur" and (step % 5 == 0):
        ph = round(random.uniform(9.0, 9.4), 2)
        event_tag = "⚠️ SIMULATING ALGAL BLOOM"
    else:
        event_tag = "✅ NORMAL"

    payload = {
        "lake_id": lake_id,
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
            print(f"[{lake['name']}] Sent -> Temp: {temp}°C | pH: {ph} | TDS: {tds} ppm | Turb: {turb} NTU")
            print(f"   ↳ AI Engine: Status={ai.get('status')} | Color={ai.get('color')} | LHI={ai.get('lhi')} | {event_tag}\n")
    except Exception as e:
        print(f"❌ Failed to reach backend: {e}")
        print("   (Make sure 'python backend_server.py' is running in another terminal!)")

    time.sleep(3) # Send every 3 seconds
