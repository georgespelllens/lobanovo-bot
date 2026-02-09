"""Subscription management service."""

from datetime import datetime, timedelta, date, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database.models import User, Subscription
from src.config import TIER_LIMITS
from src.utils.logger import logger


def get_tier_limits(tier: str) -> dict:
    """Get limits for a subscription tier."""
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


def check_weekly_limit(user: User, limit_type: str) -> tuple[bool, int, int]:
    """Check if user has remaining weekly limit.
    Returns (within_limit, used, max).
    """
    limits = get_tier_limits(user.subscription_tier)

    # Reset if new week
    today = date.today()
    if user.week_start_date is None or (today - user.week_start_date).days >= 7:
        user.weekly_questions_used = 0
        user.weekly_audits_used = 0
        user.week_start_date = today

    if limit_type == "questions":
        used = user.weekly_questions_used
        max_val = limits["weekly_questions"]
        return used < max_val, used, max_val
    elif limit_type == "audits":
        used = user.weekly_audits_used
        max_val = limits["weekly_audits"]
        return used < max_val, used, max_val

    return True, 0, 999999


def increment_usage(user: User, limit_type: str) -> None:
    """Increment usage counter."""
    if limit_type == "questions":
        user.weekly_questions_used += 1
    elif limit_type == "audits":
        user.weekly_audits_used += 1


async def activate_subscription(
    session: AsyncSession,
    user: User,
    tier: str,
    months: int = 1,
    confirmed_by_id: Optional[int] = None,
) -> Subscription:
    """Activate a subscription for a user."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30 * months)

    # Pricing
    prices = {"pro": 990, "premium": 4990}
    amount = prices.get(tier, 0) * months

    sub = Subscription(
        user_id=user.id,
        tier=tier,
        started_at=now,
        expires_at=expires,
        payment_method="manual",
        payment_amount=amount,
        payment_confirmed=True,
        confirmed_by=confirmed_by_id,
        is_active=True,
    )
    session.add(sub)

    # Update user
    user.subscription_tier = tier
    user.subscription_expires_at = expires

    logger.info(f"Activated {tier} subscription for user {user.telegram_id} until {expires}")
    return sub


async def check_subscription_expiry(session: AsyncSession, user: User) -> bool:
    """Check if subscription is still active. Downgrade if expired."""
    if user.subscription_tier == "free":
        return True

    if user.subscription_expires_at and user.subscription_expires_at < datetime.now(timezone.utc):
        # Expired — downgrade to free
        user.subscription_tier = "free"
        user.subscription_expires_at = None

        # Deactivate subscription record
        result = await session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user.id,
                Subscription.is_active == True,
            )
        )
        for sub in result.scalars():
            sub.is_active = False

        logger.info(f"Subscription expired for user {user.telegram_id}, downgraded to free")
        return False

    return True


def format_plan_info(user: User) -> str:
    """Format subscription plan info for the user."""
    limits = get_tier_limits(user.subscription_tier)
    tier_names = {"free": "Free 🐱", "pro": "Pro 🐺", "premium": "Premium 🐺🔥"}
    tier_name = tier_names.get(user.subscription_tier, "Free 🐱")

    text = f"📋 Твой тариф: {tier_name}\n\n"

    if user.subscription_tier != "free" and user.subscription_expires_at:
        text += f"⏳ Активен до: {user.subscription_expires_at.strftime('%d.%m.%Y')}\n\n"

    q_limit = limits["weekly_questions"]
    a_limit = limits["weekly_audits"]
    q_used = user.weekly_questions_used or 0
    a_used = user.weekly_audits_used or 0

    q_str = f"{q_used}/{q_limit}" if q_limit < 999999 else f"{q_used}/∞"
    a_str = f"{a_used}/{a_limit}" if a_limit < 999999 else f"{a_used}/∞"

    text += f"💬 Вопросов на этой неделе: {q_str}\n"
    text += f"📝 Аудитов на этой неделе: {a_str}\n"
    text += f"🎤 Прямая линия: {limits['direct_line_price']}₽/вопрос\n"

    if limits.get("free_direct_questions_monthly", 0) > 0:
        text += f"🎁 Бесплатных вопросов Косте в месяц: {limits['free_direct_questions_monthly']}\n"

    if user.subscription_tier == "free":
        text += (
            "\n━━━━━━━━━━━━━━━━━━━━\n"
            "\n🔥 Хочешь больше?\n\n"
            "Pro (990₽/мес):\n"
            "• 50 вопросов/нед\n"
            "• 20 аудитов/нед\n"
            "• Веб-дашборд\n\n"
            "Premium (4990₽/мес):\n"
            "• Безлимит вопросов\n"
            "• 1 бесплатный вопрос Косте/мес\n"
            "• Приоритетная очередь\n\n"
            "Для активации напиши /consult"
        )

    return text
