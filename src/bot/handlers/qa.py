"""Q&A handler — main conversational mode."""

from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import (
    get_or_create_user,
    get_or_create_conversation,
    get_conversation_messages,
    save_message,
)
from src.services.rag_service import get_qa_response
from src.services.subscription_service import check_weekly_limit, increment_usage
from src.services.escalation_service import should_escalate, process_escalation, get_escalation_response
from src.utils.logger import logger


async def handle_qa_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    """Handle a Q&A message."""
    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)

        # Check limits
        within_limit, used, max_val = check_weekly_limit(user, "questions")
        if not within_limit:
            await update.message.reply_text(
                f"Лимит вопросов на этой неделе исчерпан ({used}/{max_val}) 😔\n\n"
                "Хочешь больше? Посмотри тарифы → /plan\n"
                "Или задай вопрос Косте напрямую → /ask_kostya"
            )
            return

        # Check for escalation triggers
        trigger = await should_escalate(user, text)
        if trigger:
            conv = await get_or_create_conversation(session, user.id, "qa")
            await process_escalation(session, context.bot, user, conv.id, trigger)
            response_text = get_escalation_response(trigger)
            await update.message.reply_text(response_text)
            return

        # Send typing indicator
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )

        # Get or create conversation
        conv = await get_or_create_conversation(session, user.id, "qa")

        # Save user message
        await save_message(
            session,
            conversation_id=conv.id,
            user_id=user.id,
            role="user",
            content=text,
            input_type="text",
        )

        # Get conversation history
        history = await get_conversation_messages(session, conv.id, limit=10)

        # Generate response
        try:
            result = await get_qa_response(
                session,
                question=text,
                user_level=user.level,
                user_goal=user.main_goal or "",
                user_role=user.role or "",
                conversation_history=history,
            )
        except Exception as e:
            error_type = type(e).__name__
            status_code = getattr(e, "status_code", None)
            logger.error(
                f"LLM error in Q&A: [{error_type}] status={status_code} {e}",
                exc_info=True,
            )
            # Give user a more informative message
            if status_code == 402 or "insufficient" in str(e).lower() or "credit" in str(e).lower():
                error_msg = "Сервис временно недоступен (проблема с оплатой API). Админ уже уведомлён."
            elif status_code == 429 or "rate" in str(e).lower():
                error_msg = "Слишком много запросов. Подожди пару минут и попробуй снова."
            elif status_code and status_code >= 500:
                error_msg = "Сервер ИИ временно недоступен. Попробуй через пару минут."
            else:
                error_msg = "Произошла ошибка при обработке вопроса. Попробуй ещё раз через минуту."
            await update.message.reply_text(error_msg)
            return

        # Save assistant message
        bot_msg = await save_message(
            session,
            conversation_id=conv.id,
            user_id=user.id,
            role="assistant",
            content=result["content"],
            retrieved_knowledge_ids=result.get("retrieved_knowledge_ids"),
            tokens_input=result.get("tokens_input"),
            tokens_output=result.get("tokens_output"),
            model_used=result.get("model"),
            cost_usd=result.get("cost"),
        )

        # Increment usage
        increment_usage(user, "questions")
        user.last_interaction = datetime.now(timezone.utc)

        # Send response with rating buttons
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("👍", callback_data=f"rate:up:{bot_msg.id}"),
                    InlineKeyboardButton("👎", callback_data=f"rate:down:{bot_msg.id}"),
                ]
            ]
        )

        await update.message.reply_text(
            result["content"],
            reply_markup=keyboard,
        )
