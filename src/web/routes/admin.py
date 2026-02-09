"""Admin dashboard routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.web.routes.auth import get_current_user
from src.database.connection import get_session
from src.database.repository import (
    get_admin_stats,
    get_pending_escalations,
    get_all_active_users,
    get_pending_direct_questions,
    get_knowledge_base_stats,
)

templates = Jinja2Templates(directory="src/web/templates")

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Admin dashboard page."""
    current_user = await get_current_user(request)
    if not current_user or not current_user.get("is_admin"):
        return RedirectResponse(url="/login")

    async with get_session() as session:
        stats = await get_admin_stats(session)
        escalations = await get_pending_escalations(session)
        users = await get_all_active_users(session)
        direct_questions = await get_pending_direct_questions(session)
        kb_stats = await get_knowledge_base_stats(session)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": current_user,
            "stats": stats,
            "escalations": escalations,
            "users_list": users[:50],
            "direct_questions": direct_questions,
            "kb_stats": kb_stats,
        },
    )
