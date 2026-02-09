"""Scheduled tasks — weekly assignments, reminders, deadlines."""

from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.database.connection import get_session
from src.database.repository import (
    get_all_active_users,
    get_user_active_tasks,
    get_overdue_direct_questions,
    get_direct_question,
)
from src.services.task_service import assign_weekly_tasks
from src.utils.logger import logger


scheduler = AsyncIOScheduler()
_bot = None


def init_scheduler(bot):
    """Initialize scheduler with bot instance."""
    global _bot
    _bot = bot

    # Monday 10:00 MSK (07:00 UTC)
    scheduler.add_job(
        send_weekly_tasks,
        CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="weekly_tasks",
        replace_existing=True,
    )

    # Sunday 18:00 MSK (15:00 UTC) — reminder
    scheduler.add_job(
        send_task_reminders,
        CronTrigger(day_of_week="sun", hour=15, minute=0),
        id="task_reminders",
        replace_existing=True,
    )

    # Every 6 hours — check DL deadlines
    scheduler.add_job(
        check_direct_line_deadlines,
        CronTrigger(hour="*/6", minute=0),
        id="dl_deadlines",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")


async def send_weekly_tasks():
    """Send weekly tasks to all active users on Monday."""
    logger.info("Sending weekly tasks...")

    async with get_session() as session:
        users = await get_all_active_users(session)

        sent = 0
        for user in users:
            if not user.onboarding_completed:
                continue

            try:
                tasks = await assign_weekly_tasks(session, user)
                if tasks and _bot:
                    text = "📋 Задания на неделю:\n\n"
                    for i, task in enumerate(tasks, 1):
                        template = await session.get(
                            type(task).__mapper__.relationships["task_template"].mapper.class_,
                            task.task_template_id,
                        )
                        text += f"{i}. {template.title}\n   {template.description[:100]}...\n   ⭐ +{template.xp_reward} XP\n\n"

                    text += "Чтобы сдать задание — пришли результат текстом.\nУдачи! 💪"

                    await _bot.send_message(chat_id=user.telegram_id, text=text)
                    sent += 1
            except Exception as e:
                logger.error(f"Failed to send tasks to user {user.telegram_id}: {e}")

    logger.info(f"Weekly tasks sent to {sent} users")


async def send_task_reminders():
    """Send reminders about uncompleted tasks on Sunday."""
    logger.info("Sending task reminders...")

    async with get_session() as session:
        users = await get_all_active_users(session)

        sent = 0
        for user in users:
            if not user.onboarding_completed:
                continue

            try:
                active_tasks = await get_user_active_tasks(session, user.id)
                pending = [t for t in active_tasks if t.status == "assigned"]

                if pending and _bot:
                    text = (
                        f"⏰ Напоминание! У тебя {len(pending)} невыполненных "
                        f"заданий на этой неделе.\n\n"
                        "Не забудь сдать до конца дня → /tasks"
                    )
                    await _bot.send_message(chat_id=user.telegram_id, text=text)
                    sent += 1
            except Exception as e:
                logger.error(f"Failed to send reminder to user {user.telegram_id}: {e}")

    logger.info(f"Task reminders sent to {sent} users")


async def check_direct_line_deadlines():
    """Check for overdue Direct Line questions."""
    logger.info("Checking DL deadlines...")

    from src.config import get_settings

    settings = get_settings()

    async with get_session() as session:
        overdue = await get_overdue_direct_questions(session)

        for dq in overdue:
            hours_overdue = (datetime.utcnow() - dq.deadline_at).total_seconds() / 3600

            user = await session.get(
                type(dq).__mapper__.relationships["user"].mapper.class_,
                dq.user_id,
            )

            if hours_overdue >= settings.direct_line_auto_refund_hours - (
                settings.direct_line_response_deadline_hours
            ):
                # Auto refund
                dq.status = "refunded"
                logger.warning(f"Auto-refund DL #{dq.id} — {hours_overdue:.0f}h overdue")

                if _bot:
                    try:
                        await _bot.send_message(
                            chat_id=user.telegram_id,
                            text=(
                                f"↩️ К сожалению, Костя не успел ответить на твой вопрос "
                                f"в Прямой линии #{dq.id}. Оплата будет возвращена.\n\n"
                                "Приносим извинения. Можешь задать вопрос заново → /ask_kostya"
                            ),
                        )
                        await _bot.send_message(
                            chat_id=settings.admin_chat_id,
                            text=f"⚠️ Автовозврат Прямой линии #{dq.id} — дедлайн истёк.",
                        )
                    except Exception:
                        pass
            else:
                # Remind admin
                if _bot:
                    try:
                        await _bot.send_message(
                            chat_id=settings.admin_chat_id,
                            text=(
                                f"⏰ Напоминание: Прямая линия #{dq.id} "
                                f"ожидает ответа уже {hours_overdue:.0f} часов.\n"
                                f"Автовозврат через {settings.direct_line_auto_refund_hours - hours_overdue:.0f}ч."
                            ),
                        )
                    except Exception:
                        pass

    logger.info(f"DL deadline check complete, {len(overdue)} overdue")
