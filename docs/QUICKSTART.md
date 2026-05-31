# Quickstart — Windows, 8GB RAM, no Docker

This gets you from a fresh download to a running dashboard in about 15 minutes
(most of that is `pip install`).

---

## Prerequisites

- **Python 3.11** (3.12 also works; avoid 3.13 — some ML libs lag)
  Check: `python --version`
- ~3 GB free disk (PyTorch CPU wheel is the chunky one)
- Webcam access permission for your Windows user (Settings → Privacy → Camera)

---

## Steps

### 1. Open a Command Prompt in the project folder

```cmd
cd C:\Users\<you>\Downloads\cssa
```

### 2. Create a virtual environment and activate it

```cmd
python -m venv .venv
.venv\Scripts\activate
```

You should see `(.venv)` at the start of your prompt.

### 3. Install dependencies

```cmd
pip install --upgrade pip
pip install -r requirements.txt
```

This takes ~5–10 minutes the first time. PyTorch alone is ~200 MB.

> **If you hit a build error on `bcrypt`** (rare on Windows): run
> `pip install passlib==1.7.4 bcrypt==4.0.1 --no-deps` then re-run the full install.

### 4. Configure

```cmd
copy .env.example .env
```

Defaults are fine. You can leave SMTP empty for now (alerts come Day 6).

### 5. Initialize the database + seed demo data

```cmd
python -m app.seed
```

Output will include something like:

```
============================================================
  ADMIN USER CREATED — SAVE THIS PASSWORD NOW
============================================================
  Email:    admin@cssa.app
  Password: x7gK3pQ9-_mV2nLr
============================================================

✓ Seeded 6 demo cameras across SE Nigeria
    - Clifford University — Main Gate           (5.4733, 7.5453)
    - Aba — Ariaria Market                      (5.1066, 7.3667)
    - Umuahia — Central                         (5.5247, 7.4944)
    - Owerri — Wetheral Road                    (5.4836, 7.0332)
    - Enugu — Independence Layout               (6.4584, 7.5464)
    - Onitsha — Main Market                     (6.1664, 6.7969)
```

**Copy that password somewhere safe** — it won't be shown again.

### 6. Start the server

```cmd
python run.py
```

You'll see uvicorn logs. The app is live.

---

## Verify

Open these three URLs in your browser:

1. **http://localhost:8000/** — Dashboard. You should see a dark map of SE Nigeria
   with 6 colored pins (1 cyan = webcam, 5 green = RTSP placeholders).
   Click any pin to see its details.

2. **http://localhost:8000/docs** — Swagger API. Try:
   - `POST /api/auth/login` → log in with `admin@cssa.app` + your password
   - Click the green **Authorize** button at top right, paste the access_token
   - `GET /api/sources/` → should return the 6 seeded sources
   - `POST /api/sources/{id}/probe` on the Clifford University source → if your
     laptop webcam works, this returns `"ok": true` with the resolution

3. **http://localhost:8000/healthz** — should return `{"status": "ok", ...}`

If all three pass → **Day 1 is green**, ship it forward.

---

## Common issues

**`ModuleNotFoundError: No module named 'app'`**
Activate the venv first: `.venv\Scripts\activate`. Then run from the project root
(the folder that contains `run.py`).

**Webcam probe returns `ok: false`**
Either Windows is blocking camera access (Settings → Privacy → Camera → allow
desktop apps) or another app is using the camera (close Zoom/Teams/Skype etc.).

**`Address already in use` on port 8000**
Run `python run.py --port 8080` instead, then visit http://localhost:8080.

**`pip install` is slow / hanging**
PyTorch is ~200 MB; that's the one taking time. If your connection is unstable,
retry: `pip install -r requirements.txt`.

---

## Day-to-day commands

```cmd
.venv\Scripts\activate         # always activate first
python run.py                  # run the server
python -m app.seed             # safe to re-run; idempotent
```

To stop: `Ctrl+C` in the terminal running uvicorn.

---

## What's next (Day 2)

I'll add:
- `app/ml/spatial.py` — YOLOv8n inference wrapper (pretrained, ~6 MB auto-download)
- `app/ml/fire.py` — HSV color-based fire detector
- `app/ingest/worker.py` — background per-source ingestion (runs YOLO on frames as they arrive)
- The first real detections appearing on the map as you point the webcam at things

Your laptop webcam will start detecting people and vehicles in real time.
