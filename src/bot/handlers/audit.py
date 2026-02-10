"""Audit handler — post review mode."""

from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import (
    get_or_create_user,
    get_or_create_conversation,
    save_message,
)
from src.services.rag_service import get_audit_response
from src.services.subscription_service import check_weekly_limit, increment_usage
from src.utils.logger import logger


async def handle_audit_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /audit command — switch to audit mode."""
    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)
        user.current_mode = "audit"

        await update.message.reply_text(
            "📝 Режим аудита постов включён.\n\n"
            "Пришли мне текст своего поста — я разберу его по 6 критериям Лобанова:\n"
            "1. Мета-сообщение\n"
            "2. Конкретика\n"
            "3. Позиционирование\n"
            "4. Читабельность\n"
            "5. Антипаттерны\n"
            "6. CTA\n\n"
            "Можешь прислать текстом или переслать сообщение.\n"
            "Чтобы вернуться к вопросам — /ask"
        )


async def handle_audit_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    """Handle a post audit request."""
    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)

        # Check limits
        within_limit, used, max_val = check_weekly_limit(user, "audits")
        if not within_limit:
            await update.message.reply_text(
                f"Лимит аудитов на этой неделе исчерпан ({used}/{max_val}) 😔\n\n"
                "Хочешь больше? Посмотри тарифы → /plan"
            )
            return

        # Send typing indicator
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )

        # Get or create conversation
        conv = await get_or_create_conversation(session, user.id, "audit")

        # Save user message
        await save_message(
            session,
            conversation_id=conv.id,
            user_id=user.id,
            role="user",
            content=text,
            input_type="text",
        )

        # Generate audit
        try:
            result = await get_audit_response(session, text, user.level)
        except Exception as e:
            error_type = type(e).__name__
            status_code = getattr(e, "status_code", None)
            logger.error(
                f"LLM error in audit: [{error_type}] status={status_code} {e}",
                exc_info=True,
            )
            if status_code == 402 or "insufficient" in str(e).lower() or "credit" in str(e).lower():
                error_msg = "Сервис временно недоступен (проблема с оплатой API). Админ уже уведомлён."
            elif status_code == 429 or "rate" in str(e).lower():
                error_msg = "Слишком много запросов. Подожди пару минут и попробуй снова."
            elif status_code and status_code >= 500:
                error_msg = "Сервер ИИ временно недоступен. Попробуй через пару минут."
            else:
                error_msg = "Произошла ошибка при анализе поста. Попробуй ещё раз через минуту."
            await update.message.reply_text(error_msg)
            return

        # Save assistant message
        bot_msg = await save_message(
            session,
            conversation_id=conv.id,
            user_id=user.id,
            role="assistant",
            content=result["content"],
            tokens_input=result.get("tokens_input"),
            tokens_output=result.get("tokens_output"),
            model_used=result.get("model"),
            cost_usd=result.get("cost"),
        )

        # Increment usage
        increment_usage(user, "audits")
        user.last_interaction = datetime.now(timezone.utc)

        # Auto-return to Q&A mode after audit
        user.current_mode = "qa"

        # Send response with rating and rewrite buttons
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("👍", callback_data=f"rate:up:{bot_msg.id}"),
                    InlineKeyboardButton("👎", callback_data=f"rate:down:{bot_msg.id}"),
                ],
                [
                    InlineKeyboardButton(
                        "✍️ Перепиши пост", callback_data=f"rewrite:{bot_msg.id}"
                    ),
                ],
            ]
        )

        await update.message.reply_text(result["content"], reply_markup=keyboard)

        # Notify user about mode switch
        await update.message.reply_text(
            "✍️ Аудит завершён. Теперь ты снова в режиме вопросов.\n"
            "Чтобы разобрать ещё один пост — /audit"
        )
