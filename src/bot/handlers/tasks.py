"""Tasks and progress handler."""

from telegram import Update
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import (
    get_or_create_user,
    get_user_active_tasks,
    get_user_task_stats,
)
from src.services.task_service import assign_weekly_tasks, format_progress
from src.utils.logger import logger


async def handle_tasks_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /tasks — show current weekly tasks."""
    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)

        if not user.onboarding_completed:
            await update.message.reply_text(
                "Сначала пройди онбординг — /start"
            )
            return

        # Get active tasks
        active_tasks = await get_user_active_tasks(session, user.id)

        if not active_tasks:
            # Try to assign new tasks
            active_tasks_assigned = await assign_weekly_tasks(session, user)
            if active_tasks_assigned:
                active_tasks = await get_user_active_tasks(session, user.id)

        if not active_tasks:
            await update.message.reply_text(
                "Пока нет заданий. Задания приходят каждый понедельник в 10:00 МСК."
            )
            return

        text = "📋 Задания на неделю:\n\n"
        for i, ut in enumerate(active_tasks, 1):
            # Eagerly load task template
            template = await session.get(
                type(ut).__mapper__.relationships["task_template"].mapper.class_,
                ut.task_template_id,
            )

            status_emoji = {
                "assigned": "⬜",
                "submitted": "🔄",
                "reviewed": "✅",
                "completed": "✅",
                "skipped": "⏭",
            }
            emoji = status_emoji.get(ut.status, "⬜")

            text += f"{emoji} Задание {i}: {template.title}\n"
            text += f"   {template.description[:150]}\n"
            if ut.status == "assigned":
                text += f"   ⭐ +{template.xp_reward} XP\n"
            elif ut.status == "completed":
                text += f"   ✅ Получено {ut.xp_earned} XP\n"
            text += "\n"

        text += (
            "Чтобы сдать задание — просто пришли результат текстом. "
            "Я пойму, что это ответ на задание."
        )

        await update.message.reply_text(text)


async def handle_progress_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /progress — show user progress."""
    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)

        if not user.onboarding_completed:
            await update.message.reply_text(
                "Сначала пройди онбординг — /start"
            )
            return

        task_stats = await get_user_task_stats(session, user.id)
        text = format_progress(user, task_stats)

        await update.message.reply_text(text)
