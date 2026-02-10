"""Mini App: audit endpoints with SSE streaming."""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.api.miniapp.auth import get_current_user, UserContext
from src.database.connection import get_session
from src.database.repository import (
    get_or_create_conversation,
    save_message,
    get_user_by_telegram_id,
)
from src.services.rag_service import get_audit_response
from src.services.subscription_service import check_weekly_limit, increment_usage
from src.utils.logger import logger

router = APIRouter()


class AuditRequest(BaseModel):
    text: str


@router.post("/audit")
async def audit_post(body: AuditRequest, user: UserContext = Depends(get_current_user)):
    """Submit a post for audit and get SSE streaming response."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail={"ok": False, "error": {"code": "EMPTY_TEXT", "message": "Post text cannot be empty"}})
    if len(text) < 50:
        raise HTTPException(status_code=400, detail={"ok": False, "error": {"code": "TEXT_TOO_SHORT", "message": "Post must be at least 50 characters"}})

    async def event_generator():
        async with get_session() as session:
            db_user = await get_user_by_telegram_id(session, user.telegram_id)
            if not db_user:
                yield {"event": "message", "data": json.dumps({"type": "error", "content": "User not found"})}
                return

            # Check limits
            within_limit, used, max_val = check_weekly_limit(db_user, "audits")
            if not within_limit:
                yield {"event": "message", "data": json.dumps({"type": "error", "content": f"Лимит аудитов на этой неделе исчерпан ({used}/{max_val})"})}
                return

            # Create conversation and save user message
            conv = await get_or_create_conversation(session, db_user.id, "audit")
            await save_message(
                session,
                conversation_id=conv.id,
                user_id=db_user.id,
                role="user",
                content=text,
                input_type="text",
            )

            # Generate audit
            try:
                result = await get_audit_response(session, text, db_user.level)
            except Exception as e:
                logger.error(f"Audit LLM error: {e}", exc_info=True)
                yield {"event": "message", "data": json.dumps({"type": "error", "content": "Ошибка при анализе. Попробуй ещё раз."})}
                return

            content = result.get("content", "")

            # Stream tokens
            chunk_size = 12
            for i in range(0, len(content), chunk_size):
                chunk = content[i : i + chunk_size]
                yield {"event": "message", "data": json.dumps({"type": "token", "content": chunk})}
                await asyncio.sleep(0.02)

            # Save assistant message
            bot_msg = await save_message(
                session,
                conversation_id=conv.id,
                user_id=db_user.id,
                role="assistant",
                content=content,
                tokens_input=result.get("tokens_input"),
                tokens_output=result.get("tokens_output"),
                model_used=result.get("model"),
                cost_usd=result.get("cost"),
            )

            increment_usage(db_user, "audits")
            db_user.last_interaction = datetime.now(timezone.utc)

            yield {"event": "message", "data": json.dumps({"type": "done", "message_id": bot_msg.id})}

    return EventSourceResponse(event_generator())


@router.get("/audit/history")
async def audit_history(
    offset: int = 0,
    limit: int = 10,
    user: UserContext = Depends(get_current_user),
):
    """Get audit history."""
    if limit > 50:
        limit = 50

    async with get_session() as session:
        from src.database.models import Message, Conversation
        from sqlalchemy import select, and_

        # Get audit conversations
        conv_result = await session.execute(
            select(Conversation.id)
            .where(
                and_(
                    Conversation.user_id == user.id,
                    Conversation.mode == "audit",
                )
            )
            .order_by(Conversation.last_message_at.desc())
            .limit(20)
        )
        conv_ids = [row[0] for row in conv_result.fetchall()]

        if not conv_ids:
            return {"ok": True, "data": {"audits": [], "has_more": False}}

        # Get pairs of user+assistant messages (audit request + review)
        msg_result = await session.execute(
            select(Message)
            .where(
                and_(
                    Message.conversation_id.in_(conv_ids),
                    Message.role.in_(["user", "assistant"]),
                )
            )
            .order_by(Message.created_at.desc())
            .offset(offset * 2)  # pairs
            .limit((limit + 1) * 2)
        )
        messages = msg_result.scalars().all()

        # Group into audit pairs
        audits = []
        i = 0
        while i < len(messages) - 1:
            # Messages are desc, so assistant comes before user
            if messages[i].role == "assistant" and messages[i + 1].role == "user":
                preview = messages[i + 1].content[:100] + ("..." if len(messages[i + 1].content) > 100 else "")
                audits.append({
                    "id": messages[i].id,
                    "preview": preview,
                    "review": messages[i].content[:200] + ("..." if len(messages[i].content) > 200 else ""),
                    "created_at": messages[i].created_at.isoformat() if messages[i].created_at else None,
                })
                i += 2
            else:
                i += 1

        has_more = len(audits) > limit
        audits = audits[:limit]

        return {"ok": True, "data": {"audits": audits, "has_more": has_more}}
