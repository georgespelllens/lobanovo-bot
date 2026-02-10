"""Mini App: user profile + stats endpoints."""

from fastapi import APIRouter, Depends

from src.api.miniapp.auth import get_current_user, UserContext
from src.database.connection import get_session
from src.database.repository import get_user_task_stats
from src.database.models import Message, Conversation
from sqlalchemy import select, func, and_

router = APIRouter()


@router.get("/me")
async def get_profile(user: UserContext = Depends(get_current_user)):
    """Get current user profile with stats."""
    # Calculate stats from DB
    async with get_session() as session:
        # Questions count (qa conversations messages from user)
        questions_count = await session.execute(
            select(func.count(Message.id)).where(
                and_(
                    Message.user_id == user.id,
                    Message.role == "user",
                )
            )
        )
        questions_count = questions_count.scalar() or 0

        # Audits count
        audits_result = await session.execute(
            select(func.count(Conversation.id)).where(
                and_(
                    Conversation.user_id == user.id,
                    Conversation.mode == "audit",
                )
            )
        )
        audits_count = audits_result.scalar() or 0

        # Task stats
        task_stats = await get_user_task_stats(session, user.id)

    # XP thresholds for levels
    xp_thresholds = {
        "kitten": {"min": 0, "max": 99},
        "wolfling": {"min": 100, "max": 299},
        "wolf": {"min": 300, "max": 999},
    }
    current_threshold = xp_thresholds.get(user.level, xp_thresholds["kitten"])

    return {
        "ok": True,
        "data": {
            "user": {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "level": user.level,
                "xp": user.xp,
                "xp_min": current_threshold["min"],
                "xp_max": current_threshold["max"],
                "role": user.role,
                "workplace": user.workplace,
                "has_blog": user.has_blog,
                "main_goal": user.main_goal,
                "subscription_tier": user.subscription_tier,
                "subscription_expires_at": (
                    user.subscription_expires_at.isoformat()
                    if user.subscription_expires_at
                    else None
                ),
                "onboarding_completed": user.onboarding_completed,
                "created_at": (
                    user.created_at.isoformat() if user.created_at else None
                ),
            },
            "stats": {
                "questions_count": questions_count,
                "audits_count": audits_count,
                "tasks_completed": task_stats["completed"],
                "tasks_total": task_stats["total"],
                "xp_total": task_stats["total_xp"],
            },
        },
    }
