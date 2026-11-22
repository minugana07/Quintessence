import os
import sqlite3
import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ==========================================================
# 1. FASTAPI APP INITIALIZATION & CORS SETUP
# ==========================================================
app = FastAPI(
    title="BBMP Lake Health Intelligence & Monitoring API",
    description="Real-time IoT Telemetry Ingestion, AI Anomaly Diagnosis, and BBMP Decision Support",
    version="1.0.0"
)

# Enable CORS so Stitch's frontend or any browser can query this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "lakes.db"

# ==========================================================
# 2. DATABASE SETUP & INITIAL SEEDING
# ==========================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table for Monitored Lakes in Bengaluru
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lakes (
        lake_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        ward_name TEXT NOT NULL,
        ward_no INTEGER NOT NULL,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        status TEXT DEFAULT 'NORMAL',
        color TEXT DEFAULT 'GREEN',
        lhi REAL DEFAULT 95.0,
        last_updated TEXT
    )
    """)
    
    # Table for Telemetry Time-Series Data
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS telemetry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lake_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        temperature REAL NOT NULL,
        ph REAL NOT NULL,
        tds REAL NOT NULL,
        turbidity REAL NOT NULL,
        lhi REAL NOT NULL,
        status TEXT NOT NULL,
        color TEXT NOT NULL,
        diagnosis TEXT NOT NULL,
        FOREIGN KEY (lake_id) REFERENCES lakes (lake_id)
    )
    """)

    # Ensure only 1 active physical buoy exists in the system
    cursor.execute("SELECT COUNT(*) FROM lakes")
    count = cursor.fetchone()[0]
    if count == 0 or count > 1:
        cursor.execute("DELETE FROM lakes")
        now = datetime.datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO lakes (lake_id, name, ward_name, ward_no, lat, lng, status, color, lhi, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("buoy1", "Quintessence IoT Buoy #1", "Bellandur Lake (Ward 150)", 150, 12.9348, 77.6740, "NORMAL", "GREEN", 92.0, now))
        
    conn.commit()
    conn.close()

init_db()

# ==========================================================
# 3. EMBEDDED AI ANOMALY & DIAGNOSTIC ENGINE (KSPCB CALIBRATED)
# ==========================================================
def calculate_lhi_and_diagnosis(temp: float, ph: float, tds: float, turb: float, rate_info: Optional[dict] = None):
    # Step A: Check for Sensor Failures / Hardware Glitches
    if ph < 1.0 or ph > 13.0 or tds <= 0.0 or turb < 0.0 or temp < 5.0 or temp > 48.0:
        return {
            "lhi": 0.0,
            "status": "SENSOR_ERROR",
            "color": "YELLOW",
            "diagnosis": "Hardware Glitch / Open Probe: Reading out of physical bounds. Check wiring/probe."
        }

    # Step B: Sub-Index Calculations
    ph_dev = abs(ph - 7.5)
    i_ph = max(0.0, 100.0 - (ph_dev * 35.0))
    
    if tds <= 280:
        i_tds = 100.0
    elif tds <= 550:
        i_tds = 100.0 - ((tds - 280) / 270.0) * 40.0
    else:
        i_tds = max(0.0, 60.0 - ((tds - 550) / 400.0) * 60.0)
        
    if turb <= 8:
        i_turb = 100.0
    elif turb <= 35:
        i_turb = 100.0 - ((turb - 8) / 27.0) * 50.0
    else:
        i_turb = max(0.0, 50.0 - ((turb - 35) / 65.0) * 50.0)

    i_temp = 100.0 if 18.0 <= temp <= 29.0 else 70.0

    # Composite Lake Health Index (pH: 35%, Turbidity: 30%, TDS: 20%, Temperature: 15%)
    lhi = round(0.35 * i_ph + 0.30 * i_turb + 0.20 * i_tds + 0.15 * i_temp, 1)

    # -------------------------------------------------------------
    # Step C: AVANTHIKA BIOTECH RATE-OF-CHANGE (d/dt) ANALYSIS
    # Distinguishes natural diurnal photosynthesis from acute chemical dumping
    # -------------------------------------------------------------
    acute_surge = False
    rate_diagnosis = None
    
    if rate_info:
        delta_m = rate_info.get("delta_mins", 0.0)
        d_ph = rate_info.get("delta_ph", 0.0)
        d_tds = rate_info.get("delta_tds", 0.0)
        d_turb = rate_info.get("delta_turb", 0.0)
        rate_ph_hr = rate_info.get("rate_ph_per_hour", 0.0)

        # 1. ACUTE pH SPIKE (>0.4 change within 15 minutes)
        if delta_m <= 15.0 and abs(d_ph) >= 0.40:
            acute_surge = True
            direction = "alkaline dump" if d_ph > 0 else "acid spill"
            rate_diagnosis = f"ACUTE CHEMICAL SURGE: pH surged {'+' if d_ph>0 else ''}{d_ph:.2f} in {delta_m:.1f} mins ({direction}). Biological buffering capacity exceeded!"
        
        # 2. ACUTE TDS SURGE (>120 ppm jump within 15 minutes)
        elif delta_m <= 15.0 and d_tds >= 120.0:
            acute_surge = True
            rate_diagnosis = f"ACUTE LEACHATE INFLUX: TDS spiked +{d_tds:.0f} ppm in {delta_m:.1f} mins. Sudden dissolved effluent discharge detected!"

        # 3. ACUTE TURBIDITY SURGE (>40 NTU jump within 15 minutes)
        elif delta_m <= 15.0 and d_turb >= 40.0:
            acute_surge = True
            rate_diagnosis = f"ACUTE SEDIMENT PLUME: Turbidity surged +{d_turb:.1f} NTU in {delta_m:.1f} mins. Sludge pipe release or storm breach suspected!"

        # 4. NATURAL DIURNAL PHOTOSYNTHESIS (pH elevated but rising gradually <= 0.35/hour)
        elif 8.0 <= ph <= 8.9 and 0.0 < rate_ph_hr <= 0.35 and delta_m >= 3.0:
            rate_diagnosis = f"Natural Diurnal Photosynthesis: Gradual daytime CO2 uptake (+{rate_ph_hr:.2f} pH/hr). Biological equilibrium maintained."

    # -------------------------------------------------------------
    # Step D: MULTI-VARIATE KSPCB RULES & ANTI-ECLIPSING HARD CLAMP
    # (Liebig's Law of the Minimum: A single toxic parameter forces RED)
    # -------------------------------------------------------------
    if acute_surge:
        status = "CRITICAL"
        color = "RED"
        lhi = min(lhi, 32.0)
        diagnosis = rate_diagnosis

    # Anti-Eclipsing Single-Parameter Hard Clamp: Lethal Acid (<6.0)
    elif ph < 6.0:
        status = "CRITICAL"
        color = "RED"
        lhi = min(lhi, 28.0)
        diagnosis = f"Industrial Acid Contamination (pH {ph:.2f}): Severe single-parameter lethal violation. Anti-eclipsing override active."

    # Anti-Eclipsing Single-Parameter Hard Clamp: Extreme Caustic (>9.0)
    elif ph > 9.0:
        status = "CRITICAL"
        color = "RED"
        lhi = min(lhi, 32.0)
        diagnosis = f"Severe Caustic Alkaline Surge (pH {ph:.2f}): Exceeds KSPCB safety ceiling. High toxicity risk."

    # Concurrent Sewage / Sullage Inflow (TDS + Turbidity)
    elif tds > 550 and turb > 35:
        status = "CRITICAL"
        color = "RED"
        lhi = min(lhi, 38.0)
        diagnosis = "KSPCB Class E Non-Compliance: Raw Sewage / Sullage Inflow detected (Concurrent TDS and Turbidity surge)."

    # Anti-Eclipsing Single-Parameter Hard Clamp: Extreme Turbidity (>90 NTU)
    elif turb > 90.0:
        status = "CRITICAL"
        color = "RED"
        lhi = min(lhi, 35.0)
        diagnosis = f"Severe Sludge / Sediment Breach ({turb:.1f} NTU): Complete light penetration collapse. Eclipsing override."

    # Anti-Eclipsing Single-Parameter Hard Clamp: Extreme Dissolved Solids (>750 ppm)
    elif tds > 750.0:
        status = "CRITICAL"
        color = "RED"
        lhi = min(lhi, 35.0)
        diagnosis = f"High Saline / Toxic Chemical Contamination (TDS {tds:.0f} ppm): Critical dissolved solute saturation."

    # Moderate Diurnal or Eutrophic Alert (pH 8.4 - 9.0)
    elif ph > 8.4:
        status = "ALERT"
        color = "ORANGE"
        if rate_diagnosis:
            diagnosis = rate_diagnosis
        else:
            diagnosis = "KSPCB Eutrophication Alert: Elevated pH indicates intense daylight CO2 depletion from micro-algae."

    # Moderate Silt Runoff
    elif turb > 35:
        status = "ALERT"
        color = "ORANGE"
        diagnosis = "High Turbidity / Silt Runoff: Construction or storm drain sediment influx."

    # Moderate High TDS
    elif tds > 500:
        status = "ALERT"
        color = "ORANGE"
        diagnosis = "Elevated Dissolved Solids: Mineral or drainage leachate deviation."

    # Clean / Normal Water
    elif lhi >= 75.0:
        status = "NORMAL"
        color = "GREEN"
        diagnosis = "KSPCB Class C Compliant: Water quality within safe biological baseline. All parameters compliant."

    else:
        status = "ALERT"
        color = "ORANGE"
        diagnosis = "Moderate water quality deviation under KSPCB monitoring limits."

    return {
        "lhi": lhi,
        "status": status,
        "color": color,
        "diagnosis": diagnosis
    }

# ==========================================================
# 4. REQUEST / RESPONSE SCHEMAS
# ==========================================================
class TelemetryPayload(BaseModel):
    lake_id: str
    temp: float
    ph: float
    tds: float
    turbidity: float

class TicketPayload(BaseModel):
    lake_id: str
    reported_by: str
    notes: Optional[str] = "Field inspection requested"

class CopilotQuery(BaseModel):
    lake_id: str
    question: str

# ==========================================================
# 5. API ENDPOINTS FOR STITCH'S FRONTEND & THE ESP32
# ==========================================================

@app.post("/api/telemetry")
def ingest_telemetry(data: TelemetryPayload):
    lake_id = data.lake_id.lower()
    if lake_id in ["bellandur", "buoy_1", "esp32", "quintessence"]:
        lake_id = "buoy1"
    now = datetime.datetime.now().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Query previous telemetry to compute Rate of Change (d/dt)
    cursor.execute("""
        SELECT timestamp, temperature, ph, tds, turbidity 
        FROM telemetry 
        WHERE lake_id = ? 
        ORDER BY id DESC LIMIT 1
    """, (lake_id,))
    prev = cursor.fetchone()
    
    rate_info = None
    if prev:
        try:
            prev_time_str, prev_temp, prev_ph, prev_tds, prev_turb = prev
            prev_dt = datetime.datetime.fromisoformat(prev_time_str)
            curr_dt = datetime.datetime.fromisoformat(now)
            delta_mins = (curr_dt - prev_dt).total_seconds() / 60.0
            if 0.05 <= delta_mins <= 120.0:  # Valid comparison window between 3 sec and 2 hours
                delta_ph = data.ph - prev_ph
                rate_ph_per_hour = (delta_ph / delta_mins) * 60.0 if delta_mins > 0 else 0.0
                rate_info = {
                    "delta_mins": delta_mins,
                    "delta_ph": delta_ph,
                    "rate_ph_per_hour": rate_ph_per_hour,
                    "delta_tds": data.tds - prev_tds,
                    "delta_turb": data.turbidity - prev_turb
                }
        except Exception:
            pass

    ai_result = calculate_lhi_and_diagnosis(data.temp, data.ph, data.tds, data.turbidity, rate_info)
    
    cursor.execute("""
        INSERT INTO telemetry (lake_id, timestamp, temperature, ph, tds, turbidity, lhi, status, color, diagnosis)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lake_id, now, data.temp, data.ph, data.tds, data.turbidity,
        ai_result["lhi"], ai_result["status"], ai_result["color"], ai_result["diagnosis"]
    ))
    cursor.execute("""
        UPDATE lakes 
        SET status = ?, color = ?, lhi = ?, last_updated = ?
        WHERE lake_id = ?
    """, (ai_result["status"], ai_result["color"], ai_result["lhi"], now, lake_id))
    conn.commit()
    conn.close()
    
    return {"status": "success", "processed_at": now, "ai_result": ai_result}

@app.get("/api/lakes")
def get_all_lakes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lakes")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/lake/{lake_id}")
def get_lake_details(lake_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lakes WHERE lake_id = ?", (lake_id.lower(),))
    lake = cursor.fetchone()
    if not lake:
        conn.close()
        raise HTTPException(status_code=404, detail="Lake not found")
        
    cursor.execute("SELECT * FROM telemetry WHERE lake_id = ? ORDER BY id DESC LIMIT 1", (lake_id.lower(),))
    latest = cursor.fetchone()
    conn.close()
    return {"meta": dict(lake), "latest": dict(latest) if latest else None}

@app.get("/api/lake/{lake_id}/history")
def get_lake_history(lake_id: str, limit: int = 50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, temperature, ph, tds, turbidity, lhi, status, color 
        FROM telemetry 
        WHERE lake_id = ? 
        ORDER BY id ASC
    """, (lake_id.lower(),))
    rows = cursor.fetchall()
    conn.close()
    sliced = rows[-limit:] if len(rows) > limit else rows
    return [dict(r) for r in sliced]

@app.post("/api/ticket")
def create_bbmp_ticket(ticket: TicketPayload):
    ticket_id = f"BBMP-W{datetime.datetime.now().strftime('%m%d%H%M')}"
    return {
        "ticket_id": ticket_id,
        "lake_id": ticket.lake_id,
        "created_at": datetime.datetime.now().isoformat(),
        "status": "DISPATCHED",
        "message": f"Inspection ticket {ticket_id} created and dispatched to Ward Assistant Executive Engineer (AEE)."
    }

@app.post("/api/copilot")
def query_copilot(query: CopilotQuery):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lakes WHERE lake_id = ?", (query.lake_id.lower(),))
    lake = cursor.fetchone()
    if not lake:
        conn.close()
        raise HTTPException(status_code=404, detail="Lake not found")
        
    cursor.execute("SELECT * FROM telemetry WHERE lake_id = ? ORDER BY id DESC LIMIT 1", (query.lake_id.lower(),))
    latest = cursor.fetchone()
    conn.close()
    
    if not latest:
        return {"answer": f"No telemetry has been logged yet for {lake['name']}. Start simulate_esp32.py to stream live sensor data."}
        
    temp, ph, tds, turb = latest["temperature"], latest["ph"], latest["tds"], latest["turbidity"]
    lhi, status = latest["lhi"], latest["status"]
    q = query.question.lower()
    
    if "why" in q or "status" in q or "reason" in q or "wrong" in q or "problem" in q:
        ans = (f"🔍 **Status Diagnostic for {lake['name']}** (LHI: {lhi}/100 - {status}):\n\n"
               f"• **Root Cause:** {latest['diagnosis']}\n"
               f"• **Telemetry Evidence:** TDS is {tds} ppm (safe limit: 550 ppm), Turbidity is {turb} NTU (safe limit: 35 NTU), pH is {ph} (safe range: 6.5-8.5).\n"
               f"• **KSPCB Impact:** Concurrent spikes in TDS & Turbidity indicate raw untreated sewage or sullage bypass from surrounding storm drains.")
    elif "fish" in q or "wildlife" in q or "safe" in q or "life" in q:
        if status == "CRITICAL":
            ans = (f"⚠️ **Aquatic Toxicity Warning for {lake['name']}:**\n\n"
                   f"High TDS ({tds} ppm) and heavy suspended solids ({turb} NTU) severely deplete dissolved oxygen and choke gill filaments. Fish mortality risk is CRITICAL under current sewage loading.")
        else:
            ans = (f"✅ **Aquatic Life Baseline:** Parameter indices indicate water conditions meet KSPCB Class C standards. Suitable for aquatic fauna and secondary contact.")
    elif "action" in q or "bbmp" in q or "protocol" in q or "do" in q:
        ans = (f"📋 **BBMP Recommended Action Protocol:**\n\n"
               f"1. Dispatch Ward Assistant Executive Engineer (AEE) to inspect inlet culverts.\n"
               f"2. Verify whether local Sewage Treatment Plant (STP) aeration units are functioning.\n"
               f"3. Issue urgent field ticket (use button above).")
    else:
        ans = (f"📊 **Telemetry Summary for {lake['name']} (LHI: {lhi}/100 - {status}):**\n\n"
               f"• Water Temp: {temp}°C | pH: {ph} | TDS: {tds} ppm | Turbidity: {turb} NTU\n"
               f"• AI Diagnostic: {latest['diagnosis']}")
               
    return {"answer": ans}

# ==========================================================
# 6. RESTORED DASHBOARD WITH WORKING DARK-MATTER MAP
# ==========================================================
@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>KSPCB & BBMP Lake Health Early-Warning Command Portal</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
            html, body { margin: 0; padding: 0; height: 100%; background: #0b132b; color: #fff; display: flex; flex-direction: column; overflow: hidden; }
            header { background: #1c2541; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #3a506b; flex-shrink: 0; }
            header h1 { margin: 0; font-size: 20px; color: #48cae4; }
            .badge { background: #ff4d4d; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size: 13px; }
            .container { display: flex; flex: 1; height: calc(100vh - 65px); width: 100vw; overflow: hidden; }
            #map-pane { flex: 1; height: 100%; min-height: 450px; background: #0b132b; position: relative; }
            /* Zero-Watermark Dark Modes for OpenStreetMap */
            #map-pane.cyber-dark .leaflet-tile-pane {
                filter: brightness(0.6) invert(1) contrast(3) hue-rotate(200deg) saturate(0.3) brightness(0.7);
            }
            #map-pane.midnight .leaflet-tile-pane {
                filter: invert(100%) hue-rotate(180deg) brightness(85%) contrast(120%);
            }
            #map-pane.street .leaflet-tile-pane {
                filter: none;
            }
            #detail-pane {
                width: 520px;
                height: 100%;
                background: #1c2541;
                padding: 20px;
                overflow-y: auto;
                border-left: 2px solid #3a506b;
                scrollbar-width: thin;
                scrollbar-color: #3a506b transparent;
            }
            #detail-pane::-webkit-scrollbar {
                width: 6px;
            }
            #detail-pane::-webkit-scrollbar-track {
                background: transparent;
            }
            #detail-pane::-webkit-scrollbar-thumb {
                background: #3a506b;
                border-radius: 4px;
            }
            #detail-pane::-webkit-scrollbar-thumb:hover {
                background: #48cae4;
            }
            .card { background: #0b132b; padding: 16px; border-radius: 8px; margin-bottom: 16px; border: 1px solid #3a506b; }
            .metric-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 10px; }
            .metric-box { background: #162447; padding: 12px; border-radius: 6px; text-align: center; }
            .metric-box span { font-size: 12px; color: #8d99ae; display: block; }
            .metric-box strong { font-size: 20px; color: #00f5d4; }
            .alert-banner { padding: 12px; border-radius: 6px; margin-bottom: 14px; font-size: 14px; font-weight: 500; }
            .alert-RED { background: rgba(239, 35, 60, 0.2); border-left: 4px solid #ef233c; color: #ff758f; }
            .alert-ORANGE { background: rgba(255, 183, 3, 0.2); border-left: 4px solid #ffb703; color: #ffd166; }
            .alert-GREEN { background: rgba(6, 214, 160, 0.2); border-left: 4px solid #06d6a0; color: #a7c957; }
            .btn { background: #0077b6; color: white; border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; width: 100%; font-weight: bold; }
            .btn:hover { background: #023e8a; }
            .chart-box { height: 160px; margin-bottom: 15px; }
            .pill-btn { background: #1c2541; border: 1px solid #3a506b; color: #48cae4; padding: 5px 10px; border-radius: 12px; font-size: 11px; cursor: pointer; transition: 0.2s; }
            .pill-btn:hover { background: #0077b6; color: white; }
        </style>
    </head>
    <body>
        <header>
            <div>
                <h1>Quintessence IoT Lake Buoy Command Portal</h1>
                <small style="color: #8d99ae;">Domain: Real-Time Water Quality IoT | Active Station: Buoy #1 (Bellandur Lake Pilot) | RV College of Engineering</small>
            </div>
            <div style="display: flex; gap: 10px; align-items: center;">
                <button id="toggle-sidebar-btn" class="pill-btn" onclick="toggleSidebar()" style="display: none;">📊 Show Buoy Panel</button>
                <div id="live-indicator" class="badge">● LIVE TELEMETRY</div>
            </div>
        </header>
        <div class="container">
            <div id="map-pane" class="cyber-dark">
                <div style="position: absolute; bottom: 15px; left: 15px; z-index: 1000; display: flex; gap: 6px; background: rgba(28, 37, 65, 0.9); padding: 5px 10px; border-radius: 8px; border: 1px solid #3a506b; backdrop-filter: blur(4px);">
                    <span style="font-size: 11px; color: #8d99ae; align-self: center; font-weight: bold;">Map Theme:</span>
                    <button class="pill-btn" onclick="setMapTheme('cyber-dark')">🌙 Cyber Dark</button>
                    <button class="pill-btn" onclick="setMapTheme('midnight')">🌌 Midnight</button>
                    <button class="pill-btn" onclick="setMapTheme('street')">🗺️ Street</button>
                </div>
            </div>
            <div id="detail-pane">
                <div style="display: flex; justify-content: flex-end; margin-bottom: 8px;">
                    <button onclick="toggleSidebar()" style="background: none; border: 1px solid #3a506b; color: #8d99ae; cursor: pointer; font-size: 11px; padding: 3px 8px; border-radius: 4px;">✕ Close Panel</button>
                </div>
                <div id="select-prompt" style="color: #8d99ae; text-align: center; margin-top: 50px;">
                    <h3>Click any lake marker on the Bengaluru map</h3>
                    <p>View synchronized sensors, AI diagnosis, and dispatch tickets.</p>
                </div>
                <div id="lake-content" style="display: none;">
                    <div id="alert-box" class="alert-banner"></div>
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h2 id="lake-title" style="margin: 0; color: #caf0f8;">Lake Details</h2>
                            <span id="lake-lhi" style="font-size: 24px; font-weight: bold;">--</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px; margin-bottom: 8px;">
                            <small id="lake-ward" style="color: #8d99ae;">Ward: --</small>
                            <small id="lake-timestamp" style="color: #48cae4; font-weight: 600; font-size: 12px;">🕒 Sampled: --</small>
                        </div>
                        <div class="metric-grid">
                            <div class="metric-box"><span>Temperature</span><strong id="m-temp">-- °C</strong></div>
                            <div class="metric-box"><span>pH Level</span><strong id="m-ph">--</strong></div>
                            <div class="metric-box"><span>TDS (Solids)</span><strong id="m-tds">-- ppm</strong></div>
                            <div class="metric-box"><span>Turbidity</span><strong id="m-turb">-- NTU</strong></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px; padding-top: 8px; border-top: 1px solid #162447;">
                            <span id="duty-cycle-badge" style="font-size: 11px; background: rgba(6, 214, 160, 0.15); color: #06d6a0; padding: 3px 8px; border-radius: 10px; font-weight: 500;">⏱️ Sampling Rate: 1 Hour (Normal)</span>
                            <small style="color: #8d99ae; font-size: 11px;">Telemetry Link: Active</small>
                        </div>
                    </div>
                    <div class="card">
                        <h4 style="margin: 0 0 10px 0; color: #48cae4;">Sensor Trends (Last 20 Readings)</h4>
                        <div class="chart-box"><canvas id="chartTds"></canvas></div>
                        <div class="chart-box"><canvas id="chartPh"></canvas></div>
                    </div>
                    <button class="btn" onclick="dispatchTicket()">Generate BBMP Field Inspection Ticket</button>

                    <!-- AI Lake Analyst Copilot -->
                    <div class="card" style="margin-top: 15px; border-color: #00f5d4;">
                        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                            <h4 style="margin: 0; color: #00f5d4;">🤖 AI Lake Analyst Copilot</h4>
                            <span style="font-size: 11px; background: rgba(0, 245, 212, 0.2); color: #00f5d4; padding: 2px 6px; border-radius: 4px;">KSPCB Grounded</span>
                        </div>
                        <div id="copilot-thread" style="background: #162447; border-radius: 6px; padding: 10px; max-height: 180px; overflow-y: auto; font-size: 13px; line-height: 1.5; color: #e0e6ed; margin-bottom: 10px; border: 1px solid #3a506b;">
                            <div style="color: #8d99ae; font-style: italic;">Ask me anything about this lake's live readings, KSPCB compliance, or action steps...</div>
                        </div>
                        
                        <!-- Quick Question Pills -->
                        <div style="display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px;">
                            <button class="pill-btn" onclick="askCopilot('Why is this lake in this status?')">Why this status?</button>
                            <button class="pill-btn" onclick="askCopilot('Is the water safe for fish & wildlife?')">Safe for fish?</button>
                            <button class="pill-btn" onclick="askCopilot('What immediate action should BBMP take?')">Action protocol</button>
                        </div>

                        <!-- Chat Input -->
                        <div style="display: flex; gap: 6px;">
                            <input id="copilot-input" type="text" placeholder="Ask about this lake..." style="flex: 1; background: #0b132b; border: 1px solid #3a506b; color: #fff; padding: 8px 10px; border-radius: 6px; font-size: 13px;" onkeypress="if(event.key==='Enter') sendCopilotText()" />
                            <button class="btn" style="width: auto; padding: 8px 14px;" onclick="sendCopilotText()">Ask</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            // 1. Initialize Map Focused on Quintessence Buoy #1 at Bellandur Lake
            let map = L.map('map-pane', { zoomControl: true }).setView([12.9348, 77.6740], 14);

            // 2. OpenStreetMap Layer (Zero Watermarks, Ultra Fast, 100% Free)
            L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }).addTo(map);

            function setMapTheme(theme) {
                document.getElementById('map-pane').className = theme;
            }

            // 3. Force container size recalculation to guarantee immediate rendering
            map.invalidateSize();
            setTimeout(() => { map.invalidateSize(); }, 250);
            setTimeout(() => { map.invalidateSize(); }, 750);

            let markers = {};
            let selectedLakeId = 'buoy1';
            let chartTdsInst = null;
            let chartPhInst = null;

            const colorMap = {
                'RED': '#ef233c',
                'ORANGE': '#ffb703',
                'GREEN': '#06d6a0',
                'YELLOW': '#ffd166'
            };

            // Single physical hardware buoy deployed at pilot station
            const defaultLakes = [
                { lake_id: 'buoy1', name: 'Quintessence IoT Buoy #1 (Bellandur Lake)', lat: 12.9348, lng: 77.6740, color: 'GREEN', lhi: 92.0, status: 'NORMAL' }
            ];

            // Outer radar beacon ping ring for Buoy #1
            let beaconRing = L.circleMarker([12.9348, 77.6740], {
                radius: 24,
                color: '#00f5d4',
                weight: 1.5,
                opacity: 0.7,
                fillColor: '#00f5d4',
                fillOpacity: 0.12
            }).addTo(map);

            function renderMarkers(lakes) {
                lakes.forEach(lake => {
                    let color = colorMap[lake.color] || '#06d6a0';
                    if (!markers[lake.lake_id]) {
                        let marker = L.circleMarker([lake.lat, lake.lng], {
                            radius: 13,
                            fillColor: color,
                            color: '#fff',
                            weight: 2.5,
                            opacity: 1,
                            fillOpacity: 0.9
                        }).addTo(map);

                        let timeLabel = lake.last_updated ? new Date(lake.last_updated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Live';
                        marker.bindTooltip(`<b>${lake.name}</b><br>LHI: ${lake.lhi} (${lake.status})<br><small style="color:#48cae4;">🕒 Measured: ${timeLabel}</small>`, { direction: 'top' });
                        marker.on('click', () => selectLake(lake.lake_id));
                        markers[lake.lake_id] = marker;
                    } else {
                        markers[lake.lake_id].setStyle({ fillColor: color });
                        let timeLabel = lake.last_updated ? new Date(lake.last_updated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Live';
                        markers[lake.lake_id].setTooltipContent(`<b>${lake.name}</b><br>LHI: ${lake.lhi} (${lake.status})<br><small style="color:#48cae4;">🕒 Measured: ${timeLabel}</small>`);
                        if (beaconRing) beaconRing.setStyle({ color: color, fillColor: color });
                    }
                });
            }

            // Render single buoy immediately
            renderMarkers(defaultLakes);

            function fetchLakes() {
                fetch('/api/lakes')
                    .then(res => res.json())
                    .then(lakes => {
                        if (lakes && lakes.length > 0) {
                            renderMarkers(lakes);
                        }
                    })
                    .catch(err => console.error("Error fetching lakes:", err));
            }

            function jumpToLake(lakeId) {
                selectLake(lakeId);
                let lake = defaultLakes.find(l => l.lake_id === lakeId);
                if (lake) {
                    map.setView([lake.lat, lake.lng], 14, { animate: true });
                }
            }

            function toggleSidebar() {
                let pane = document.getElementById('detail-pane');
                let btn = document.getElementById('toggle-sidebar-btn');
                if (pane.style.display === 'none') {
                    pane.style.display = 'block';
                    btn.style.display = 'none';
                } else {
                    pane.style.display = 'none';
                    btn.style.display = 'inline-block';
                }
                setTimeout(() => { map.invalidateSize(); }, 200);
            }

            function selectLake(lakeId) {
                selectedLakeId = lakeId;
                let pane = document.getElementById('detail-pane');
                pane.style.display = 'block';
                let btn = document.getElementById('toggle-sidebar-btn');
                if (btn) btn.style.display = 'none';
                setTimeout(() => { map.invalidateSize(); }, 150);

                document.getElementById('select-prompt').style.display = 'none';
                document.getElementById('lake-content').style.display = 'block';

                fetch(`/api/lake/${lakeId}`)
                    .then(res => res.json())
                    .then(data => {
                        let meta = data.meta;
                        let latest = data.latest;

                        document.getElementById('lake-title').innerText = meta.name;
                        document.getElementById('lake-ward').innerText = `Ward: ${meta.ward_name} (Ward No: ${meta.ward_no})`;
                        document.getElementById('lake-lhi').innerText = `LHI: ${meta.lhi}`;
                        document.getElementById('lake-lhi').style.color = colorMap[meta.color];

                        let alertBox = document.getElementById('alert-box');
                        alertBox.className = `alert-banner alert-${meta.color}`;
                        alertBox.innerText = latest ? latest.diagnosis : "No data recorded yet.";

                        if (latest) {
                            document.getElementById('m-temp').innerText = `${latest.temperature} °C`;
                            document.getElementById('m-ph').innerText = `${latest.ph}`;
                            document.getElementById('m-tds').innerText = `${latest.tds} ppm`;
                            document.getElementById('m-turb').innerText = `${latest.turbidity} NTU`;

                            if (latest.timestamp) {
                                let d = new Date(latest.timestamp);
                                let timeStr = !isNaN(d) ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : latest.timestamp;
                                let dateStr = !isNaN(d) ? d.toLocaleDateString([], { month: 'short', day: 'numeric' }) : "";
                                document.getElementById('lake-timestamp').innerHTML = `🕒 Sampled: <span style="color:#00f5d4;">${dateStr} ${timeStr}</span>`;
                            }

                            let dutyBadge = document.getElementById('duty-cycle-badge');
                            if (latest.status === 'CRITICAL' || latest.status === 'ALERT') {
                                dutyBadge.style.background = 'rgba(255, 183, 3, 0.2)';
                                dutyBadge.style.color = '#ffd166';
                                dutyBadge.innerText = '⚡ Adaptive Mode: Every 15 Mins (Anomaly Active)';
                            } else {
                                dutyBadge.style.background = 'rgba(6, 214, 160, 0.15)';
                                dutyBadge.style.color = '#06d6a0';
                                dutyBadge.innerText = '⏱️ Sampling Rate: Every 1 Hour (Normal)';
                            }
                        } else if (meta.last_updated) {
                            let d = new Date(meta.last_updated);
                            let timeStr = !isNaN(d) ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : meta.last_updated;
                            document.getElementById('lake-timestamp').innerHTML = `🕒 Sampled: <span style="color:#00f5d4;">${timeStr}</span>`;
                        } else {
                            document.getElementById('lake-timestamp').innerText = `🕒 No Telemetry Yet`;
                        }
                        loadCharts(lakeId);
                    });
            }

            function loadCharts(lakeId) {
                fetch(`/api/lake/${lakeId}/history?limit=20`)
                    .then(res => res.json())
                    .then(history => {
                        let labels = history.map((h, i) => {
                            if (h.timestamp) {
                                let d = new Date(h.timestamp);
                                return !isNaN(d) ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : `#${i + 1}`;
                            }
                            return `#${i + 1}`;
                        });
                        let tds = history.map(h => h.tds);
                        let turb = history.map(h => h.turbidity);
                        let ph = history.map(h => h.ph);

                        if (chartTdsInst) chartTdsInst.destroy();
                        if (chartPhInst) chartPhInst.destroy();

                        chartTdsInst = new Chart(document.getElementById('chartTds'), {
                            type: 'line',
                            data: {
                                labels: labels,
                                datasets: [
                                    { label: 'TDS (ppm)', data: tds, borderColor: '#00f5d4', tension: 0.3 },
                                    { label: 'Turbidity (NTU)', data: turb, borderColor: '#ffb703', tension: 0.3 }
                                ]
                            },
                            options: { responsive: true, maintainAspectRatio: false }
                        });

                        chartPhInst = new Chart(document.getElementById('chartPh'), {
                            type: 'line',
                            data: {
                                labels: labels,
                                datasets: [{ label: 'pH Level', data: ph, borderColor: '#ff758f', tension: 0.3 }]
                            },
                            options: { responsive: true, maintainAspectRatio: false }
                        });
                    });
            }

            function dispatchTicket() {
                if (!selectedLakeId) return;
                fetch('/api/ticket', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lake_id: selectedLakeId, reported_by: "BBMP Automated IoT Buoy" })
                })
                .then(res => res.json())
                .then(data => alert(`✅ Ticket Dispatched Successfully!\nTicket ID: ${data.ticket_id}\nAssigned to Ward Assistant Executive Engineer (AEE).`));
            }

            function askCopilot(question) {
                if (!selectedLakeId) return;
                let thread = document.getElementById('copilot-thread');
                thread.innerHTML += `<div style="margin-top: 8px; color: #00f5d4;"><b>You:</b> ${question}</div>`;
                thread.innerHTML += `<div id="copilot-loading" style="color: #8d99ae; font-style: italic; margin-top: 4px;">Analyzing live telemetry & KSPCB rules...</div>`;
                thread.scrollTop = thread.scrollHeight;

                fetch('/api/copilot', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lake_id: selectedLakeId, question: question })
                })
                .then(res => res.json())
                .then(data => {
                    let loader = document.getElementById('copilot-loading');
                    if (loader) loader.remove();
                    let formatted = data.answer.replace(/\\n/g, '<br>');
                    thread.innerHTML += `<div style="margin-top: 6px; padding: 8px; background: rgba(0, 245, 212, 0.08); border-left: 3px solid #00f5d4; border-radius: 4px;">${formatted}</div>`;
                    thread.scrollTop = thread.scrollHeight;
                });
            }

            function sendCopilotText() {
                let input = document.getElementById('copilot-input');
                let q = input.value.trim();
                if (!q) return;
                input.value = '';
                askCopilot(q);
            }

            fetchLakes();
            selectLake('buoy1');
            setInterval(fetchLakes, 3000);
            setInterval(() => { selectLake('buoy1'); }, 3000);
        </script>
    </body>
    </html>
    """

# ==========================================================
# 7. MAIN ENTRY POINT WITH AUTO-RELOAD
# ==========================================================
if __name__ == "__main__":
    import uvicorn
    print("\n=======================================================")
    print("🚀 BBMP & KSPCB Lake Health Monitoring Server Starting...")
    print("📍 Dashboard UI:    http://localhost:8000/dashboard")
    print("📖 API Docs (Docs): http://localhost:8000/docs")
    print("📡 Ingestion URL:   http://localhost:8000/api/telemetry")
    print("=======================================================\n")
    uvicorn.run("backend_server:app", host="0.0.0.0", port=8000, reload=True)
