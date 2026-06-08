
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

from app.api import admin, alerts, analyze, auth, detections, ingest, sources
from app.config import PROJECT_ROOT, settings
from app.db import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} ({settings.APP_ENV})")
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database ready at {settings.DATABASE_URL}")
   
    import anyio
    from app.ml.yolo import get_model
    try:
        await anyio.to_thread.run_sync(get_model)
        logger.info("YOLOv8n model loaded")
    except Exception as exc:
        logger.warning(f"YOLO preload failed (will load on first inference): {exc}")
    # Weapon model (optional). Logs clearly whether it loaded or fell back to COCO.
    from app.ml.weapon import get_model as get_weapon_model
    try:
        await anyio.to_thread.run_sync(get_weapon_model)
    except Exception as exc:
        logger.warning(f"Weapon model preload failed: {exc}")
    yield
    logger.info("Shutting down")


app = FastAPI(title=settings.APP_NAME, version="2.0.0", debug=settings.DEBUG, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else [],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")


_MEDIA_DIR = PROJECT_ROOT / "data" / "analyzed"
_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_MEDIA_DIR)), name="media")

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))


# ---- API routers ----
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(detections.router, prefix="/api/detections", tags=["detections"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(analyze.router, prefix="/api/analyze", tags=["analyze"])


# ---- Page routes ----

def page_ctx(page: str, **extra):
    return {
        "app_name": settings.APP_NAME,
        "app_short": settings.APP_SHORT,
        "active_page": page,
        "map_center_lat": settings.MAP_CENTER_LAT,
        "map_center_lon": settings.MAP_CENTER_LON,
        "map_zoom": settings.MAP_DEFAULT_ZOOM,
        **extra,
    }


@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", page_ctx("login"))


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse(request, "signup.html", page_ctx("signup"))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", page_ctx("dashboard"))


@app.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    return templates.TemplateResponse(request, "sources.html", page_ctx("sources"))


@app.get("/sources/new", response_class=HTMLResponse)
async def new_source_page(request: Request):
    return templates.TemplateResponse(request, "add_source.html", page_ctx("sources"))


@app.get("/analyze/image", response_class=HTMLResponse)
async def analyze_image_page(request: Request):
    return templates.TemplateResponse(request, "analyze_image.html", page_ctx("analyze_image"))


@app.get("/analyze/video", response_class=HTMLResponse)
async def analyze_video_page(request: Request):
    return templates.TemplateResponse(request, "analyze_video.html", page_ctx("analyze_video"))


@app.get("/sources/{source_id}", response_class=HTMLResponse)
async def source_detail_page(request: Request, source_id: str):
    return templates.TemplateResponse(
        request, "source_detail.html", page_ctx("sources", source_id=source_id),
    )


@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    return templates.TemplateResponse(request, "alerts.html", page_ctx("alerts"))


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse(request, "admin.html", page_ctx("admin"))


@app.get("/healthz")
async def healthz():
    return JSONResponse({"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV})
