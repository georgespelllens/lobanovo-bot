"""Escalation service — routing complex questions to Lobanov."""

from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from src.database.models import User, Escalation, Message
from src.database.repository import (
    create_escalation,
    get_user_recent_messages,
)
from src.services.llm_service import call_llm
from src.config import get_settings
from src.utils.logger import logger


async def should_escalate(user: User, message_text: str) -> Optional[str]:
    """Check if a message should trigger escalation. Returns trigger type or None."""

    text_lower = message_text.lower()

    # Direct request keywords
    escalation_keywords = [
        "хочу поговорить с костей",
        "нужна консультация",
        "хочу консультацию",
        "поговорить с лобановым",
        "хочу к косте",
        "записаться на консультацию",
        "связаться с костей",
    ]
    for keyword in escalation_keywords:
        if keyword in text_lower:
            return "user_request"

    # Wolf-level users with complex questions
    if user.level == "wolf":
        complex_indicators = ["стратегия", "выбрать между", "два оффера", "не знаю куда"]
        for ind in complex_indicators:
            if ind in text_lower:
                return "wolf_level"

    # Negative feedback streak
    if user.negative_streak >= 3:
        return "negative_feedback"

    return None


async def create_escalation_summary(
    session: AsyncSession, user: User, trigger_type: str
) -> str:
    """Generate a summary for the escalation card."""

    # Get recent messages
    recent = await get_user_recent_messages(session, user.id, limit=5)
    messages_text = "\n".join(
        [f"{'👤' if m.role == 'user' else '🤖'} {m.content[:200]}" for m in recent]
    )

    result = await call_llm(
        [
            {
                "role": "system",
                "content": "Ты — системный помощник. Сделай краткую сводку (2-3 предложения) "
                "о чём пользователь общается с ботом и почему нужна эскалация к живому Лобанову.",
            },
            {
                "role": "user",
                "content": f"Причина эскалации: {trigger_type}\n\nПоследние сообщения:\n{messages_text}",
            },
        ],
        task_type="summary",
        max_tokens=200,
    )

    return result["content"]


async def process_escalation(
    session: AsyncSession,
    bot: Bot,
    user: User,
    conversation_id: int,
    trigger_type: str,
) -> Escalation:
    """Process an escalation — create record and notify admin."""
    settings = get_settings()

    # Generate summary
    summary = await create_escalation_summary(session, user, trigger_type)

    # Get last messages for context
    recent = await get_user_recent_messages(session, user.id, limit=5)
    last_messages = [
        {"role": m.role, "content": m.content[:300], "created_at": str(m.created_at)}
        for m in recent
    ]

    # Create escalation record
    escalation = await create_escalation(
        session,
        user_id=user.id,
        conversation_id=conversation_id,
        trigger_type=trigger_type,
        summary=summary,
        last_messages=last_messages,
    )

    # Notify admin channel
    level_map = {"kitten": "🐱 Котёнок", "wolfling": "🐺 Волчонок", "wolf": "🐺🔥 Волк"}
    tier_label = user.subscription_tier.upper()
    trigger_labels = {
        "user_request": "Прямой запрос",
        "negative_feedback": "3x 👎 подряд",
        "complex_question": "Сложный вопрос",
        "wolf_level": "Уровень Волк — нужна стратегия",
    }

    admin_text = f"""🔔 Эскалация #{escalation.id}

👤 @{user.username or 'без username'} ({level_map.get(user.level, user.level)}, {tier_label})
📋 Причина: {trigger_labels.get(trigger_type, trigger_type)}
💬 Сводка: {summary}

Последние сообщения:
"""
    for msg in last_messages[-5:]:
        role_icon = "👤" if msg["role"] == "user" else "🤖"
        admin_text += f"{role_icon} {msg['content'][:150]}\n"

    try:
        await bot.send_message(
            chat_id=settings.admin_chat_id,
            text=admin_text,
        )
    except Exception as e:
        logger.error(f"Failed to send escalation to admin: {e}")

    return escalation


def get_escalation_response(trigger_type: str) -> str:
    """Get user-facing escalation message."""
    if trigger_type == "user_request":
        return (
            "Понял! Есть два варианта связи с Костей:\n\n"
            "🎤 Прямая линия (1000₽) — задай вопрос, Костя ответит голосовым на 5–10 минут. "
            "Быстро и без созвонов → /ask_kostya\n\n"
            "📞 Полная консультация (от 5000₽) — если нужен развёрнутый разговор → @lobanovkv\n\n"
            "Прямая линия — самый быстрый способ получить персональный ответ от Кости."
        )
    elif trigger_type == "negative_feedback":
        return (
            "Вижу, что мои ответы пока не попадают в точку. Предлагаю два варианта:\n\n"
            "🎤 Прямая линия (1000₽) — задай вопрос напрямую Косте, "
            "он ответит голосовым → /ask_kostya\n\n"
            "📞 Или запишись на полную консультацию → @lobanovkv\n\n"
            "Иногда живой человек нужнее любого ИИ."
        )
    else:
        return (
            "Это тот случай, когда лучше поговорить с Костей напрямую.\n\n"
            "🎤 Прямая линия (1000₽) — задай вопрос, получи голосовой ответ "
            "на 5–10 минут → /ask_kostya\n\n"
            "📞 Полная консультация (от 5000₽) → @lobanovkv"
        )
