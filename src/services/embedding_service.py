"""Embedding regeneration service (can be triggered via API)."""

import asyncio
from sqlalchemy import select, text

from src.database.connection import get_session, get_engine
from src.database.models import KnowledgeBase
from src.services.llm_service import get_embedding
from src.utils.logger import logger


async def regenerate_all_embeddings(only_embeddings: bool = True) -> dict:
    """Clear and regenerate embeddings for all knowledge base posts."""
    async with get_engine().begin() as conn:
        result = await conn.execute(
            text("UPDATE knowledge_base SET embedding = NULL WHERE embedding IS NOT NULL")
        )
        cleared = result.rowcount
    logger.info(f"Cleared embeddings: {cleared} rows")

    async with get_session() as session:
        result = await session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.embedding.is_(None),
                KnowledgeBase.is_active == True,
            )
        )
        posts = result.scalars().all()

    processed = 0
    errors = 0
    for i, post in enumerate(posts):
        try:
            embedding = await get_embedding(post.content[:8000])
            async with get_session() as session:
                result = await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == post.id))
                p = result.scalar_one()
                p.embedding = embedding
            processed += 1
            if (i + 1) % 10 == 0:
                logger.info(f"Regenerated {i + 1}/{len(posts)}")
            await asyncio.sleep(0.2)
        except Exception as e:
            errors += 1
            logger.error(f"Error post #{post.id}: {e}")

    logger.info(f"Regeneration complete: {processed} ok, {errors} errors")
    return {"cleared": cleared, "processed": processed, "errors": errors, "total": len(posts)}
