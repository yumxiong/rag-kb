import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt import ExpiredSignatureError, InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel

from app.core.config import settings
from app.core.rate_limiter import limiter

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
ph = PasswordHash.recommended()
logger = logging.getLogger(__name__)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def require_admin(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        secret = settings.get_jwt_secret()
    except RuntimeError as exc:
        logger.error(f"Admin auth misconfigured: {exc}")
        raise HTTPException(
            status_code=500, detail="Admin authentication is not configured"
        )

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "role"]},
        )
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return claims


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    try:
        password_hash = settings.get_admin_password_hash()
        secret = settings.get_jwt_secret()
    except RuntimeError as exc:
        logger.error(f"Admin auth misconfigured: {exc}")
        raise HTTPException(
            status_code=500, detail="Admin authentication is not configured"
        )

    if form.username != settings.admin_username:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        password_ok = ph.verify(form.password, password_hash)
    except Exception:
        logger.error("Invalid admin password hash format")
        raise HTTPException(
            status_code=500, detail="Admin authentication is not configured"
        )

    if not password_ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    exp = datetime.now(timezone.utc) + timedelta(minutes=30)
    token = jwt.encode(
        {
            "sub": form.username,
            "exp": exp,
            "role": "admin",
            "iat": datetime.now(timezone.utc),
        },
        secret,
        algorithm=settings.jwt_algorithm,
    )

    return TokenResponse(access_token=token)
