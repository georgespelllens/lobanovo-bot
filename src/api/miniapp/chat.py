"""Mini App: Q&A chat endpoints with SSE streaming."""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.api.miniapp.auth import get_current_user, UserContext
from src.config import get_settings, MODELS
from src.database.connection import get_session
from src.database.repository import (
    get_or_create_conversation,
    get_conversation_messages,
    save_message,
    update_message_rating,
    get_user_by_telegram_id,
)
from src.services.rag_service import get_qa_response, _format_posts_context, QA_SYSTEM_PROMPT
from src.services.llm_service import get_llm_client, get_embedding, calculate_cost
from src.database.repository import search_knowledge_base, get_system_prompt
from src.utils.logger import logger

router = APIRouter()


class ChatMessage(BaseModel):
    message: str


class FeedbackBody(BaseModel):
    rating: int  # 1 or -1


@router.post("/chat")
async def chat_message(body: ChatMessage, user: UserContext = Depends(get_current_user)):
    """Send a chat message and get SSE streaming response."""
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail={"ok": False, "error": {"code": "EMPTY_MESSAGE", "message": "Message cannot be empty"}})

    settings = get_settings()
    if len(text) > settings.max_message_length:
        raise HTTPException(status_code=400, detail={"ok": False, "error": {"code": "MESSAGE_TOO_LONG", "message": f"Message exceeds {settings.max_message_length} characters"}})

    async def event_generator():
        async with get_session() as session:
            # Re-fetch user inside session
            db_user = await get_user_by_telegram_id(session, user.telegram_id)
            if not db_user:
                yield {"event": "error", "data": json.dumps({"code": "AUTH_FAILED"})}
                return

            # Get or create conversation
            conv = await get_or_create_conversation(session, db_user.id, "qa")

            # Save user message
            await save_message(
                session,
                conversation_id=conv.id,
                user_id=db_user.id,
                role="user",
                content=text,
                input_type="text",
            )

            # Get conversation history
            history = await get_conversation_messages(session, conv.id, limit=10)

            # Generate RAG response (non-streaming for now, stream tokens to client)
            try:
                result = await get_qa_response(
                    session,
                    text,
                    user_level=db_user.level or "kitten",
                    user_goal=db_user.main_goal or "",
                    user_role=db_user.role or "",
                    conversation_history=history[:-1],  # exclude the just-saved user msg
                )
            except Exception as e:
                logger.error(f"Chat LLM error: {e}", exc_info=True)
                yield {"event": "message", "data": json.dumps({"type": "error", "content": "Произошла ошибка. Попробуй ещё раз через минуту."})}
                return

            content = result.get("content", "")

            # Stream tokens to client (simulate token-by-token for now)
            # In production, use actual streaming from LLM
            chunk_size = 12  # characters per chunk
            for i in range(0, len(content), chunk_size):
                chunk = content[i : i + chunk_size]
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "token", "content": chunk}),
                }
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
                retrieved_knowledge_ids=result.get("retrieved_knowledge_ids"),
            )

            db_user.last_interaction = datetime.now(timezone.utc)

            # Send done event with message_id
            yield {
                "event": "message",
                "data": json.dumps({"type": "done", "message_id": bot_msg.id}),
            }

    return EventSourceResponse(event_generator())


@router.get("/chat/history")
async def chat_history(
    offset: int = 0,
    limit: int = 20,
    user: UserContext = Depends(get_current_user),
):
    """Get chat history."""
    if limit > 50:
        limit = 50

    async with get_session() as session:
        from src.database.models import Message, Conversation
        from sqlalchemy import select, and_

        # Get recent QA conversations
        conv_result = await session.execute(
            select(Conversation.id)
            .where(
                and_(
                    Conversation.user_id == user.id,
                    Conversation.mode == "qa",
                )
            )
            .order_by(Conversation.last_message_at.desc())
            .limit(5)
        )
        conv_ids = [row[0] for row in conv_result.fetchall()]

        if not conv_ids:
            return {"ok": True, "data": {"messages": [], "has_more": False}}

        # Get messages from those conversations
        msg_result = await session.execute(
            select(Message)
            .where(Message.conversation_id.in_(conv_ids))
            .order_by(Message.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        messages = msg_result.scalars().all()

        has_more = len(messages) > limit
        messages = messages[:limit]
        messages.reverse()  # chronological

        return {
            "ok": True,
            "data": {
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "rating": m.rating,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in messages
                ],
                "has_more": has_more,
            },
        }


@router.post("/chat/{message_id}/feedback")
async def chat_feedback(
    message_id: int,
    body: FeedbackBody,
    user: UserContext = Depends(get_current_user),
):
    """Rate a chat message."""
    if body.rating not in (1, -1):
        raise HTTPException(status_code=400, detail={"ok": False, "error": {"code": "INVALID_RATING", "message": "Rating must be 1 or -1"}})

    async with get_session() as session:
        from src.database.models import Message
        from sqlalchemy import select

        # Verify message belongs to this user
        msg = await session.execute(
            select(Message).where(
                Message.id == message_id,
                Message.user_id == user.id,
            )
        )
        msg = msg.scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "Message not found"}})

        await update_message_rating(session, message_id, body.rating)

    return {"ok": True, "data": {"message_id": message_id, "rating": body.rating}}
