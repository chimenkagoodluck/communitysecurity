# CSSA — Defense Quickstart

## Install (5 minutes)

Open PowerShell in this folder (`cssa`), with your existing `.venv` activated:

```powershell
# Same venv as before — no new packages needed
pip install -r requirements.txt

# Create database + admin user + 6 demo SE Nigeria cameras
python -m app.seed
```
  Email:    admin@cssa.app
  Password: r9PiqxIU_ZB-zw
**The seeder prints an admin password. COPY IT IMMEDIATELY** — it's randomly generated and shown only once.

```
================================================================
  ADMIN USER CREATED — SAVE THIS PASSWORD NOW
================================================================
  Email:    admin@cssa.app
  Password: <copy this>
================================================================
```

## Run

```powershell
python run.py
```

Open **http://localhost:8000** in your browser.

## The 7 screens

| URL | What it shows |
|-----|---------------|
| `/login` | Strict login — uses admin@cssa.app + the seeded password |
| `/dashboard` | **Command Center** — map, KPIs, detection feed, alerts ticker |
| `/sources` | Grid of all 6 sources, filterable by Camera / CCTV / Drone |
| `/sources/{id}` | **Live video** + source-specific telemetry + detection log |
| `/sources/new` | 3-step wizard: type → config → map-pick location |
| `/alerts` | Alert history table with severity filter + acknowledge |
| `/admin` | System health, users, fusion weights, metrics |

## Defense walkthrough (recommended)

1. **Login screen** — show strict auth, sign in with the seeded admin password
2. **Command Center (`/dashboard`)** — show:
   - 6 KPI tiles populated from seeded data
   - Map of SE Nigeria with all 6 sources color-coded by category
   - Recent detections feed on the right
   - Active alert strip at the top (a demo high-severity alert is already seeded)
3. **Sources page (`/sources`)** — show all 6 sources, click the filter buttons (Camera / CCTV / Drone) — note each category has different metadata
4. **Click "Clifford University — Main Gate"** to open `/sources/{id}`. This is a **camera** type — you'll see:
   - Live video frame (showing "NO SIGNAL" placeholder)
   - Camera-specific telemetry (Device, Resolution, Framerate)
   - Source info panel + mini-map
5. **Click "▶ Start Monitoring"** — YOLOv8 starts running on your webcam. The "NO SIGNAL" turns into your live face with bounding boxes annotated in real time. The detection log fills with `person` entries.
6. **Click stop**, navigate to a **CCTV source** (e.g. Aba Ariaria Market). Show how the telemetry tiles change to Signal / Vendor / PTZ / Codec.
7. **Click a Drone source** (Owerri Wetheral). Telemetry now shows Altitude / Drone Model / Battery / GPS Lock / Flight Mode.
8. **Add Source wizard** (`/sources/new`) — walk through choosing type → configuring → pinning on map.
9. **Alerts page** — show 3 seeded alerts of different severities, acknowledge one.
10. **Admin page** — show system health, fusion weights (α, β, γ), per-class detection chart.

## What to say in the defense

- **"This is a source-agnostic command and control system."** The same pipeline handles webcams for testing, RTSP CCTV for fixed surveillance, and RTMP drone feeds for aerial patrol.
- **"The system uses pretrained YOLOv8n on COCO for spatial detection — no custom training required."** Picks up people, vehicles, motorcycles, bicycles. Fire detection uses a complementary HSV + temporal flicker heuristic.
- **"Detections are geo-tagged automatically using each source's registered location."** Every detection carries its lat/lon, which is how the heat map and hotspot detection (Day 4) work.
- **"Auto-alerting triggers when confidence exceeds class-specific thresholds."** 50% for fire (critical), 85% for person (low priority unless very high confidence), 80% for vehicle (medium).
- **"The fusion equation `T = α·S_A + β·S_B + γ·S_A·S_B` combines spatial and temporal scores."** Currently α=0.45, β=0.40, γ=0.15. The temporal half is Day 3 work.

## What's stubbed for the defense

Be honest if asked:
- **Live video for CCTV/Drone sources** shows "NO SIGNAL" because real RTSP/RTMP endpoints aren't reachable from your laptop. Only the webcam ("Clifford University — Main Gate") produces actual live video.
- **Battery / Signal / GPS Lock values on the source detail pages** are display placeholders showing what real telemetry would look like. Real drone telemetry needs the DJI SRT parser (already written, integrated Day 4).
- **Temporal model (violence/fighting detection)** — Day 3 work, fields exist in DB schema (`temporal_score`, `fused_score`), currently NULL.

## Troubleshooting on defense day

| Symptom | Fix |
|---------|-----|
| "Invalid credentials" on login | Re-run `python -m app.seed` to print a fresh password (delete `data/cssa.db` first for a clean reset) |
| Webcam doesn't start | Make sure no other app (Zoom, Teams) has the camera open |
| Live video says "NO SIGNAL" forever | YOLOv8 weights download on first run — wait for "Downloading yolov8n.pt" to finish in the terminal |
| Browser shows blank page | Refresh with Ctrl+F5 (clears cached old assets) |
| Some pages 401 | Click your name in the sidebar → sign out → sign back in |

## File map

```
cssa/
├── app/
│   ├── api/        ← HTTP API routes (auth, sources, detections, alerts, admin, ingest)
│   ├── ingest/     ← Video reader, frame store, ingestion worker
│   ├── ml/         ← YOLOv8 wrapper + fire detector
│   ├── main.py     ← FastAPI app + page routes
│   ├── seed.py     ← Demo data seeder
│   └── models.py   ← SQLAlchemy ORM
├── static/         ← CSS + JS
├── templates/      ← Jinja2 HTML
├── data/cssa.db    ← SQLite (created on first run)
├── run.py          ← Server launcher
└── requirements.txt
```

Good luck tomorrow.
