"""Bot middleware — user tracking, limit checks, etc."""

from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import get_or_create_user
from src.services.subscription_service import check_subscription_expiry
from src.utils.logger import logger


async def track_user_middleware(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Middleware to track user interactions and check subscriptions.
    Called before every handler.
    """
    if not update.effective_user:
        return

    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )

        # Update username/name if changed
        if user.username != tg_user.username:
            user.username = tg_user.username
        if user.first_name != tg_user.first_name:
            user.first_name = tg_user.first_name

        # Update last interaction
        user.last_interaction = datetime.utcnow()

        # Check subscription expiry
        await check_subscription_expiry(session, user)
