"""Auth endpoints + dependency."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import create_access_token, decode_token, hash_password, verify_password
from app.db import get_db
from app.models import User, UserRole
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserOut

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    request: Request = None,
    token_query: Optional[str] = Query(None, alias="token"),
) -> str:
    """
    Accept token from any of:
      - Authorization: Bearer <token>     (default for fetch/XHR)
      - ?token=<token>                    (for <img src> live video — browser can't set headers)
    """
    if credentials and credentials.credentials:
        return credentials.credentials
    if token_query:
        return token_query
    raise HTTPException(status_code=401, detail="Not authenticated")


def get_current_user(
    token: str = Depends(_resolve_token),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_role(*roles: UserRole):
    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return _checker


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    """
    Self-service signup. The database creates its own tables on startup, so the
    first person to register becomes the administrator (bootstrap); everyone who
    signs up after that is an operator. Returns a token so the user is logged in
    immediately. Role is assigned server-side and cannot be chosen by the client.
    """
    email = payload.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    role = UserRole.admin if db.query(User).count() == 0 else UserRole.operator
    user = User(
        email=email,
        full_name=(payload.full_name or "").strip() or None,
        hashed_password=hash_password(payload.password),
        role=role,
    )
    db.add(user); db.commit(); db.refresh(user)

    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(
        access_token=token, role=user.role.value,
        user_id=user.id, full_name=user.full_name,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive account")
    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(
        access_token=token, role=user.role.value,
        user_id=user.id, full_name=user.full_name,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
