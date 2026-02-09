"""
Generate embeddings and categorize knowledge base posts.

Run after load_knowledge_base.py to:
1. Generate vector embeddings for semantic search
2. Auto-categorize posts using LLM
3. Generate summaries for each post

Usage:
  python scripts/generate_embeddings.py
  python scripts/generate_embeddings.py --batch-size 20
  python scripts/generate_embeddings.py --only-embeddings
"""

import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from src.database.connection import get_session
from src.database.models import KnowledgeBase
from src.services.llm_service import get_embedding, call_llm
from src.utils.logger import logger


async def generate_embeddings(batch_size: int = 10, only_embeddings: bool = False):
    """Generate embeddings for all posts without them."""

    async with get_session() as session:
        # Get posts without embeddings
        result = await session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.embedding.is_(None),
                KnowledgeBase.is_active == True,
            )
        )
        posts = result.scalars().all()

        print(f"Постов без эмбеддингов: {len(posts)}")

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
                        post.category = cat_result["content"].strip().lower().split()[0]

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

                if (i + 1) % batch_size == 0:
                    await session.flush()
                    print(f"  Обработано: {i + 1}/{len(posts)}")

                # Small delay to avoid rate limits
                await asyncio.sleep(0.2)

            except Exception as e:
                logger.error(f"Error processing post #{post.id}: {e}")
                continue

    print(f"✅ Обработано постов: {len(posts)}")


def main():
    parser = argparse.ArgumentParser(description="Generate embeddings for knowledge base")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size for DB commits")
    parser.add_argument("--only-embeddings", action="store_true", help="Only generate embeddings, skip categorization")

    args = parser.parse_args()
    asyncio.run(generate_embeddings(args.batch_size, args.only_embeddings))


if __name__ == "__main__":
    main()
