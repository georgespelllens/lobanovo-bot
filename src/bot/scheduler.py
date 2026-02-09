"""Scheduled tasks — weekly assignments, reminders, deadlines."""

from datetime import datetime, timedelta, timezone
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
    """Check for overdue Direct Line questions.
    
    Auto-refund is calculated from created_at (not deadline_at) using
    settings.direct_line_auto_refund_hours (96h = 4 days by default).
    """
    logger.info("Checking DL deadlines...")

    from src.config import get_settings
    from src.database.models import DirectQuestion, User
    from sqlalchemy import select, and_

    settings = get_settings()
    auto_refund_cutoff = datetime.now(timezone.utc) - timedelta(
        hours=settings.direct_line_auto_refund_hours
    )

    async with get_session() as session:
        # Get all questions awaiting response
        result = await session.execute(
            select(DirectQuestion).where(
                DirectQuestion.status == "question_sent",
            )
        )
        pending_questions = result.scalars().all()

        refunded_count = 0
        reminded_count = 0

        for dq in pending_questions:
            # Make created_at timezone-aware if it isn't already
            created = dq.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            hours_since_created = (datetime.now(timezone.utc) - created).total_seconds() / 3600

            user = await session.get(User, dq.user_id)

            if dq.created_at <= auto_refund_cutoff:
                # Auto refund — past the auto_refund_hours threshold
                dq.status = "refunded"
                refunded_count += 1
                logger.warning(
                    f"Auto-refund DL #{dq.id} — {hours_since_created:.0f}h since created"
                )

                if _bot and user:
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
            elif dq.deadline_at and datetime.now(timezone.utc) > (
                dq.deadline_at if dq.deadline_at.tzinfo else dq.deadline_at.replace(tzinfo=timezone.utc)
            ):
                # Past response deadline but not yet at auto-refund — remind admin
                hours_remaining = (
                    settings.direct_line_auto_refund_hours - hours_since_created
                )
                reminded_count += 1

                if _bot:
                    try:
                        await _bot.send_message(
                            chat_id=settings.admin_chat_id,
                            text=(
                                f"⏰ Напоминание: Прямая линия #{dq.id} "
                                f"ожидает ответа уже {hours_since_created:.0f} часов.\n"
                                f"Автовозврат через {max(0, hours_remaining):.0f}ч."
                            ),
                        )
                    except Exception:
                        pass

    logger.info(
        f"DL deadline check complete: {refunded_count} refunded, {reminded_count} reminded"
    )
