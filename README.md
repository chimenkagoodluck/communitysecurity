# Community Security Alert System (CSSA)

A web-based surveillance command center that pulls in live video from cameras,
drones, and CCTV feeds, runs AI-powered threat detection on each frame, and
raises geo-tagged alerts on a live map — all from a single browser tab.

Built as a final-year B.Sc. Computer Science project at Clifford University,
Owerrinta. Authors: Chimenka Goodluck Uchechi, Daniel Reigneth Chinemerem,
Onyeobia Samuel Tochukwu. Supervisor: Dr. Ndubuisi Odikwa.

---

## Before you start

You need **Python 3.11** installed on your machine. You can download it from
python.org — during installation, make sure you tick *"Add Python to PATH"*.

Everything else (the web framework, the AI model, OpenCV) gets installed
automatically in the next step. No Docker, no PostgreSQL, no Node.js needed.

The system is designed to run on a regular Windows laptop with at least 8 GB
of RAM. The AI model uses your CPU — no GPU required.

---

## Installation

Open PowerShell in the project folder and run the setup script:

```powershell
.\setup.bat
```

That single command creates a Python virtual environment, installs all
dependencies, and creates an **empty** database (just the tables). There are no
demo cameras, sample detections, or pre-made accounts. The first time you open
the app you **sign up** to create your account — the first account created
becomes the administrator. Everything else (sources, detections, alerts) appears
only through real use of the app.

If you ever need a clean slate (new password, fresh data), you can reset
everything from inside the Admin page without touching the terminal.

---

## Running the app

```powershell
.\run.bat
```

Then open **http://localhost:8000** in your browser. The first time, click
**Create one** on the login page to sign up — the first account becomes the
administrator. After that, sign in with those credentials.

> The first time you start monitoring a webcam, the camera can take 30–45 seconds
> to initialise. This is a Windows driver warm-up and only happens once per
> session — after that, stopping and restarting is almost instant.

---

## What you can do

**Dashboard** (`/dashboard`) gives you the full picture: a live map of all
registered sources, a running count of detections and active alerts, and a
feed of recent activity. Everything refreshes automatically every few seconds.

**Sources** (`/sources`) lists every camera, CCTV feed, and drone registered
in the system. Click any source to open its detail page, where you can watch
the live annotated video feed and see detections as they happen. For the
webcam source, monitoring starts automatically when you open the page.

**Add Source** (`/sources/new`) walks you through a three-step wizard to
register a new video source: pick the type (Camera / CCTV / Drone), fill in
the connection details, then pin the location on the map.

**Alerts** (`/alerts`) shows every alert the system has raised, filtered by
severity or status. You can acknowledge alerts individually to mark them as
reviewed.

**Admin** (`/admin`) shows system health, detection statistics, and the fusion
equation weights. It also has a Data Management section where you can:

- Create a named backup of the entire database at any point
- Restore any previous backup (the current database is saved first automatically)
- Reset everything and start fresh with new demo data and a new admin password

---

## Troubleshooting

**"Invalid credentials" on the login page**
Make sure you signed up first (the **Create one** link on the login page). If you
have lost access entirely and want to start over, an existing admin can open the
Admin page → Data Management → **Reset (Empty Database)**; this wipes everything
and sends you to sign up again, where the first new account becomes the admin.

**Webcam shows "Initialising Camera" for a long time after the page loads**
The first open of a webcam on Windows initialises the driver, which can take
30–45 seconds. The video feed appears automatically once it is ready — you do
not need to click anything.

**Another app has the camera (Zoom, Teams, OBS)**
Only one application can use a webcam at a time on Windows. Close the other
app and refresh the source page.

**The page is blank or shows old data after a reset**
Hold Shift and press F5 to do a full reload. The browser may have cached the
previous session's login token.

**The app crashes or the server stops responding**
The terminal window shows the full error log. The most common cause is another
process already using port 8000. You can change the port by editing `.env`
and adding `PORT=8080` (or any free port), then restarting.

---

## Project structure

```
cssa/
├── app/
│   ├── api/          Route handlers (auth, sources, detections, alerts, admin)
│   ├── ingest/       Camera reader, frame buffer, ingestion worker thread
│   ├── ml/           YOLOv8 spatial detector and fire heuristic
│   ├── main.py       FastAPI application entry point
│   └── seed.py       Demo data seeder
├── templates/        HTML pages (Jinja2)
├── static/           CSS and JavaScript
├── data/             SQLite database and backups (created on first run)
├── setup.bat         First-time installation script
├── run.bat           Start the server
└── requirements.txt  Python package list
```
