
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum as SAEnum, Float, ForeignKey,
    Integer, JSON, String, Text,
)
from sqlalchemy.orm import relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ----- Enums -----

class UserRole(str, enum.Enum):
    operator = "operator"
    admin = "admin"
    community = "community"


class SourceKind(str, enum.Enum):
    """
    Internal kinds. UI groups them as:
      'camera'  -> webcam
      'cctv'    -> rtsp
      'drone'   -> rtmp or file (drone footage)
    """
    webcam = "webcam"
    rtsp = "rtsp"
    rtmp = "rtmp"
    file = "file"


class SourceCategory(str, enum.Enum):
    """User-facing source category — what the UI shows."""
    camera = "camera"
    cctv = "cctv"
    drone = "drone"


class SourceStatus(str, enum.Enum):
    idle = "idle"
    streaming = "streaming"
    error = "error"


class ModelSource(str, enum.Enum):
    spatial = "spatial"
    temporal = "temporal"
    fused = "fused"


class AlertSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AlertStatus(str, enum.Enum):
    new = "new"
    acknowledged = "acknowledged"
    resolved = "resolved"


class GeofenceSensitivity(str, enum.Enum):
    normal = "normal"
    high = "high"
    critical = "critical"


# ----- Tables -----

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255))
    hashed_password = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.operator)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class Source(Base):
    __tablename__ = "sources"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(120), nullable=False)
    description = Column(Text)

    kind = Column(SAEnum(SourceKind), nullable=False)
    category = Column(SAEnum(SourceCategory), nullable=False, default=SourceCategory.camera)
    locator = Column(String(500), nullable=False)

    location_lat = Column(Float, nullable=False)
    location_lon = Column(Float, nullable=False)
    location_label = Column(String(200))

    # Optional metadata used by the UI
    drone_model = Column(String(120))      # e.g. "DJI Air 2S"
    cctv_vendor = Column(String(120))      # e.g. "Hikvision"
    altitude_m = Column(Float)             # for drones
    has_ptz = Column(Boolean, default=False)
    notes = Column(Text)

    status = Column(SAEnum(SourceStatus), default=SourceStatus.idle, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_frame_at = Column(DateTime(timezone=True))
    last_error = Column(Text)

    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    detections = relationship("Detection", back_populates="source", cascade="all, delete-orphan")


class Detection(Base):
    __tablename__ = "detections"

    id = Column(String(36), primary_key=True, default=_uuid)
    source_id = Column(String(36), ForeignKey("sources.id"), nullable=False, index=True)
    detected_at = Column(DateTime(timezone=True), default=_now, nullable=False, index=True)

    model_source = Column(SAEnum(ModelSource), nullable=False, index=True)
    threat_class = Column(String(80), nullable=False)
    confidence = Column(Float, nullable=False)

    spatial_score = Column(Float)
    temporal_score = Column(Float)
    fused_score = Column(Float)

    bbox = Column(JSON)
    lat = Column(Float)
    lon = Column(Float)
    frame_path = Column(String(500))

    source = relationship("Source", back_populates="detections")
    alert = relationship("Alert", back_populates="detection", uselist=False)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True, default=_uuid)
    detection_id = Column(String(36), ForeignKey("detections.id"), nullable=True, unique=True)
    source_id = Column(String(36), ForeignKey("sources.id"), nullable=True)

    severity = Column(SAEnum(AlertSeverity), nullable=False)
    status = Column(SAEnum(AlertStatus), default=AlertStatus.new, nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)

    lat = Column(Float)
    lon = Column(Float)

    dispatched_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    acknowledged_by = Column(String(36), ForeignKey("users.id"))
    acknowledged_at = Column(DateTime(timezone=True))

    detection = relationship("Detection", back_populates="alert")


class Geofence(Base):
    __tablename__ = "geofences"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(120), nullable=False)
    description = Column(Text)
    sensitivity = Column(SAEnum(GeofenceSensitivity), default=GeofenceSensitivity.normal, nullable=False)
    polygon = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(40))
    area_polygon = Column(JSON)
    is_active = Column(Boolean, default=True, nullable=False)
    min_severity = Column(SAEnum(AlertSeverity), default=AlertSeverity.medium, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
