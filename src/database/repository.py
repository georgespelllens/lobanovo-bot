"""Database CRUD operations."""

from datetime import datetime, timedelta, date, timezone
from typing import Optional, List

import numpy as np
from sqlalchemy import select, update, func, desc, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    User,
    KnowledgeBase,
    Conversation,
    Message,
    TaskTemplate,
    UserTask,
    Escalation,
    Subscription,
    SystemPrompt,
    Feedback,
    DirectQuestion,
)


# ─── Users ───────────────────────────────────────────────────────────

async def get_or_create_user(session: AsyncSession, telegram_id: int, **kwargs) -> User:
    """Get existing user or create a new one."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, **kwargs)
        session.add(user)
        await session.flush()
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Get user by Telegram ID."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def update_user(session: AsyncSession, user_id: int, **kwargs) -> None:
    """Update user fields."""
    await session.execute(
        update(User).where(User.id == user_id).values(**kwargs)
    )


async def reset_weekly_limits(session: AsyncSession, user_id: int) -> None:
    """Reset weekly question/audit limits."""
    today = date.today()
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            weekly_questions_used=0,
            weekly_audits_used=0,
            week_start_date=today,
        )
    )


async def get_all_active_users(session: AsyncSession) -> List[User]:
    """Get all active users."""
    result = await session.execute(
        select(User).where(User.is_active == True)
    )
    return result.scalars().all()


async def get_admin_users(session: AsyncSession) -> List[User]:
    """Get admin users."""
    result = await session.execute(
        select(User).where(User.is_admin == True)
    )
    return result.scalars().all()


# ─── Knowledge Base ──────────────────────────────────────────────────

async def search_knowledge_base(
    session: AsyncSession,
    embedding: list,
    limit: int = 5,
    min_quality: float = 0.3,
) -> List[KnowledgeBase]:
    """Search knowledge base by cosine similarity (Python-side).

    Loads all active posts with embeddings and computes cosine similarity
    against the query embedding. Returns top-N most similar posts.

    NOTE: For 3000+ posts this is O(n) per query. When pgvector is available,
    switch to server-side cosine_distance for better performance.
    """
    result = await session.execute(
        select(KnowledgeBase).where(
            and_(
                KnowledgeBase.is_active == True,
                KnowledgeBase.embedding.isnot(None),
                KnowledgeBase.quality_score >= min_quality,
            )
        )
    )
    posts = result.scalars().all()

    if not posts or not embedding:
        # Fallback to quality_score ordering if no embedding provided
        result = await session.execute(
            select(KnowledgeBase)
            .where(
                and_(
                    KnowledgeBase.is_active == True,
                    KnowledgeBase.quality_score >= min_quality,
                )
            )
            .order_by(KnowledgeBase.quality_score.desc())
            .limit(limit)
        )
        return result.scalars().all()

    # Python-side cosine similarity
    query_vec = np.array(embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return posts[:limit]

    scored = []
    for post in posts:
        try:
            post_vec = np.array(post.embedding, dtype=np.float32)
            post_norm = np.linalg.norm(post_vec)
            if post_norm == 0:
                continue
            similarity = float(np.dot(query_vec, post_vec) / (query_norm * post_norm))
            scored.append((similarity, post))
        except (TypeError, ValueError):
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [post for _, post in scored[:limit]]


async def add_knowledge_entry(session: AsyncSession, **kwargs) -> KnowledgeBase:
    """Add a new knowledge base entry."""
    entry = KnowledgeBase(**kwargs)
    session.add(entry)
    await session.flush()
    return entry


async def get_knowledge_base_stats(session: AsyncSession) -> dict:
    """Get knowledge base statistics."""
    result = await session.execute(
        select(
            func.count(KnowledgeBase.id).label("total"),
            func.count(KnowledgeBase.embedding).label("with_embeddings"),
        ).where(KnowledgeBase.is_active == True)
    )
    row = result.one()
    return {"total": row.total, "with_embeddings": row.with_embeddings}


# ─── Conversations ───────────────────────────────────────────────────

async def get_or_create_conversation(
    session: AsyncSession, user_id: int, mode: str = "qa"
) -> Conversation:
    """Get active conversation or create a new one."""
    # Check for active conversation (last message within 30 minutes)
    threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
    result = await session.execute(
        select(Conversation)
        .where(
            and_(
                Conversation.user_id == user_id,
                Conversation.mode == mode,
                Conversation.is_active == True,
                Conversation.last_message_at >= threshold,
            )
        )
        .order_by(Conversation.last_message_at.desc())
        .limit(1)
    )
    conv = result.scalar_one_or_none()

    if conv is None:
        # Deactivate old conversations
        await session.execute(
            update(Conversation)
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.is_active == True,
                )
            )
            .values(is_active=False)
        )
        conv = Conversation(user_id=user_id, mode=mode)
        session.add(conv)
        await session.flush()

    return conv


async def get_conversation_messages(
    session: AsyncSession, conversation_id: int, limit: int = 10
) -> List[Message]:
    """Get last N messages from a conversation."""
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return list(reversed(messages))  # chronological order


# ─── Messages ────────────────────────────────────────────────────────

async def save_message(session: AsyncSession, **kwargs) -> Message:
    """Save a message and update conversation."""
    msg = Message(**kwargs)
    session.add(msg)

    # Update conversation
    if msg.conversation_id:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == msg.conversation_id)
            .values(
                last_message_at=datetime.now(timezone.utc),
                message_count=Conversation.message_count + 1,
            )
        )

    await session.flush()
    return msg


async def update_message_rating(
    session: AsyncSession, message_id: int, rating: int, reason: Optional[str] = None
) -> None:
    """Update message rating."""
    await session.execute(
        update(Message)
        .where(Message.id == message_id)
        .values(rating=rating, rating_reason=reason)
    )


async def get_user_recent_messages(
    session: AsyncSession, user_id: int, limit: int = 20
) -> List[Message]:
    """Get recent messages from a user across conversations."""
    result = await session.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return list(reversed(messages))


# ─── Task Templates ──────────────────────────────────────────────────

async def get_tasks_for_level(
    session: AsyncSession, level: str, limit: int = 3
) -> List[TaskTemplate]:
    """Get random active tasks for a given level."""
    result = await session.execute(
        select(TaskTemplate)
        .where(
            and_(
                TaskTemplate.level == level,
                TaskTemplate.is_active == True,
            )
        )
        .order_by(func.random())
        .limit(limit)
    )
    return result.scalars().all()


# ─── User Tasks ──────────────────────────────────────────────────────

async def assign_task(
    session: AsyncSession, user_id: int, task_template_id: int, week_number: int
) -> UserTask:
    """Assign a task to a user."""
    task = UserTask(
        user_id=user_id,
        task_template_id=task_template_id,
        week_number=week_number,
    )
    session.add(task)
    await session.flush()
    return task


async def get_user_active_tasks(session: AsyncSession, user_id: int) -> List[UserTask]:
    """Get user's active (assigned) tasks."""
    result = await session.execute(
        select(UserTask)
        .where(
            and_(
                UserTask.user_id == user_id,
                UserTask.status.in_(["assigned", "submitted"]),
            )
        )
        .order_by(UserTask.assigned_at.desc())
    )
    return result.scalars().all()


async def get_user_task_stats(session: AsyncSession, user_id: int) -> dict:
    """Get task completion stats for a user."""
    result = await session.execute(
        select(
            func.count(UserTask.id).label("total"),
            func.count(UserTask.id).filter(UserTask.status == "completed").label("completed"),
            func.sum(UserTask.xp_earned).label("total_xp"),
        ).where(UserTask.user_id == user_id)
    )
    row = result.one()
    return {
        "total": row.total or 0,
        "completed": row.completed or 0,
        "total_xp": row.total_xp or 0,
    }


# ─── Escalations ────────────────────────────────────────────────────

async def create_escalation(session: AsyncSession, **kwargs) -> Escalation:
    """Create a new escalation."""
    escalation = Escalation(**kwargs)
    session.add(escalation)
    await session.flush()
    return escalation


async def get_pending_escalations(session: AsyncSession) -> List[Escalation]:
    """Get pending escalations."""
    result = await session.execute(
        select(Escalation)
        .where(Escalation.status == "pending")
        .order_by(Escalation.created_at.desc())
    )
    return result.scalars().all()


# ─── System Prompts ──────────────────────────────────────────────────

async def get_system_prompt(session: AsyncSession, name: str) -> Optional[str]:
    """Get active system prompt by name."""
    result = await session.execute(
        select(SystemPrompt.content)
        .where(
            and_(
                SystemPrompt.name == name,
                SystemPrompt.is_active == True,
            )
        )
        .order_by(SystemPrompt.version.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


# ─── Feedback ────────────────────────────────────────────────────────

async def save_feedback(session: AsyncSession, user_id: int, text: str) -> Feedback:
    """Save user feedback."""
    fb = Feedback(user_id=user_id, text=text)
    session.add(fb)
    await session.flush()
    return fb


# ─── Direct Questions ───────────────────────────────────────────────

async def create_direct_question(session: AsyncSession, **kwargs) -> DirectQuestion:
    """Create a new direct line question."""
    dq = DirectQuestion(**kwargs)
    session.add(dq)
    await session.flush()
    return dq


async def get_direct_question(session: AsyncSession, dq_id: int) -> Optional[DirectQuestion]:
    """Get direct question by ID."""
    result = await session.execute(
        select(DirectQuestion).where(DirectQuestion.id == dq_id)
    )
    return result.scalar_one_or_none()


async def get_weekly_direct_questions_count(session: AsyncSession) -> int:
    """Get number of direct questions this week."""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.count(DirectQuestion.id))
        .where(
            and_(
                DirectQuestion.created_at >= week_start,
                DirectQuestion.status.notin_(["pending_payment", "refunded"]),
            )
        )
    )
    return result.scalar() or 0


async def get_pending_direct_questions(session: AsyncSession) -> List[DirectQuestion]:
    """Get questions awaiting Lobanov's answer."""
    result = await session.execute(
        select(DirectQuestion)
        .where(DirectQuestion.status == "question_sent")
        .order_by(DirectQuestion.created_at)
    )
    return result.scalars().all()


async def get_overdue_direct_questions(session: AsyncSession) -> List[DirectQuestion]:
    """Get questions past their deadline."""
    now_utc = datetime.now(timezone.utc)
    result = await session.execute(
        select(DirectQuestion)
        .where(
            and_(
                DirectQuestion.status == "question_sent",
                DirectQuestion.deadline_at <= now_utc,
            )
        )
    )
    return result.scalars().all()


# ─── Admin Stats ─────────────────────────────────────────────────────

async def get_admin_stats(session: AsyncSession) -> dict:
    """Get admin overview statistics."""
    # Total users
    total_users = await session.execute(select(func.count(User.id)))
    total_users = total_users.scalar()

    # Active users (last 7 days)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    active_users = await session.execute(
        select(func.count(User.id)).where(User.last_interaction >= week_ago)
    )
    active_users = active_users.scalar()

    # Total messages today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_messages = await session.execute(
        select(func.count(Message.id)).where(Message.created_at >= today_start)
    )
    today_messages = today_messages.scalar()

    # Average rating
    avg_rating = await session.execute(
        select(func.avg(Message.rating)).where(Message.rating.isnot(None))
    )
    avg_rating = avg_rating.scalar()

    # Subscription breakdown
    sub_counts = await session.execute(
        select(User.subscription_tier, func.count(User.id))
        .group_by(User.subscription_tier)
    )
    subs = {row[0]: row[1] for row in sub_counts}

    # Direct line stats
    dl_total = await session.execute(
        select(func.count(DirectQuestion.id))
        .where(DirectQuestion.status != "pending_payment")
    )
    dl_total = dl_total.scalar()

    dl_revenue = await session.execute(
        select(func.sum(DirectQuestion.payment_amount))
        .where(DirectQuestion.payment_confirmed == True)
    )
    dl_revenue = dl_revenue.scalar() or 0

    return {
        "total_users": total_users,
        "active_users_7d": active_users,
        "messages_today": today_messages,
        "avg_rating": round(float(avg_rating), 2) if avg_rating else None,
        "subscriptions": subs,
        "direct_line_total": dl_total,
        "direct_line_revenue_rub": dl_revenue,
    }
