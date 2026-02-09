"""Inline callback query handlers."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import (
    get_or_create_user,
    update_message_rating,
)
from src.services.escalation_service import process_escalation, get_escalation_response
from src.services.subscription_service import activate_subscription
from src.bot.handlers.start import handle_onboarding_callback
from src.bot.handlers.payment import handle_payment_callback
from src.bot.handlers.direct_line import (
    handle_direct_line_callback,
    handle_admin_direct_line_callback,
)
from src.utils.logger import logger


async def handle_rating(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle 👍/👎 rating callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data  # rate:up:MSGID or rate:down:MSGID
    parts = data.split(":")
    if len(parts) < 3:
        return

    direction = parts[1]  # up or down
    msg_id = int(parts[2])
    rating = 1 if direction == "up" else -1

    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)

        await update_message_rating(session, msg_id, rating)

        if rating == 1:
            user.negative_streak = 0
            await query.edit_message_reply_markup(reply_markup=None)
            # Optional: show a subtle confirmation
        else:
            user.negative_streak = (user.negative_streak or 0) + 1

            # Show reason options
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Не по теме", callback_data=f"reason:off_topic:{msg_id}"
                        ),
                        InlineKeyboardButton(
                            "Слишком общий",
                            callback_data=f"reason:too_general:{msg_id}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "Неправильный совет",
                            callback_data=f"reason:wrong_advice:{msg_id}",
                        ),
                        InlineKeyboardButton(
                            "Хочу к Косте",
                            callback_data=f"reason:want_human:{msg_id}",
                        ),
                    ],
                ]
            )
            await query.edit_message_reply_markup(reply_markup=keyboard)

            # Check for escalation after 3 negative ratings
            if user.negative_streak >= 3:
                from src.database.repository import get_or_create_conversation

                conv = await get_or_create_conversation(session, user.id, "qa")
                await process_escalation(
                    session, context.bot, user, conv.id, "negative_feedback"
                )


async def handle_rating_reason(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle rating reason selection."""
    query = update.callback_query
    await query.answer()

    data = query.data  # reason:REASON:MSGID
    parts = data.split(":", 2)
    if len(parts) < 3:
        return

    reason = parts[1]
    msg_id = int(parts[2])

    async with get_session() as session:
        await update_message_rating(session, msg_id, -1, reason)

    reason_labels = {
        "off_topic": "Не по теме",
        "too_general": "Слишком общий",
        "wrong_advice": "Неправильный совет",
        "want_human": "Хочу к Косте",
    }

    await query.edit_message_reply_markup(reply_markup=None)

    if reason == "want_human":
        # Direct escalation to consultation
        response_text = get_escalation_response("user_request")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=response_text,
        )


async def handle_subscription_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle admin subscription confirmation callback."""
    query = update.callback_query
    await query.answer()

    data = query.data  # confirm_sub:USERID:TIER
    parts = data.split(":")
    if len(parts) < 3:
        return

    target_tg_id = int(parts[1])
    tier = parts[2]

    async with get_session() as session:
        from src.database.repository import get_user_by_telegram_id

        user = await get_user_by_telegram_id(session, target_tg_id)
        admin = await get_or_create_user(
            session, telegram_id=update.effective_user.id
        )

        if user:
            await activate_subscription(session, user, tier, confirmed_by_id=admin.id)

            # Notify user
            tier_names = {"pro": "Pro 🐺", "premium": "Premium 🐺🔥"}
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"🎉 Подписка {tier_names.get(tier, tier)} активирована!\n\n"
                    f"Действует до: {user.subscription_expires_at.strftime('%d.%m.%Y')}\n\n"
                    "Пользуйся на здоровье!",
                )
            except Exception as e:
                logger.error(f"Failed to notify user about subscription: {e}")

    await query.edit_message_text(
        query.message.text + "\n\n✅ Подписка активирована"
    )


async def handle_task_submit_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle task submission confirmation callback."""
    query = update.callback_query
    await query.answer()

    data = query.data  # submit_task:TASK_ID
    parts = data.split(":")
    if len(parts) < 2:
        return

    task_id = int(parts[1])
    submission_text = context.user_data.pop("pending_submission_text", None)

    if not submission_text:
        await query.edit_message_text("Текст задания не найден. Пришли его ещё раз.")
        return

    from src.services.task_service import review_task_submission
    from src.database.repository import get_or_create_user

    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)

        # Find the task
        from src.database.models import UserTask
        task = await session.get(UserTask, task_id)
        if not task or task.user_id != user.id:
            await query.edit_message_text("Задание не найдено.")
            return

        result = await review_task_submission(session, task, submission_text)

        response = result["review_text"]
        response += f"\n\n⭐ +{result['xp_earned']} XP"
        response += f"\n📊 Итого: {result['total_xp']} XP"

        if result.get("level_up"):
            level_emoji = {
                "wolfling": "🐺 Волчонок",
                "wolf": "🐺🔥 Волк",
            }
            new_level = level_emoji.get(result.get("level", ""), result.get("level", ""))
            response += f"\n\n🎉 Поздравляю! Ты теперь {new_level}!"

    await query.edit_message_text(response)

    # Clean up user_data
    context.user_data.pop("pending_submission_task_id", None)


async def route_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Route callback queries to appropriate handlers."""
    data = update.callback_query.data

    if data.startswith("rate:"):
        await handle_rating(update, context)
    elif data.startswith("reason:"):
        await handle_rating_reason(update, context)
    elif data.startswith("onboard:"):
        await handle_onboarding_callback(update, context)
    elif data.startswith("pay:"):
        await handle_payment_callback(update, context)
    elif data.startswith("dl:"):
        await handle_direct_line_callback(update, context)
    elif data.startswith("adl:"):
        await handle_admin_direct_line_callback(update, context)
    elif data.startswith("confirm_sub:"):
        await handle_subscription_confirm(update, context)
    elif data.startswith("submit_task:"):
        await handle_task_submit_confirm(update, context)
    elif data == "continue_qa":
        await update.callback_query.answer("Ок, отвечаю как обычно")
        # Re-route as QA — just acknowledge, next message will be routed normally
    else:
        logger.warning(f"Unknown callback data: {data}")
        await update.callback_query.answer("Неизвестная команда")
