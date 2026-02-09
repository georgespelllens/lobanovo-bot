"""Direct Line handler — paid personal questions to Lobanov."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import get_or_create_user, get_direct_question
from src.services.direct_line_service import (
    check_slots_available,
    initiate_direct_question,
    confirm_payment,
    submit_question,
    generate_admin_card,
    deliver_answer,
    transcribe_and_add_to_kb,
)
from src.config import get_settings
from src.utils.logger import logger


async def handle_direct_line_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /ask_kostya — initiate Direct Line."""
    tg_user = update.effective_user
    settings = get_settings()

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)

        # Check available slots
        available, used, total = await check_slots_available(session)
        if not available:
            await update.message.reply_text(
                f"На этой неделе все слоты Прямой линии заняты ({used}/{total}).\n"
                "Следующие откроются в понедельник.\n\n"
                "Пока можешь задать вопрос ИИ — /ask"
            )
            return

        # Create direct question
        dq = await initiate_direct_question(session, user)

        # Store DQ ID in user context
        context.user_data["pending_dq_id"] = dq.id

        await update.message.reply_text(
            f"🎤 Прямая линия с Костей\n\n"
            f"Задай вопрос — Костя ответит голосовым на 5–10 минут.\n"
            f"Стоимость: {settings.direct_line_price_rub}₽\n"
            f"Обычно отвечает в течение 24–48 часов.\n"
            f"Слотов на этой неделе: {total - used} из {total}\n\n"
            f"Для начала — оплати вопрос.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"💳 Оплатить {settings.direct_line_price_rub}₽",
                            callback_data=f"dl:pay:{dq.id}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Отмена", callback_data=f"dl:cancel:{dq.id}"
                        ),
                    ],
                ]
            ),
        )


async def handle_direct_line_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle Direct Line inline button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    settings = get_settings()

    if data.startswith("dl:pay:"):
        dq_id = int(data.split(":")[-1])
        await query.edit_message_text(
            f"💳 Оплата Прямой линии — {settings.direct_line_price_rub}₽\n\n"
            "Переведи сумму и напиши «оплатил».\n"
            "Реквизиты: [будут добавлены]\n\n"
            "После подтверждения оплаты — сможешь задать вопрос Косте."
        )

        # Notify admin
        tg_user = update.effective_user
        try:
            await context.bot.send_message(
                chat_id=settings.admin_chat_id,
                text=(
                    f"💰 Прямая линия — оплата #{dq_id}\n\n"
                    f"👤 @{tg_user.username or tg_user.first_name}\n"
                    f"Сумма: {settings.direct_line_price_rub}₽\n\n"
                    "Подтвердить после получения оплаты."
                ),
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ Оплата получена",
                                callback_data=f"adl:confirm:{dq_id}",
                            ),
                        ],
                        [
                            InlineKeyboardButton(
                                "↩️ Вернуть деньги",
                                callback_data=f"adl:refund:{dq_id}",
                            ),
                        ],
                    ]
                ),
            )
        except Exception as e:
            logger.error(f"Failed to notify admin about DL payment: {e}")

    elif data.startswith("dl:cancel:"):
        await query.edit_message_text("Прямая линия отменена. Можешь задать вопрос ИИ → /ask")


async def handle_admin_direct_line_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle admin Direct Line callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("adl:confirm:"):
        dq_id = int(data.split(":")[-1])

        async with get_session() as session:
            dq = await confirm_payment(session, dq_id)
            if dq:
                user = await session.get(
                    type(dq).__mapper__.relationships["user"].mapper.class_,
                    dq.user_id,
                )

                # Notify user
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=(
                            "✅ Оплата получена!\n\n"
                            "Теперь сформулируй свой вопрос Косте.\n"
                            "Можешь текстом или голосовым (до 3 минут).\n\n"
                            "Чем конкретнее — тем полезнее будет ответ."
                        ),
                    )
                    # Set user mode — DQ status is now "paid" in DB,
                    # which is checked by _route_text_to_handler and handle_voice
                    user.current_mode = "direct_line"
                except Exception as e:
                    logger.error(f"Failed to notify user about DL payment confirmation: {e}")

        await query.edit_message_text(
            query.message.text + "\n\n✅ Оплата подтверждена"
        )

    elif data.startswith("adl:refund:"):
        dq_id = int(data.split(":")[-1])

        async with get_session() as session:
            dq = await get_direct_question(session, dq_id)
            if dq:
                dq.status = "refunded"
                user_model = type(dq).__mapper__.relationships["user"].mapper.class_
                user = await session.get(user_model, dq.user_id)

                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text="↩️ Оплата возвращена. Если есть вопросы — напиши @lobanovkv",
                    )
                except Exception:
                    pass

        await query.edit_message_text(
            query.message.text + "\n\n↩️ Возврат оформлен"
        )

    elif data.startswith("adl:answered:"):
        dq_id = int(data.split(":")[-1])
        await query.edit_message_text(
            query.message.text + "\n\n✅ Ответ отправлен"
        )

    elif data.startswith("adl:addkb:"):
        dq_id = int(data.split(":")[-1])

        async with get_session() as session:
            kb_id = await transcribe_and_add_to_kb(session, context.bot, dq_id)

        if kb_id:
            await query.edit_message_text(
                query.message.text + f"\n\n📚 Добавлено в базу знаний (#{kb_id})"
            )
        else:
            await query.edit_message_text(
                query.message.text + "\n\n❌ Не удалось добавить в базу знаний"
            )

    elif data.startswith("adl:morecontext:"):
        dq_id = int(data.split(":")[-1])

        async with get_session() as session:
            dq = await get_direct_question(session, dq_id)
            if dq:
                user_model = type(dq).__mapper__.relationships["user"].mapper.class_
                user = await session.get(user_model, dq.user_id)
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=(
                            "Костя просит уточнить вопрос — ему нужно больше контекста.\n"
                            "Пожалуйста, дополни свой вопрос."
                        ),
                    )
                except Exception:
                    pass

        await query.edit_message_text(
            query.message.text + "\n\n🔄 Запрошено уточнение"
        )
