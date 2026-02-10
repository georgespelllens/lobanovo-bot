"""Mini App API router — aggregates all miniapp sub-routers."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException

from src.api.miniapp.auth import validate_init_data, create_jwt_token
from src.api.miniapp.profile import router as profile_router
from src.api.miniapp.chat import router as chat_router
from src.api.miniapp.audit import router as audit_router
from src.api.miniapp.tasks import router as tasks_router
from src.database.connection import get_session
from src.database.repository import get_user_by_telegram_id
from src.utils.logger import logger

router = APIRouter(prefix="/api/miniapp", tags=["miniapp"])


@router.post("/auth")
async def auth(x_telegram_init_data: str = Header(alias="X-Telegram-Init-Data")):
    """Authenticate via Telegram initData, return JWT + user info."""
    user_data = validate_init_data(x_telegram_init_data)
    if user_data is None:
        raise HTTPException(
            status_code=401,
            detail={
                "ok": False,
                "error": {"code": "AUTH_FAILED", "message": "Invalid initData"},
            },
        )

    telegram_id = user_data.get("id")
    if not telegram_id:
        raise HTTPException(
            status_code=401,
            detail={
                "ok": False,
                "error": {"code": "AUTH_FAILED", "message": "No user id in initData"},
            },
        )

    async with get_session() as session:
        user = await get_user_by_telegram_id(session, int(telegram_id))
        if user is None:
            raise HTTPException(
                status_code=403,
                detail={
                    "ok": False,
                    "error": {
                        "code": "ONBOARDING_REQUIRED",
                        "message": "Сначала напиши боту /start для регистрации",
                    },
                },
            )

        if not user.onboarding_completed:
            raise HTTPException(
                status_code=403,
                detail={
                    "ok": False,
                    "error": {
                        "code": "ONBOARDING_REQUIRED",
                        "message": "Сначала пройди онбординг в боте — напиши /start",
                    },
                },
            )

        # Update mini app tracking
        user.miniapp_last_seen = datetime.now(timezone.utc)
        # Update name from Telegram if changed
        if user_data.get("first_name"):
            user.first_name = user_data["first_name"]
        if user_data.get("last_name"):
            user.last_name = user_data.get("last_name")
        if user_data.get("username"):
            user.username = user_data["username"]

        token = create_jwt_token(user.id, user.telegram_id)

        return {
            "ok": True,
            "data": {
                "token": token,
                "user": {
                    "id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "level": user.level,
                    "xp": user.xp,
                    "role": user.role,
                    "subscription_tier": user.subscription_tier,
                    "onboarding_completed": user.onboarding_completed,
                },
            },
        }


# Include sub-routers
router.include_router(profile_router)
router.include_router(chat_router)
router.include_router(audit_router)
router.include_router(tasks_router)
