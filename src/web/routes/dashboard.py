"""User dashboard routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.web.routes.auth import get_current_user
from src.database.connection import get_session
from src.database.repository import (
    get_user_by_telegram_id,
    get_user_task_stats,
    get_user_active_tasks,
    get_user_recent_messages,
)
from src.services.task_service import format_progress

templates = Jinja2Templates(directory="src/web/templates")

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """User dashboard page."""
    current_user = await get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login")

    async with get_session() as session:
        user = await get_user_by_telegram_id(session, current_user["telegram_id"])
        task_stats = await get_user_task_stats(session, user.id)
        active_tasks = await get_user_active_tasks(session, user.id)
        recent_messages = await get_user_recent_messages(session, user.id, limit=20)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": current_user,
            "task_stats": task_stats,
            "active_tasks": active_tasks,
            "recent_messages": recent_messages,
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page with Telegram widget."""
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": request.query_params.get("error"),
        },
    )
