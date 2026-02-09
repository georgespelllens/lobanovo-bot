"""Task assignment and XP management service."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User, UserTask, TaskTemplate
from src.database.repository import (
    get_tasks_for_level,
    assign_task,
    get_user_active_tasks,
    update_user,
)
from src.services.rag_service import get_task_review_response
from src.utils.logger import logger


# XP thresholds for level transitions
LEVEL_THRESHOLDS = {
    "kitten": 0,
    "wolfling": 100,
    "wolf": 300,
}


def get_level_for_xp(xp: int) -> str:
    """Determine level based on XP."""
    if xp >= 300:
        return "wolf"
    elif xp >= 100:
        return "wolfling"
    return "kitten"


def get_week_number() -> int:
    """Get current ISO week number."""
    return datetime.utcnow().isocalendar()[1]


async def assign_weekly_tasks(
    session: AsyncSession, user: User
) -> List[UserTask]:
    """Assign weekly tasks to a user based on their level."""
    week = get_week_number()

    # Get task templates for user's level
    hours = user.hours_per_week or 3
    num_tasks = min(3, max(2, hours // 2))

    templates = await get_tasks_for_level(session, user.level, limit=num_tasks)

    assigned = []
    for template in templates:
        task = await assign_task(session, user.id, template.id, week)
        assigned.append(task)

    logger.info(f"Assigned {len(assigned)} tasks to user {user.telegram_id} (level={user.level})")
    return assigned


async def review_task_submission(
    session: AsyncSession,
    user_task: UserTask,
    submission_text: str,
) -> dict:
    """Review a task submission and award XP."""
    # Get task template
    task_template = await session.get(TaskTemplate, user_task.task_template_id)

    # AI review
    review_result = await get_task_review_response(
        session,
        task_description=task_template.description,
        submission_text=submission_text,
        review_criteria=task_template.review_criteria or "",
    )

    score = review_result.get("score", 0.5)

    # Calculate XP based on score
    base_xp = task_template.xp_reward
    earned_xp = int(base_xp * score)
    earned_xp = max(5, earned_xp)  # Minimum 5 XP for trying

    # Update user task
    user_task.status = "completed"
    user_task.submitted_at = datetime.utcnow()
    user_task.reviewed_at = datetime.utcnow()
    user_task.submission_text = submission_text
    user_task.submission_type = "text"
    user_task.review_text = review_result["content"]
    user_task.review_score = score
    user_task.xp_earned = earned_xp

    # Update user XP and potentially level
    user = await session.get(User, user_task.user_id)
    new_xp = user.xp + earned_xp
    new_level = get_level_for_xp(new_xp)
    level_up = new_level != user.level

    user.xp = new_xp
    user.level = new_level

    return {
        "review_text": review_result["content"],
        "score": score,
        "xp_earned": earned_xp,
        "total_xp": new_xp,
        "level": new_level,
        "level_up": level_up,
    }


def format_progress(user: User, task_stats: dict) -> str:
    """Format user progress for display."""
    level_emoji = {"kitten": "🐱", "wolfling": "🐺", "wolf": "🐺🔥"}
    level_name = {"kitten": "Котёнок", "wolfling": "Волчонок", "wolf": "Волк"}

    emoji = level_emoji.get(user.level, "🐱")
    name = level_name.get(user.level, "Котёнок")

    next_level = None
    xp_to_next = None
    if user.level == "kitten":
        next_level = "🐺 Волчонок"
        xp_to_next = 100 - user.xp
    elif user.level == "wolfling":
        next_level = "🐺🔥 Волк"
        xp_to_next = 300 - user.xp

    text = f"""📊 Твой прогресс

{emoji} Уровень: {name}
⭐ XP: {user.xp}
📝 Заданий выполнено: {task_stats.get('completed', 0)} из {task_stats.get('total', 0)}"""

    if next_level and xp_to_next:
        text += f"\n🎯 До {next_level}: {xp_to_next} XP"

    # Progress bar
    if user.level == "kitten":
        progress = min(user.xp / 100, 1.0)
    elif user.level == "wolfling":
        progress = min((user.xp - 100) / 200, 1.0)
    else:
        progress = 1.0

    bar_length = 10
    filled = int(progress * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    text += f"\n\n[{bar}] {int(progress * 100)}%"

    return text
