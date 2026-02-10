"""
Generate embeddings and categorize knowledge base posts.

Run after load_knowledge_base.py + filter_quality.py to:
1. Generate vector embeddings for semantic search
2. Auto-categorize posts using LLM
3. Generate summaries for each post

Only processes active posts (is_active=True). Low-quality posts
filtered by filter_quality.py are skipped automatically.

Pipeline:
  1. load_knowledge_base.py --all          # Загрузить посты
  2. filter_quality.py                     # LLM-оценка качества
  3. generate_embeddings.py                # Эмбеддинги ← ВЫ ЗДЕСЬ

Usage:
  python scripts/generate_embeddings.py
  python scripts/generate_embeddings.py --batch-size 20
  python scripts/generate_embeddings.py --only-embeddings
  python scripts/generate_embeddings.py --force --only-embeddings  # clear + regenerate (after model change)
  python scripts/generate_embeddings.py --min-quality 0.5          # only high-quality posts
"""

import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text, func
from src.database.connection import get_session, get_engine
from src.database.models import KnowledgeBase
from src.services.llm_service import get_embedding, call_llm
from src.utils.logger import logger


async def clear_all_embeddings():
    """Clear all embeddings (for re-embedding with new model)."""
    async with get_engine().begin() as conn:
        result = await conn.execute(
            text("UPDATE knowledge_base SET embedding = NULL WHERE embedding IS NOT NULL")
        )
        print(f"Cleared embeddings: {result.rowcount} rows")
    return result.rowcount


async def show_stats():
    """Show current embedding statistics."""
    async with get_session() as session:
        total = await session.execute(select(func.count(KnowledgeBase.id)))
        total = total.scalar()

        active = await session.execute(
            select(func.count(KnowledgeBase.id)).where(KnowledgeBase.is_active == True)
        )
        active = active.scalar()

        with_emb = await session.execute(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.embedding.isnot(None),
                KnowledgeBase.is_active == True,
            )
        )
        with_emb = with_emb.scalar()

        with_cat = await session.execute(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.category.isnot(None),
                KnowledgeBase.is_active == True,
            )
        )
        with_cat = with_cat.scalar()

        with_sum = await session.execute(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.content_summary.isnot(None),
                KnowledgeBase.is_active == True,
            )
        )
        with_sum = with_sum.scalar()

    print(f"\n📊 Состояние базы знаний:")
    print(f"  Всего:       {total}")
    print(f"  Активных:    {active}")
    print(f"  С эмбеддингами: {with_emb}/{active}")
    print(f"  С категорией:   {with_cat}/{active}")
    print(f"  С резюме:       {with_sum}/{active}")
    remaining = active - with_emb
    print(f"  Нужно обработать: {remaining}")


async def generate_embeddings(
    batch_size: int = 10,
    only_embeddings: bool = False,
    force: bool = False,
    min_quality: float = 0.0,
):
    """Generate embeddings for all active posts without them."""

    if force:
        await clear_all_embeddings()

    await show_stats()

    async with get_session() as session:
        # Get active posts without embeddings
        query = select(KnowledgeBase).where(
            KnowledgeBase.embedding.is_(None),
            KnowledgeBase.is_active == True,
        )
        if min_quality > 0:
            query = query.where(KnowledgeBase.quality_score >= min_quality)

        result = await session.execute(query)
        posts = result.scalars().all()

        if not posts:
            print("\n✅ Все активные посты уже имеют эмбеддинги.")
            return

        print(f"\nОбработка {len(posts)} постов...")

        processed = 0
        errors = 0
        total_cost = 0.0

        for i, post in enumerate(posts):
            try:
                # 1. Generate embedding
                embedding = await get_embedding(post.content[:8000])
                post.embedding = embedding

                if not only_embeddings:
                    # 2. Categorize
                    if not post.category:
                        cat_result = await call_llm(
                            [
                                {
                                    "role": "system",
                                    "content": (
                                        "Определи категорию поста. Ответь ОДНИМ словом из списка: "
                                        "career / personal_brand / pr / public_speaking / blog / "
                                        "mindset / pricing / networking / management / agency / "
                                        "antipattern / health / review"
                                    ),
                                },
                                {"role": "user", "content": post.content[:2000]},
                            ],
                            task_type="categorize",
                            max_tokens=10,
                        )
                        category = cat_result["content"].strip().lower().split()[0]
                        # Validate category
                        valid_cats = {
                            "career", "personal_brand", "pr", "public_speaking",
                            "blog", "mindset", "pricing", "networking",
                            "management", "agency", "antipattern", "health", "review",
                        }
                        post.category = category if category in valid_cats else "personal_brand"
                        total_cost += cat_result.get("cost", 0)

                    # 3. Generate summary
                    if not post.content_summary:
                        sum_result = await call_llm(
                            [
                                {
                                    "role": "system",
                                    "content": "Сделай краткое резюме поста в 1–2 предложениях. Без вводных слов.",
                                },
                                {"role": "user", "content": post.content[:2000]},
                            ],
                            task_type="summary",
                            max_tokens=100,
                        )
                        post.content_summary = sum_result["content"]
                        total_cost += sum_result.get("cost", 0)

                processed += 1

                if (i + 1) % batch_size == 0:
                    await session.flush()
                    pct = (i + 1) / len(posts) * 100
                    print(
                        f"  [{i+1}/{len(posts)}] {pct:.0f}% "
                        f"(ошибок: {errors}, ~${total_cost:.3f})"
                    )

                # Small delay to avoid rate limits
                await asyncio.sleep(0.2)

            except Exception as e:
                errors += 1
                logger.error(f"Error processing post #{post.id}: {e}")
                continue

        # Flush remaining batch
        await session.flush()

    print(f"\n✅ Обработано: {processed}/{len(posts)} (ошибок: {errors})")
    if total_cost > 0:
        print(f"💰 Примерная стоимость LLM: ${total_cost:.4f}")

    await show_stats()


def main():
    parser = argparse.ArgumentParser(
        description="Generate embeddings for knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--batch-size", type=int, default=10,
        help="Batch size for DB commits (default: 10)"
    )
    parser.add_argument(
        "--only-embeddings", action="store_true",
        help="Only generate embeddings, skip categorization and summaries"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Clear existing embeddings first (for model migration)"
    )
    parser.add_argument(
        "--min-quality", type=float, default=0.0,
        help="Only process posts with quality_score >= this value (default: 0 = all active)"
    )

    args = parser.parse_args()
    asyncio.run(generate_embeddings(
        args.batch_size,
        args.only_embeddings,
        args.force,
        args.min_quality,
    ))


if __name__ == "__main__":
    main()
