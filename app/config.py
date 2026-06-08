
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "Community Security Alert System"
    APP_SHORT: str = "CSSA"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "please-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    DATABASE_URL: str = "sqlite:///./data/cssa.db"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    MAP_CENTER_LAT: float = 5.4836
    MAP_CENTER_LON: float = 7.0332
    MAP_DEFAULT_ZOOM: int = 8

    SPATIAL_CONFIDENCE_THRESHOLD: float = 0.40
    TEMPORAL_ANOMALY_THRESHOLD: float = 0.55
    FUSION_ALERT_THRESHOLD: float = 0.55

   
    WEAPON_MODEL_PATH: str = "weapons.pt"
   
    WEAPON_CONFIDENCE_THRESHOLD: float = 0.50

   
    WEAPON_REQUIRE_PERSON: bool = True
   
    WEAPON_PERSIST_WINDOW: int = 6
    WEAPON_PERSIST_MIN: int = 4
    WEAPON_MATCH_DIST: float = 0.12

    
    WEAPON_IMAGE_CONFIDENCE_THRESHOLD: float = 0.50
    WEAPON_IMAGE_SCALES: list[int] = [640]
    WEAPON_IMAGE_TTA: bool = False

    FUSION_ALPHA: float = 0.45
    FUSION_BETA: float = 0.40
    FUSION_GAMMA: float = 0.15

    INGEST_TARGET_FPS: int = 3
    STREAM_FPS: int = 10  
   
    VIDEO_ANALYZE_FPS: int = 3      
    VIDEO_MAX_SECONDS: int = 60     

   
    CROWD_MIN_PERSONS: int = 4
    CROWD_PROXIMITY_DIST: float = 0.45

    HOTSPOT_EPS_METERS: float = 300.0
    HOTSPOT_MIN_SAMPLES: int = 3
    HOTSPOT_WINDOW_HOURS: int = 6

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "Community Security Alert"
    SMTP_FROM_EMAIL: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
