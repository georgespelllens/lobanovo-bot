"""Direct Line service — paid personal questions to Lobanov."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from src.database.models import User, DirectQuestion, KnowledgeBase
from src.database.repository import (
    create_direct_question,
    get_direct_question,
    get_weekly_direct_questions_count,
    get_user_recent_messages,
    get_user_task_stats,
)
from src.services.llm_service import call_llm, get_embedding
from src.services.stt_service import transcribe_voice
from src.config import get_settings
from src.utils.logger import logger


async def check_slots_available(session: AsyncSession) -> tuple[bool, int, int]:
    """Check if direct line slots are available this week.
    Returns (available, used, total).
    """
    settings = get_settings()
    used = await get_weekly_direct_questions_count(session)
    total = settings.direct_line_weekly_quota
    return used < total, used, total


async def initiate_direct_question(
    session: AsyncSession, user: User
) -> DirectQuestion:
    """Create a new direct question entry (pending payment)."""
    settings = get_settings()

    dq = await create_direct_question(
        session,
        user_id=user.id,
        payment_amount=settings.direct_line_price_rub,
        status="pending_payment",
        user_context={
            "level": user.level,
            "role": user.role,
            "goal": user.main_goal,
            "xp": user.xp,
            "workplace": user.workplace,
            "has_blog": user.has_blog,
        },
    )

    return dq


async def confirm_payment(
    session: AsyncSession, dq_id: int
) -> DirectQuestion:
    """Confirm payment for a direct question."""
    dq = await get_direct_question(session, dq_id)
    if dq:
        dq.status = "paid"
        dq.payment_confirmed = True
        dq.payment_confirmed_at = datetime.utcnow()
        dq.paid_at = datetime.utcnow()
    return dq


async def submit_question(
    session: AsyncSession,
    dq_id: int,
    question_text: str = None,
    question_voice_file_id: str = None,
    question_voice_transcript: str = None,
) -> DirectQuestion:
    """Submit the actual question after payment."""
    settings = get_settings()
    dq = await get_direct_question(session, dq_id)

    if dq:
        dq.question_text = question_text
        dq.question_voice_file_id = question_voice_file_id
        dq.question_voice_transcript = question_voice_transcript
        dq.question_type = "voice" if question_voice_file_id else "text"
        dq.status = "question_sent"
        dq.deadline_at = datetime.utcnow() + timedelta(
            hours=settings.direct_line_auto_refund_hours
        )

    return dq


async def generate_admin_card(
    session: AsyncSession, dq: DirectQuestion, user: User
) -> str:
    """Generate admin card text for Lobanov."""
    # Get user stats
    task_stats = await get_user_task_stats(session, user.id)

    # Get recent messages for AI summary
    recent = await get_user_recent_messages(session, user.id, limit=20)
    messages_for_summary = "\n".join(
        [f"{'User' if m.role == 'user' else 'Bot'}: {m.content[:200]}" for m in recent]
    )

    # Generate AI summary
    try:
        summary_result = await call_llm(
            [
                {
                    "role": "system",
                    "content": "Кратко (2-3 предложения) резюмируй, о чём ИИ-бот уже отвечал "
                    "пользователю по его теме. Только факты, без оценок.",
                },
                {"role": "user", "content": messages_for_summary},
            ],
            task_type="direct_line_card",
            max_tokens=200,
        )
        ai_summary = summary_result["content"]
    except Exception:
        ai_summary = "Не удалось сгенерировать резюме"

    # Save summary to DQ
    dq.ai_summary = ai_summary

    # Format card
    level_map = {"kitten": "🐱 Котёнок", "wolfling": "🐺 Волчонок", "wolf": "🐺🔥 Волк"}
    tier_label = user.subscription_tier.capitalize()

    question_text = dq.question_text or dq.question_voice_transcript or "[голосовое сообщение]"

    deadline = dq.deadline_at.strftime("%d %B %Y") if dq.deadline_at else "не установлен"

    goal_map = {
        "find_job": "найти работу",
        "raise_price": "поднять чек",
        "start_blog": "начать блог",
        "become_speaker": "стать спикером",
    }
    role_map = {
        "student": "студент",
        "junior": "джуниор",
        "middle": "мидл",
        "senior": "сеньор",
        "lead": "руководитель",
    }

    card = f"""💰 Прямая линия #{dq.id}

👤 @{user.username or 'без username'} ({level_map.get(user.level, user.level)}, {tier_label})
📋 Профиль: {role_map.get(user.role, user.role or '?')}, цель — {goal_map.get(user.main_goal, user.main_goal or '?')}
📊 Активность: {task_stats.get('total', 0)} заданий, {user.xp} XP

🤖 Что бот уже ответил:
{ai_summary}

❓ Вопрос:
«{question_text}»

⏱ Срок ответа: до {deadline}"""

    return card


async def deliver_answer(
    session: AsyncSession,
    bot: Bot,
    dq_id: int,
    voice_file_id: str,
) -> DirectQuestion:
    """Deliver Lobanov's voice answer to the user."""
    dq = await get_direct_question(session, dq_id)
    if not dq:
        return None

    user = await session.get(User, dq.user_id)

    dq.answer_voice_file_id = voice_file_id
    dq.status = "delivered"
    dq.answered_at = datetime.utcnow()
    dq.delivered_at = datetime.utcnow()

    # Send to user
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text="🎤 Костя ответил на твой вопрос!",
        )
        await bot.send_voice(
            chat_id=user.telegram_id,
            voice=voice_file_id,
        )
        await bot.send_message(
            chat_id=user.telegram_id,
            text="Если есть уточняющий вопрос — напиши его прямо сейчас (бесплатно, 1 штука).",
        )
    except Exception as e:
        logger.error(f"Failed to deliver DL answer to user {user.telegram_id}: {e}")

    return dq


async def transcribe_and_add_to_kb(
    session: AsyncSession,
    bot: Bot,
    dq_id: int,
) -> Optional[int]:
    """Transcribe Lobanov's answer and add to knowledge base (anonymized)."""
    dq = await get_direct_question(session, dq_id)
    if not dq or not dq.answer_voice_file_id:
        return None

    # Transcribe
    try:
        import tempfile, os

        file = await bot.get_file(dq.answer_voice_file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        transcript = await transcribe_voice(tmp_path)
        os.remove(tmp_path)

        dq.answer_voice_transcript = transcript
    except Exception as e:
        logger.error(f"Failed to transcribe DL answer: {e}")
        return None

    # Anonymize
    try:
        anon_result = await call_llm(
            [
                {
                    "role": "system",
                    "content": (
                        "Анонимизируй текст для базы знаний. Убери имена, компании, города. "
                        "Замени на обобщения. Сохрани суть совета и стиль Лобанова. "
                        "Результат — как обычный пост-совет."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            task_type="direct_line_anonymize",
            max_tokens=1500,
        )
        anonymized = anon_result["content"]
    except Exception as e:
        logger.error(f"Failed to anonymize DL answer: {e}")
        return None

    # Generate embedding
    try:
        embedding = await get_embedding(anonymized)
    except Exception:
        embedding = None

    # Add to KB
    kb_entry = KnowledgeBase(
        source="direct_line",
        content=anonymized,
        content_summary=f"Ответ из Прямой линии #{dq.id}",
        embedding=embedding,
        category="personal_brand",
        quality_score=0.7,
        is_active=True,
    )
    session.add(kb_entry)
    await session.flush()

    dq.added_to_knowledge_base = True
    dq.knowledge_base_id = kb_entry.id

    logger.info(f"Added DL #{dq.id} answer to KB as entry #{kb_entry.id}")
    return kb_entry.id
