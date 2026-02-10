"""Mini App auth: Telegram initData validation + JWT."""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import parse_qs, unquote

import jwt
from fastapi import Depends, HTTPException, Request

from src.config import get_settings
from src.database.connection import get_session
from src.database.repository import get_user_by_telegram_id
from src.database.models import User
from src.utils.logger import logger


def _get_jwt_secret() -> str:
    """Get JWT secret — miniapp_jwt_secret or fallback to secret_key."""
    settings = get_settings()
    return settings.miniapp_jwt_secret or settings.secret_key


def validate_init_data(init_data: str) -> Optional[dict]:
    """Validate Telegram Mini App initData using HMAC-SHA256.

    Returns parsed user data dict if valid, None otherwise.
    Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    settings = get_settings()

    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        # parse_qs returns lists, flatten
        data = {k: v[0] for k, v in parsed.items()}
    except Exception:
        return None

    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    # Check auth_date is not too old (allow 24 hours)
    auth_date = data.get("auth_date")
    if auth_date:
        try:
            if time.time() - int(auth_date) > 86400:
                logger.warning("initData auth_date expired")
                return None
        except (ValueError, TypeError):
            return None

    # Build data-check-string: sorted key=value pairs joined by \n
    data_check_parts = sorted(
        f"{k}={v}" for k, v in data.items()
    )
    data_check_string = "\n".join(data_check_parts)

    # HMAC-SHA256: secret_key = HMAC_SHA256(bot_token, "WebAppData")
    secret_key = hmac.new(
        b"WebAppData",
        settings.telegram_bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        logger.warning("initData HMAC validation failed")
        return None

    # Extract user info
    user_json = data.get("user")
    if user_json:
        try:
            return json.loads(unquote(user_json))
        except (json.JSONDecodeError, TypeError):
            return None

    return None


def create_jwt_token(user_id: int, telegram_id: int) -> str:
    """Create a JWT token for Mini App session."""
    settings = get_settings()
    secret = _get_jwt_secret()

    payload = {
        "user_id": user_id,
        "telegram_id": telegram_id,
        "exp": datetime.now(timezone.utc)
        + timedelta(hours=settings.miniapp_jwt_expiry_hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt_token(token: str) -> Optional[dict]:
    """Decode and validate JWT token. Returns payload or None."""
    secret = _get_jwt_secret()
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"JWT invalid: {e}")
        return None


async def get_current_user(request: Request) -> User:
    """FastAPI dependency: extract and validate JWT, return User from DB.

    Raises HTTPException(401) if auth fails, HTTPException(403) if onboarding not completed.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"ok": False, "error": {"code": "AUTH_FAILED", "message": "Missing or invalid Authorization header"}},
        )

    token = auth_header[7:]
    payload = decode_jwt_token(token)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail={"ok": False, "error": {"code": "AUTH_FAILED", "message": "Invalid or expired token"}},
        )

    telegram_id = payload.get("telegram_id")
    if not telegram_id:
        raise HTTPException(
            status_code=401,
            detail={"ok": False, "error": {"code": "AUTH_FAILED", "message": "Token missing telegram_id"}},
        )

    async with get_session() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"ok": False, "error": {"code": "AUTH_FAILED", "message": "User not found"}},
            )

        # Update miniapp_last_seen
        user.miniapp_last_seen = datetime.now(timezone.utc)

        # Make sure user object is expunged so it can be used outside session
        await session.flush()

        # We need to return a detached-friendly dict or re-fetch outside
        # For simplicity, store essential attrs
        user_data = _user_to_dict(user)

    # Return a lightweight user-like object
    return UserContext(**user_data)


def _user_to_dict(user: User) -> dict:
    """Convert User ORM object to dict for detached use."""
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "level": user.level,
        "xp": user.xp,
        "role": user.role,
        "workplace": user.workplace,
        "has_blog": user.has_blog,
        "main_goal": user.main_goal,
        "hours_per_week": user.hours_per_week,
        "onboarding_completed": user.onboarding_completed,
        "subscription_tier": user.subscription_tier,
        "subscription_expires_at": user.subscription_expires_at,
        "current_mode": user.current_mode,
        "created_at": user.created_at,
        "last_interaction": user.last_interaction,
    }


class UserContext:
    """Lightweight user context for use in API handlers (detached from session)."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
