"""Payment and subscription handlers."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import get_or_create_user
from src.services.subscription_service import format_plan_info
from src.config import get_settings
from src.utils.logger import logger


async def handle_plan_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /plan — show current plan and available upgrades."""
    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)
        text = format_plan_info(user)

    await update.message.reply_text(text)


async def handle_consult_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /consult — information about consulting with Lobanov."""
    text = (
        "📞 Консультация с Константином Лобановым\n\n"
        "Есть два варианта:\n\n"
        "🎤 Прямая линия (1000₽)\n"
        "Задай вопрос — Костя ответит голосовым на 5–10 минут.\n"
        "Без созвонов, в удобное время.\n"
        "→ /ask_kostya\n\n"
        "📞 Полная консультация (от 5000₽)\n"
        "Развёрнутый разговор 30–60 минут.\n"
        "→ Напиши @lobanovkv\n\n"
        "💎 Подписка Pro/Premium\n"
        "Больше вопросов ИИ, веб-дашборд, приоритет.\n"
        "Для активации подписки:\n"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Pro — 990₽/мес", callback_data="pay_pro"
                ),
            ],
            [
                InlineKeyboardButton(
                    "Premium — 4990₽/мес", callback_data="pay_premium"
                ),
            ],
        ]
    )

    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_payment_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle payment tier selection callback."""
    query = update.callback_query
    await query.answer()

    data = query.data  # pay_pro or pay_premium
    tier = data.replace("pay_", "")
    prices = {"pro": 990, "premium": 4990}
    price = prices.get(tier, 990)
    tier_name = {"pro": "Pro 🐺", "premium": "Premium 🐺🔥"}.get(tier, tier)
    settings = get_settings()

    tg_user = update.effective_user

    await query.edit_message_text(
        f"Активация подписки {tier_name} — {price}₽/мес\n\n"
        "Для оплаты:\n"
        "1. Переведи сумму по реквизитам (будут отправлены)\n"
        "2. Напиши «оплатил» или пришли скриншот\n"
        "3. Админ подтвердит — и подписка активируется\n\n"
        "Реквизиты: [будут добавлены]\n\n"
        "После оплаты напиши в чат: «Оплатил подписку»"
    )

    # Notify admin
    try:
        await context.bot.send_message(
            chat_id=settings.admin_chat_id,
            text=(
                f"💰 Запрос на подписку\n\n"
                f"👤 @{tg_user.username or tg_user.first_name}\n"
                f"📋 Тариф: {tier_name} ({price}₽/мес)\n\n"
                f"Подтвердить после оплаты."
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Подтвердить",
                            callback_data=f"confirm_sub_{tg_user.id}_{tier}",
                        ),
                    ]
                ]
            ),
        )
    except Exception as e:
        logger.error(f"Failed to notify admin about payment: {e}")
