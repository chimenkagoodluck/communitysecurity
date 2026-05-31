"""
First-time database setup + demo seeding.

Run once after install:
    python -m app.seed

Creates:
  - Admin user
  - 6 sample sources across SE Nigeria covering Camera / CCTV / Drone
  - Optional realistic synthetic detections so the dashboard is alive on first load
"""
import random
import secrets
from datetime import datetime, timedelta, timezone

from app.auth import hash_password
from app.db import Base, SessionLocal, engine
from app.models import (
    Alert, AlertSeverity, AlertStatus, Detection, ModelSource,
    Source, SourceCategory, SourceKind, SourceStatus, User, UserRole,
)


DEMO_SOURCES = [
    {
        "name": "Clifford University — Main Gate",
        "description": "Primary campus webcam — laptop default device",
        "kind": SourceKind.webcam, "category": SourceCategory.camera,
        "locator": "0",
        "location_lat": 5.4733, "location_lon": 7.5453,
        "location_label": "Clifford University, Owerrinta, Abia State",
    },
    {
        "name": "Aba — Ariaria Market CCTV",
        "description": "Hikvision IP camera at the main entrance",
        "kind": SourceKind.rtsp, "category": SourceCategory.cctv,
        "locator": "rtsp://demo.invalid/aba-ariaria",
        "location_lat": 5.1066, "location_lon": 7.3667,
        "location_label": "Ariaria International Market, Aba, Abia State",
        "cctv_vendor": "Hikvision", "has_ptz": True,
    },
    {
        "name": "Umuahia — Central Square",
        "description": "Dahua dome camera covering town centre",
        "kind": SourceKind.rtsp, "category": SourceCategory.cctv,
        "locator": "rtsp://demo.invalid/umuahia-central",
        "location_lat": 5.5247, "location_lon": 7.4944,
        "location_label": "Umuahia, Abia State",
        "cctv_vendor": "Dahua", "has_ptz": False,
    },
    {
        "name": "Owerri — Wetheral Patrol Drone",
        "description": "DJI Air 2S patrol drone over Wetheral Road",
        "kind": SourceKind.rtmp, "category": SourceCategory.drone,
        "locator": "rtmp://demo.invalid/owerri-drone",
        "location_lat": 5.4836, "location_lon": 7.0332,
        "location_label": "Owerri, Imo State",
        "drone_model": "DJI Air 2S", "altitude_m": 42.0,
    },
    {
        "name": "Enugu — Independence Layout CCTV",
        "description": "Axis network camera at residential entry",
        "kind": SourceKind.rtsp, "category": SourceCategory.cctv,
        "locator": "rtsp://demo.invalid/enugu-independence",
        "location_lat": 6.4584, "location_lon": 7.5464,
        "location_label": "Independence Layout, Enugu, Enugu State",
        "cctv_vendor": "Axis Communications", "has_ptz": True,
    },
    {
        "name": "Onitsha — Main Market Drone Survey",
        "description": "Roving drone patrol of Main Market perimeter",
        "kind": SourceKind.rtmp, "category": SourceCategory.drone,
        "locator": "rtmp://demo.invalid/onitsha-drone",
        "location_lat": 6.1664, "location_lon": 6.7969,
        "location_label": "Main Market, Onitsha, Anambra State",
        "drone_model": "DJI Mavic 3", "altitude_m": 55.0,
    },
]


def create_tables() -> None:
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print("[OK] Tables created (or already existed)")


def seed_admin() -> None:
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == "admin@cssa.app").first():
            print("[OK] Admin user already exists (admin@cssa.app)")
            return
        password = secrets.token_urlsafe(10)
        user = User(
            email="admin@cssa.app", full_name="System Administrator",
            hashed_password=hash_password(password), role=UserRole.admin,
        )
        db.add(user); db.commit()
        print("")
        print("=" * 64)
        print("  ADMIN USER CREATED — SAVE THIS PASSWORD NOW")
        print("=" * 64)
        print(f"  Email:    admin@cssa.app")
        print(f"  Password: {password}")
        print("=" * 64)
        print("")
    finally:
        db.close()


def seed_demo_sources() -> None:
    db = SessionLocal()
    try:
        if db.query(Source).count() > 0:
            print(f"[OK] Demo sources already present ({db.query(Source).count()})")
            return
        for entry in DEMO_SOURCES:
            db.add(Source(**entry, status=SourceStatus.idle, is_active=True))
        db.commit()
        print(f"[OK] Seeded {len(DEMO_SOURCES)} demo sources across SE Nigeria")
    finally:
        db.close()


def seed_synthetic_history() -> None:
    """Seed plausible historic detections + a couple of alerts so the dashboard is alive on first load."""
    db = SessionLocal()
    try:
        if db.query(Detection).count() > 100:
            print(f"[OK] Detection history present ({db.query(Detection).count()} rows)")
            return

        sources = db.query(Source).all()
        if not sources:
            return

        now = datetime.now(timezone.utc)
        rng = random.Random(42)
        threat_weights = [
            ("person", 0.65, 0.75, 0.95),
            ("vehicle", 0.25, 0.65, 0.92),
            ("motorcycle", 0.05, 0.60, 0.88),
            ("bicycle", 0.04, 0.55, 0.85),
            ("fire", 0.01, 0.45, 0.75),
        ]
        classes = [t[0] for t in threat_weights]
        weights = [t[1] for t in threat_weights]

        n_added = 0
        for src in sources:
            # Each source contributes 30-60 detections spread over the last 12 hours
            n_for_source = rng.randint(30, 60)
            for _ in range(n_for_source):
                cls = rng.choices(classes, weights=weights)[0]
                low, high = next((lo, hi) for (c, _w, lo, hi) in threat_weights if c == cls)
                conf = round(rng.uniform(low, high), 4)
                minutes_ago = rng.uniform(1, 720)  # up to 12h ago
                ts = now - timedelta(minutes=minutes_ago)

                det = Detection(
                    source_id=src.id, detected_at=ts,
                    model_source=ModelSource.spatial,
                    threat_class=cls, confidence=conf,
                    spatial_score=conf,
                    bbox={
                        "x": round(rng.uniform(0.05, 0.5), 3),
                        "y": round(rng.uniform(0.05, 0.5), 3),
                        "w": round(rng.uniform(0.2, 0.5), 3),
                        "h": round(rng.uniform(0.3, 0.7), 3),
                    },
                    lat=src.location_lat, lon=src.location_lon,
                )
                db.add(det)
                n_added += 1

        db.commit()
        print(f"[OK] Seeded {n_added} synthetic detections")

        # A couple of demo alerts
        if db.query(Alert).count() == 0:
            owerri = next((s for s in sources if "Owerri" in s.name), sources[0])
            aba = next((s for s in sources if "Aba" in s.name), sources[0])
            db.add(Alert(
                source_id=owerri.id, severity=AlertSeverity.high, status=AlertStatus.new,
                title=f"Vehicle convoy detected at {owerri.name}",
                message="Unusual vehicle density detected during drone patrol. Confidence 89%.",
                lat=owerri.location_lat, lon=owerri.location_lon,
                dispatched_at=now - timedelta(minutes=12),
            ))
            db.add(Alert(
                source_id=aba.id, severity=AlertSeverity.medium, status=AlertStatus.new,
                title=f"Crowd gathering at {aba.name}",
                message="Person density above baseline at market gate. Confidence 76%.",
                lat=aba.location_lat, lon=aba.location_lon,
                dispatched_at=now - timedelta(minutes=34),
            ))
            db.add(Alert(
                source_id=sources[0].id, severity=AlertSeverity.low, status=AlertStatus.acknowledged,
                title=f"Routine pedestrian activity",
                message="Normal pedestrian movement near campus gate.",
                lat=sources[0].location_lat, lon=sources[0].location_lon,
                dispatched_at=now - timedelta(hours=2),
            ))
            db.commit()
            print("[OK] Seeded 3 demo alerts")
    finally:
        db.close()


def seed_fresh() -> str:
    """
    Seed a freshly-wiped database and return the new admin password.
    Called by the admin reset API so the password can be returned in the response.
    """
    db = SessionLocal()
    try:
        password = secrets.token_urlsafe(10)
        db.add(User(
            email="admin@cssa.app", full_name="System Administrator",
            hashed_password=hash_password(password), role=UserRole.admin,
        ))
        db.commit()
    finally:
        db.close()
    seed_demo_sources()
    seed_synthetic_history()
    return password


if __name__ == "__main__":
    create_tables()
    seed_admin()
    seed_demo_sources()
    seed_synthetic_history()
    print("\nSetup complete. Run:  python run.py")
    print("Then open:  http://localhost:8000")
