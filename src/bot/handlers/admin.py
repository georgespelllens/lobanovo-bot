"""Admin command handlers."""

from telegram import Update
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import (
    get_or_create_user,
    get_admin_stats,
    get_pending_escalations,
    get_user_by_telegram_id,
    get_all_active_users,
)
from src.config import get_settings
from src.utils.logger import logger


def is_admin(telegram_id: int) -> bool:
    """Check if user is admin."""
    settings = get_settings()
    return telegram_id in settings.admin_ids_list


async def handle_admin_stats(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /admin_stats — show overview statistics."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return

    async with get_session() as session:
        stats = await get_admin_stats(session)

    subs = stats.get("subscriptions", {})
    text = f"""📊 Статистика бота

👥 Пользователи: {stats['total_users']}
🟢 Активных (7 дней): {stats['active_users_7d']}
💬 Сообщений сегодня: {stats['messages_today']}
⭐ Средняя оценка: {stats['avg_rating'] or 'нет данных'}

📋 Подписки:
  Free: {subs.get('free', 0)}
  Pro: {subs.get('pro', 0)}
  Premium: {subs.get('premium', 0)}

💰 Прямая линия:
  Всего вопросов: {stats['direct_line_total']}
  Доход: {stats['direct_line_revenue_rub']}₽"""

    await update.message.reply_text(text)


async def handle_admin_escalations(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /admin_escalations — show pending escalations."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return

    async with get_session() as session:
        escalations = await get_pending_escalations(session)

    if not escalations:
        await update.message.reply_text("✅ Нет непросмотренных эскалаций.")
        return

    text = f"🔔 Непросмотренные эскалации ({len(escalations)}):\n\n"
    for esc in escalations[:10]:
        text += f"#{esc.id} | {esc.trigger_type} | {esc.created_at.strftime('%d.%m %H:%M')}\n"
        text += f"  {esc.summary[:100]}\n\n"

    await update.message.reply_text(text)


async def handle_admin_top_questions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /admin_top_questions — show top frequent questions."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return

    await update.message.reply_text(
        "📊 Топ вопросов — функция будет доступна после накопления данных."
    )


async def handle_admin_users(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /admin_users [username] — user info."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return

    args = context.args
    if not args:
        async with get_session() as session:
            users = await get_all_active_users(session)
            text = f"👥 Всего активных: {len(users)}\n\n"
            for u in users[:20]:
                text += f"@{u.username or '?'} | {u.level} | {u.subscription_tier} | XP: {u.xp}\n"
            await update.message.reply_text(text)
        return

    # Search by username
    username = args[0].lstrip("@")
    await update.message.reply_text(f"Поиск @{username}... (функция в разработке)")


async def handle_admin_broadcast(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /admin_broadcast [text] — send message to all users."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /admin_broadcast Текст сообщения")
        return

    broadcast_text = " ".join(context.args)

    async with get_session() as session:
        users = await get_all_active_users(session)

    sent = 0
    failed = 0
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=f"📢 Сообщение от Лобанова:\n\n{broadcast_text}",
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"✅ Отправлено: {sent}\n❌ Не доставлено: {failed}"
    )


async def handle_admin_add_knowledge(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /admin_add_knowledge — add post to knowledge base."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Нет доступа.")
        return

    await update.message.reply_text(
        "Чтобы добавить пост в базу знаний, пришли его текст следующим сообщением.\n"
        "(Функция пока в ручном режиме — используй скрипт load_knowledge_base.py)"
    )
