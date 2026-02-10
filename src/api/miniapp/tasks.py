"""Mini App: tasks endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_

from src.api.miniapp.auth import get_current_user, UserContext
from src.database.connection import get_session
from src.database.models import TaskTemplate, UserTask
from src.database.repository import get_user_by_telegram_id
from src.services.rag_service import get_task_review_response
from src.services.task_service import get_level_for_xp
from src.utils.logger import logger

router = APIRouter()


class TaskSubmission(BaseModel):
    text: str
    type: str = "text"  # text or link


@router.get("/tasks")
async def get_tasks(user: UserContext = Depends(get_current_user)):
    """Get available, in-progress, and completed tasks."""
    async with get_session() as session:
        db_user = await get_user_by_telegram_id(session, user.telegram_id)
        if not db_user:
            raise HTTPException(status_code=401, detail={"ok": False, "error": {"code": "AUTH_FAILED"}})

        level = db_user.level or "kitten"

        # Get all task templates for user's level
        templates_result = await session.execute(
            select(TaskTemplate).where(
                and_(
                    TaskTemplate.level == level,
                    TaskTemplate.is_active == True,
                )
            ).order_by(TaskTemplate.id)
        )
        templates = templates_result.scalars().all()

        # Get user's tasks
        user_tasks_result = await session.execute(
            select(UserTask).where(UserTask.user_id == db_user.id).order_by(UserTask.assigned_at.desc())
        )
        user_tasks = user_tasks_result.scalars().all()

        # Group
        assigned_template_ids = {ut.task_template_id for ut in user_tasks}
        in_progress = []
        completed = []

        for ut in user_tasks:
            # Find template
            template = next((t for t in templates if t.id == ut.task_template_id), None)
            task_data = _format_user_task(ut, template)
            if ut.status in ("assigned", "submitted"):
                in_progress.append(task_data)
            elif ut.status in ("reviewed", "completed"):
                completed.append(task_data)

        # Available = templates not yet assigned
        available = []
        for t in templates:
            if t.id not in assigned_template_ids:
                available.append({
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "category": t.category,
                    "level": t.level,
                    "xp_reward": t.xp_reward,
                    "estimated_hours": t.estimated_hours,
                })

    return {
        "ok": True,
        "data": {
            "available": available,
            "in_progress": in_progress,
            "completed": completed,
        },
    }


@router.get("/tasks/{task_id}")
async def get_task_detail(task_id: int, user: UserContext = Depends(get_current_user)):
    """Get task detail."""
    async with get_session() as session:
        # Try as template ID first
        template = await session.execute(
            select(TaskTemplate).where(TaskTemplate.id == task_id)
        )
        template = template.scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=404, detail={"ok": False, "error": {"code": "NOT_FOUND"}})

        # Check if user has this task
        user_task_result = await session.execute(
            select(UserTask).where(
                and_(
                    UserTask.user_id == user.id,
                    UserTask.task_template_id == task_id,
                )
            ).order_by(UserTask.assigned_at.desc()).limit(1)
        )
        user_task = user_task_result.scalar_one_or_none()

        return {
            "ok": True,
            "data": {
                "task": {
                    "id": template.id,
                    "title": template.title,
                    "description": template.description,
                    "category": template.category,
                    "level": template.level,
                    "xp_reward": template.xp_reward,
                    "estimated_hours": template.estimated_hours,
                    "review_criteria": template.review_criteria,
                },
                "user_task": _format_user_task(user_task, template) if user_task else None,
            },
        }


@router.post("/tasks/{task_id}/submit")
async def submit_task(
    task_id: int,
    body: TaskSubmission,
    user: UserContext = Depends(get_current_user),
):
    """Submit a task solution."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail={"ok": False, "error": {"code": "EMPTY_SUBMISSION"}})

    async with get_session() as session:
        db_user = await get_user_by_telegram_id(session, user.telegram_id)
        if not db_user:
            raise HTTPException(status_code=401, detail={"ok": False, "error": {"code": "AUTH_FAILED"}})

        # Get or assign user task
        user_task_result = await session.execute(
            select(UserTask).where(
                and_(
                    UserTask.user_id == db_user.id,
                    UserTask.task_template_id == task_id,
                    UserTask.status == "assigned",
                )
            ).limit(1)
        )
        user_task = user_task_result.scalar_one_or_none()

        if not user_task:
            # Auto-assign if not yet assigned
            template = await session.execute(
                select(TaskTemplate).where(TaskTemplate.id == task_id)
            )
            template = template.scalar_one_or_none()
            if not template:
                raise HTTPException(status_code=404, detail={"ok": False, "error": {"code": "NOT_FOUND"}})

            user_task = UserTask(
                user_id=db_user.id,
                task_template_id=task_id,
                status="assigned",
            )
            session.add(user_task)
            await session.flush()

        # Get template for review
        template = await session.execute(
            select(TaskTemplate).where(TaskTemplate.id == task_id)
        )
        template = template.scalar_one_or_none()

        # Submit
        user_task.submission_text = text
        user_task.submission_type = body.type
        user_task.submitted_at = datetime.now(timezone.utc)
        user_task.status = "submitted"

        # AI review
        try:
            review = await get_task_review_response(
                session,
                task_description=template.description,
                submission_text=text,
                review_criteria=template.review_criteria or "",
            )
            user_task.review_text = review["content"]
            user_task.review_score = review.get("score", 0.5)
            user_task.reviewed_at = datetime.now(timezone.utc)
            user_task.status = "reviewed"

            # Award XP if score >= 0.4
            if review.get("score", 0) >= 0.4:
                xp_earned = template.xp_reward
                user_task.xp_earned = xp_earned
                user_task.status = "completed"
                db_user.xp = (db_user.xp or 0) + xp_earned
                db_user.level = get_level_for_xp(db_user.xp)
        except Exception as e:
            logger.error(f"Task review error: {e}", exc_info=True)
            # Still save submission even if review fails
            user_task.review_text = "Автоматическая проверка временно недоступна. Задание сохранено."

        db_user.last_interaction = datetime.now(timezone.utc)

        return {
            "ok": True,
            "data": {
                "user_task": _format_user_task(user_task, template),
                "review": user_task.review_text,
            },
        }


def _format_user_task(user_task, template=None) -> dict:
    """Format UserTask + optional template into API response."""
    if user_task is None:
        return None
    data = {
        "id": user_task.id,
        "task_template_id": user_task.task_template_id,
        "status": user_task.status,
        "submission_text": user_task.submission_text,
        "submission_type": user_task.submission_type,
        "review_text": user_task.review_text,
        "review_score": user_task.review_score,
        "xp_earned": user_task.xp_earned,
        "assigned_at": user_task.assigned_at.isoformat() if user_task.assigned_at else None,
        "submitted_at": user_task.submitted_at.isoformat() if user_task.submitted_at else None,
        "reviewed_at": user_task.reviewed_at.isoformat() if user_task.reviewed_at else None,
    }
    if template:
        data["task"] = {
            "title": template.title,
            "description": template.description,
            "category": template.category,
            "xp_reward": template.xp_reward,
            "estimated_hours": template.estimated_hours,
        }
    return data
