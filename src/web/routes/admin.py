"""Admin dashboard routes."""

import asyncio
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.web.routes.auth import get_current_user
from src.database.connection import get_session
from src.config import get_settings
from src.utils.logger import logger
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


@router.post("/admin/api/regenerate-embeddings")
async def api_regenerate_embeddings(
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
):
    """Regenerate all embeddings (clear + create with current model). Requires X-Admin-Token: SECRET_KEY."""
    settings = get_settings()
    if x_admin_token != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid token")

    from src.services.embedding_service import regenerate_all_embeddings

    async def _run():
        try:
            await regenerate_all_embeddings(only_embeddings=True)
        except Exception as e:
            logger.error(f"Regeneration failed: {e}", exc_info=True)

    asyncio.create_task(_run())
    return JSONResponse({"status": "started", "message": "Regeneration running in background"})
