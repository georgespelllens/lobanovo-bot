"""Telegram Login Widget authentication."""

import hashlib
import hmac
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from src.config import get_settings
from src.database.connection import get_session
from src.database.repository import get_user_by_telegram_id

router = APIRouter()


def verify_telegram_login(data: dict, bot_token: str) -> bool:
    """Verify Telegram Login Widget data."""
    check_hash = data.pop("hash", None)
    if not check_hash:
        return False

    # Sort and join data
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items()) if v
    )

    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hmac_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    return hmac_hash == check_hash


@router.get("/auth/telegram")
async def telegram_auth(request: Request):
    """Handle Telegram Login Widget callback."""
    settings = get_settings()
    params = dict(request.query_params)

    if not verify_telegram_login(params.copy(), settings.telegram_bot_token):
        return RedirectResponse(url="/login?error=auth_failed")

    telegram_id = int(params.get("id", 0))
    if not telegram_id:
        return RedirectResponse(url="/login?error=no_id")

    # Check user exists in our DB
    async with get_session() as session:
        user = await get_user_by_telegram_id(session, telegram_id)

    if not user:
        return RedirectResponse(url="/login?error=not_registered")

    # Set session cookie
    response = RedirectResponse(url="/dashboard")
    response.set_cookie(
        key="session_user_id",
        value=str(telegram_id),
        httponly=True,
        max_age=86400 * 30,  # 30 days
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    """Clear session."""
    response = RedirectResponse(url="/")
    response.delete_cookie("session_user_id")
    return response


async def get_current_user(request: Request) -> Optional[dict]:
    """Get current authenticated user from session cookie."""
    telegram_id = request.cookies.get("session_user_id")
    if not telegram_id:
        return None

    try:
        telegram_id = int(telegram_id)
    except ValueError:
        return None

    async with get_session() as session:
        user = await get_user_by_telegram_id(session, telegram_id)

    if not user:
        return None

    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "level": user.level,
        "xp": user.xp,
        "subscription_tier": user.subscription_tier,
        "is_admin": user.is_admin,
    }
