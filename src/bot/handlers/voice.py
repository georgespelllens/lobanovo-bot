"""Voice message handler."""

from telegram import Update
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import get_or_create_user
from src.services.stt_service import download_and_transcribe
from src.config import get_settings
from src.utils.logger import logger
from src.bot.handlers.qa import handle_qa_message
from src.bot.handlers.audit import handle_audit_message


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages — transcribe and route."""
    settings = get_settings()
    voice = update.message.voice

    # Check duration
    if voice.duration > settings.max_voice_duration_seconds:
        await update.message.reply_text(
            f"Голосовое слишком длинное ({voice.duration} сек). "
            f"Максимум — {settings.max_voice_duration_seconds // 60} минут. "
            "Пришли покороче или напиши текстом."
        )
        return

    # Send typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    # Transcribe
    try:
        transcript = await download_and_transcribe(context.bot, voice.file_id)
    except Exception as e:
        logger.error(f"Voice transcription error: {e}")
        await update.message.reply_text(
            "Не удалось распознать голосовое сообщение. "
            "Попробуй ещё раз или напиши текстом."
        )
        return

    if not transcript or len(transcript.strip()) < 5:
        await update.message.reply_text(
            "Не удалось разобрать, что ты сказал. Попробуй ещё раз или напиши текстом."
        )
        return

    # Notify user about transcription
    await update.message.reply_text(f"🎤 Распознал: «{transcript[:200]}{'...' if len(transcript) > 200 else ''}»")

    # Route to appropriate handler based on mode
    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=update.effective_user.id)
        mode = user.current_mode or "qa"

    if mode == "audit":
        await handle_audit_message(update, context, transcript)
    else:
        await handle_qa_message(update, context, transcript)
