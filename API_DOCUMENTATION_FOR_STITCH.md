# BBMP Lake Health Monitoring: API Documentation for Frontend (Stitch)

**Base URL:** `http://localhost:8000` (or `http://<your-laptop-ip>:8000`)
**CORS:** Enabled for all origins (`*`)

---

## 1. Get All Monitored Bengaluru Lakes (For the Master Map)
Returns all lakes in Bengaluru with coordinates, current Lake Health Index (LHI: 0–100), and color status for markers.

* **Endpoint:** `GET /api/lakes`
* **Response `200 OK`:**
```json
[
  {
    "lake_id": "bellandur",
    "name": "Bellandur Lake",
    "ward_name": "Mahadevapura",
    "ward_no": 150,
    "lat": 12.9348,
    "lng": 77.6740,
    "status": "CRITICAL",
    "color": "RED",
    "lhi": 32.0,
    "last_updated": "2026-11-20T17:00:00"
  },
  {
    "lake_id": "varthur",
    "name": "Varthur Lake",
    "ward_name": "Varthur",
    "ward_no": 149,
    "lat": 12.9406,
    "lng": 77.7466,
    "status": "ALERT",
    "color": "ORANGE",
    "lhi": 64.5,
    "last_updated": "2026-11-20T17:00:00"
  },
  {
    "lake_id": "sankey",
    "name": "Sankey Tank",
    "ward_name": "Aramane Nagar",
    "ward_no": 35,
    "lat": 13.0068,
    "lng": 77.5753,
    "status": "NORMAL",
    "color": "GREEN",
    "lhi": 92.0,
    "last_updated": "2026-11-20T17:00:00"
  }
]
```

---

## 2. Get Single Lake Details & Current AI Diagnosis
Returns metadata, current readings, and the AI diagnostic explanation when a user clicks a lake pin.

* **Endpoint:** `GET /api/lake/{lake_id}` (e.g. `/api/lake/bellandur`)
* **Response `200 OK`:**
```json
{
  "meta": {
    "lake_id": "bellandur",
    "name": "Bellandur Lake",
    "ward_name": "Mahadevapura",
    "ward_no": 150,
    "lat": 12.9348,
    "lng": 77.6740,
    "status": "CRITICAL",
    "color": "RED",
    "lhi": 32.0
  },
  "latest": {
    "temperature": 24.5,
    "ph": 7.3,
    "tds": 710.2,
    "turbidity": 54.8,
    "lhi": 32.0,
    "status": "CRITICAL",
    "color": "RED",
    "diagnosis": "Raw Sewage / Sullage Inflow detected (Concurrent TDS and Turbidity surge). Sensor drift ruled out."
  }
}
```

---

## 3. Get Sensor Time-Series History (For Graphs)
Returns chronological readings for plotting the 4 sensor graphs: Temperature, pH, TDS, and Turbidity.

* **Endpoint:** `GET /api/lake/{lake_id}/history?limit=50`
* **Response `200 OK`:**
```json
[
  {
    "timestamp": "2026-11-20T17:01:10",
    "temperature": 24.2,
    "ph": 7.4,
    "tds": 250.0,
    "turbidity": 8.0,
    "lhi": 92.0,
    "status": "NORMAL",
    "color": "GREEN"
  },
  {
    "timestamp": "2026-11-20T17:01:15",
    "temperature": 24.3,
    "ph": 7.3,
    "tds": 680.0,
    "turbidity": 48.0,
    "lhi": 34.0,
    "status": "CRITICAL",
    "color": "RED"
  }
]
```

---

## 4. Ingest Telemetry (From ESP32 or Simulator)
Used by the hardware to post sensor packets.

* **Endpoint:** `POST /api/telemetry`
* **Payload:**
```json
{
  "lake_id": "bellandur",
  "temp": 24.5,
  "ph": 7.2,
  "tds": 280.0,
  "turbidity": 8.5
}
```

---

## 5. Dispatch Field Inspection Ticket
Creates an official BBMP ticket for the Ward Assistant Executive Engineer (AEE).

* **Endpoint:** `POST /api/ticket`
* **Payload:**
```json
{
  "lake_id": "bellandur",
  "reported_by": "BBMP Web Portal",
  "notes": "Severe sewage odor and foam reported by locals."
}
```
* **Response `200 OK`:**
```json
{
  "ticket_id": "BBMP-W11201705",
  "lake_id": "bellandur",
  "created_at": "2026-11-20T17:05:00",
  "status": "DISPATCHED",
  "message": "Inspection ticket BBMP-W11201705 created and dispatched to Ward Assistant Executive Engineer (AEE)."
}
```

---

## 6. Lake AI Analyst Copilot (Interactive Environmental Q&A)
Allows BBMP officers to ask natural questions about the lake's condition. The AI pulls live database telemetry, checks KSPCB limits, and explains the issue with recommended actions.

* **Endpoint:** `POST /api/copilot`
* **Payload:**
```json
{
  "lake_id": "bellandur",
  "question": "Why is this lake in red alert and what action should we take?"
}
```
* **Response `200 OK`:**
```json
{
  "lake_id": "bellandur",
  "lake_name": "Bellandur Lake",
  "question": "Why is this lake in red alert and what action should we take?",
  "answer": "🚨 Bellandur Lake is in Critical Status (LHI: 30/100) due to confirmed Raw Sewage Influx.\n\n• TDS is 710 ppm (KSPCB limit is 280 ppm): Excessive dissolved mineral salts, urine, and detergents.\n• Turbidity is 52 NTU (KSPCB limit is 8 NTU): High volume of suspended organic sludge.\n• Recommended Action: Dispatch Ward 150 team to inspect inlet stormwater culvert #2 immediately.",
  "timestamp": "2026-11-21T11:58:00"
}
```
