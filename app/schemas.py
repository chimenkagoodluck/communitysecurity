from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- Auth ---
class UserCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    password: str = Field(min_length=8)
    role: str = "operator"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: EmailStr
    full_name: Optional[str]
    role: str
    is_active: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    full_name: Optional[str] = None


# --- Sources ---
class SourceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    kind: str
    category: str
    locator: str
    location_lat: float = Field(ge=-90, le=90)
    location_lon: float = Field(ge=-180, le=180)
    location_label: Optional[str] = None
    drone_model: Optional[str] = None
    cctv_vendor: Optional[str] = None
    altitude_m: Optional[float] = None
    has_ptz: bool = False
    notes: Optional[str] = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: Optional[str]
    kind: str
    category: str
    locator: str
    location_lat: float
    location_lon: float
    location_label: Optional[str]
    drone_model: Optional[str] = None
    cctv_vendor: Optional[str] = None
    altitude_m: Optional[float] = None
    has_ptz: bool = False
    notes: Optional[str] = None
    status: str
    is_active: bool
    last_frame_at: Optional[datetime] = None
    last_error: Optional[str] = None
