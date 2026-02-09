"""Voice message handler."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from src.database.connection import get_session
from src.database.repository import get_or_create_user
from src.database.models import DirectQuestion
from src.services.stt_service import download_and_transcribe
from src.services.direct_line_service import submit_question, generate_admin_card
from src.config import get_settings
from src.utils.logger import logger
from src.bot.handlers.qa import handle_qa_message
from src.bot.handlers.audit import handle_audit_message


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages — transcribe and route.
    
    Checks for pending Direct Line questions first (DB-based, survives restarts).
    """
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

    # Route — check for Direct Line first (DB-based, survives restarts)
    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=update.effective_user.id)
        mode = user.current_mode or "qa"

        # Check for pending DL question in DB
        dq_result = await session.execute(
            select(DirectQuestion).where(
                DirectQuestion.user_id == user.id,
                DirectQuestion.status == "paid",
            ).order_by(DirectQuestion.created_at.desc()).limit(1)
        )
        pending_dq = dq_result.scalar_one_or_none()

        if pending_dq:
            # Route as Direct Line question with voice
            dq = await submit_question(
                session,
                pending_dq.id,
                question_text=transcript,
                question_voice_file_id=voice.file_id,
                question_voice_transcript=transcript,
            )

            if dq:
                # Generate admin card
                card_text = await generate_admin_card(session, dq, user)

                # Send to admin
                try:
                    admin_msg = await context.bot.send_message(
                        chat_id=settings.admin_chat_id,
                        text=card_text,
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Ответил",
                                        callback_data=f"adl:answered:{dq.id}",
                                    ),
                                    InlineKeyboardButton(
                                        "⏭ Больше контекста",
                                        callback_data=f"adl:morecontext:{dq.id}",
                                    ),
                                ],
                                [
                                    InlineKeyboardButton(
                                        "↩️ Вернуть деньги",
                                        callback_data=f"adl:refund:{dq.id}",
                                    ),
                                    InlineKeyboardButton(
                                        "📚 В базу знаний",
                                        callback_data=f"adl:addkb:{dq.id}",
                                    ),
                                ],
                            ]
                        ),
                    )
                    dq.admin_card_message_id = admin_msg.message_id
                except Exception as e:
                    logger.error(f"Failed to send DL card to admin: {e}")

                user.current_mode = "qa"

                await update.message.reply_text(
                    "✅ Голосовой вопрос отправлен Косте!\n\n"
                    "Он получил твой профиль, историю наших разговоров и вопрос.\n"
                    "Ожидай ответ в течение 48 часов ⏳"
                )
            return

    # Regular routing based on mode
    if mode == "audit":
        await handle_audit_message(update, context, transcript)
    else:
        await handle_qa_message(update, context, transcript)
