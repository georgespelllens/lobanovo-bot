"""
LLM-based quality scoring for knowledge base posts.

Evaluates each post on a 0.0–1.0 scale:
  0.0–0.2  → мусор (репосты, поздравления, опросы без контекста)
  0.3–0.5  → средне (общие рассуждения, мало конкретики)
  0.6–0.8  → хорошо (конкретные советы, кейсы, инструкции)
  0.9–1.0  → отлично (уникальный инсайт Лобанова, антипаттерны, кейсы с цифрами)

Posts with quality < threshold (default 0.3) are marked is_active=False.

Uses grok-4-1-fast-non-reasoning for speed and cost efficiency.
Estimated cost: ~$1.5–3 for 3000 posts.

Pipeline:
  1. load_knowledge_base.py --all          # Загрузить посты
  2. filter_quality.py                     # LLM-оценка качества ← ВЫ ЗДЕСЬ
  3. filter_quality.py --dry-run           # Посмотреть статистику без изменений
  4. filter_quality.py --threshold 0.4     # Поднять порог (жёстче)
  5. generate_embeddings.py                # Эмбеддинги (только active)

Usage:
  python scripts/filter_quality.py                           # Оценить все неоценённые посты
  python scripts/filter_quality.py --dry-run                 # Показать текущую статистику
  python scripts/filter_quality.py --threshold 0.4           # Поднять порог отсечки
  python scripts/filter_quality.py --force                   # Переоценить все посты
  python scripts/filter_quality.py --batch-size 20           # Размер батча
  python scripts/filter_quality.py --sample 10               # Оценить 10 случайных (тест)
"""

import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update, func, text
from src.database.connection import get_session, get_engine
from src.database.models import KnowledgeBase
from src.services.llm_service import call_llm
from src.utils.logger import logger


# ─── Quality scoring prompt ───────────────────────────────

QUALITY_PROMPT = """Ты — эксперт по контент-маркетингу и личному бренду.
Оцени пост из Telegram-канала Константина Лобанова по шкале от 0.0 до 1.0.

Критерии оценки:
- Конкретика: есть цифры, примеры, кейсы? (+)
- Уникальность: авторское мнение Лобанова, а не общие истины? (+)
- Применимость: читатель может что-то сделать после прочтения? (+)
- Глубина: есть анализ, антипаттерны, неочевидные выводы? (+)
- Мусор: репост чужого, поздравление, реклама, опрос без контекста? (−)
- Вода: общие слова без конкретики, мотивация ни о чём? (−)

Шкала:
  0.0–0.2 = мусор (репост, поздравление, опрос, реклама, ссылка без комментария)
  0.3–0.5 = средне (общие рассуждения, мало конкретики, но по теме)
  0.6–0.8 = хорошо (конкретные советы, личный опыт, кейсы)
  0.9–1.0 = отлично (уникальный инсайт, антипаттерн, кейс с цифрами и выводами)

Ответь ТОЛЬКО в формате JSON:
{"score": 0.7, "reason": "краткая причина оценки в 5-10 слов"}"""


DEFAULT_THRESHOLD = 0.3
DEFAULT_BATCH_SIZE = 10


# ─── LLM scoring ─────────────────────────────────────────

async def score_post(content: str) -> tuple[float, str]:
    """Score a single post using LLM. Returns (score, reason)."""
    try:
        result = await call_llm(
            [
                {"role": "system", "content": QUALITY_PROMPT},
                {"role": "user", "content": content[:2000]},
            ],
            task_type="categorize",  # Uses fast model
            max_tokens=50,
            temperature=0.1,  # Low temp for consistent scoring
        )

        response = result["content"].strip()

        # Parse JSON response
        # Handle cases where LLM wraps in ```json
        if "```" in response:
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]

        data = json.loads(response)
        score = float(data.get("score", 0.5))
        reason = data.get("reason", "")

        # Clamp to valid range
        score = max(0.0, min(1.0, score))
        return score, reason

    except json.JSONDecodeError:
        # Try to extract just a number
        import re
        numbers = re.findall(r"0\.\d+|1\.0|0|1", result["content"])
        if numbers:
            return float(numbers[0]), "json_parse_fallback"
        return 0.5, "parse_error"
    except Exception as e:
        logger.error(f"Score error: {e}")
        return 0.5, f"error: {type(e).__name__}"


# ─── Main operations ─────────────────────────────────────

async def show_stats():
    """Show current quality distribution without changes."""
    async with get_session() as session:
        # Total posts
        total = await session.execute(select(func.count(KnowledgeBase.id)))
        total = total.scalar()

        # Active posts
        active = await session.execute(
            select(func.count(KnowledgeBase.id)).where(KnowledgeBase.is_active == True)
        )
        active = active.scalar()

        # Posts with quality_score != default (0.5)
        scored = await session.execute(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.quality_score != 0.5
            )
        )
        scored = scored.scalar()

        # Quality distribution
        buckets_query = """
            SELECT
                CASE
                    WHEN quality_score < 0.2 THEN '0.0-0.2 (мусор)'
                    WHEN quality_score < 0.4 THEN '0.2-0.4 (слабо)'
                    WHEN quality_score < 0.6 THEN '0.4-0.6 (средне)'
                    WHEN quality_score < 0.8 THEN '0.6-0.8 (хорошо)'
                    ELSE '0.8-1.0 (отлично)'
                END as bucket,
                COUNT(*) as cnt
            FROM knowledge_base
            GROUP BY bucket
            ORDER BY bucket
        """
        result = await session.execute(text(buckets_query))
        distribution = result.fetchall()

        # Average quality
        avg = await session.execute(
            select(func.avg(KnowledgeBase.quality_score)).where(
                KnowledgeBase.quality_score != 0.5
            )
        )
        avg_score = avg.scalar()

    print(f"\n{'='*60}")
    print(f"📊 Статистика базы знаний")
    print(f"{'='*60}")
    print(f"  Всего постов:      {total}")
    print(f"  Активных:          {active}")
    print(f"  Неактивных:        {total - active}")
    print(f"  Оценённых LLM:     {scored}")
    print(f"  Не оценённых:      {total - scored}")
    if avg_score:
        print(f"  Средний score:     {avg_score:.2f}")

    if distribution:
        print(f"\n  Распределение качества:")
        for bucket, cnt in distribution:
            bar = "█" * (cnt // max(1, total // 40))
            print(f"    {bucket}: {cnt:>5} {bar}")


async def apply_threshold(threshold: float):
    """Mark posts below threshold as inactive."""
    async with get_session() as session:
        # Deactivate low-quality
        result = await session.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.quality_score < threshold,
                KnowledgeBase.quality_score != 0.5,  # Don't touch unscored
            )
            .values(is_active=False)
        )
        deactivated = result.rowcount

        # Reactivate above threshold (in case threshold was lowered)
        result2 = await session.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.quality_score >= threshold,
                KnowledgeBase.is_active == False,
            )
            .values(is_active=True)
        )
        reactivated = result2.rowcount

    print(f"  Порог: {threshold}")
    print(f"  Деактивировано (score < {threshold}): {deactivated}")
    print(f"  Реактивировано (score >= {threshold}): {reactivated}")


async def score_posts(
    batch_size: int = DEFAULT_BATCH_SIZE,
    threshold: float = DEFAULT_THRESHOLD,
    force: bool = False,
    sample: int = 0,
    dry_run: bool = False,
):
    """Score posts using LLM and apply quality threshold."""

    if dry_run:
        await show_stats()
        return

    async with get_session() as session:
        # Get posts to score
        query = select(KnowledgeBase)
        if not force:
            # Only unscored (default 0.5)
            query = query.where(KnowledgeBase.quality_score == 0.5)

        if sample > 0:
            query = query.order_by(func.random()).limit(sample)

        result = await session.execute(query)
        posts = result.scalars().all()

        if not posts:
            print("Нет постов для оценки (все уже оценены). Используй --force для переоценки.")
            await show_stats()
            return

        print(f"Постов для оценки: {len(posts)}")
        total_cost = 0.0
        scored_count = 0

        for i, post in enumerate(posts):
            try:
                score, reason = await score_post(post.content)
                post.quality_score = score

                scored_count += 1

                if (i + 1) % batch_size == 0:
                    await session.flush()
                    print(
                        f"  [{i+1}/{len(posts)}] "
                        f"последний: {score:.1f} ({reason[:30]})"
                    )

                # Rate limit
                await asyncio.sleep(0.15)

            except Exception as e:
                logger.error(f"Error scoring post #{post.id}: {e}")
                continue

        # Flush remaining
        await session.flush()

    print(f"\n✅ Оценено постов: {scored_count}/{len(posts)}")

    # Apply threshold
    print(f"\nПрименяю порог качества...")
    await apply_threshold(threshold)

    # Show final stats
    await show_stats()

    print(f"\nСледующий шаг: python scripts/generate_embeddings.py")


def main():
    parser = argparse.ArgumentParser(
        description="LLM-based quality scoring for knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s                        Оценить все неоценённые посты
  %(prog)s --dry-run              Показать текущую статистику
  %(prog)s --threshold 0.4        Повысить порог (жёстче)
  %(prog)s --force                Переоценить ВСЕ посты
  %(prog)s --sample 10            Тест на 10 случайных постах
        """,
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Batch size for DB commits (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Quality threshold — posts below this are deactivated (default: {DEFAULT_THRESHOLD})"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-score ALL posts (not just unscored)"
    )
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Score only N random posts (for testing)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show current stats without scoring"
    )

    args = parser.parse_args()

    asyncio.run(score_posts(
        batch_size=args.batch_size,
        threshold=args.threshold,
        force=args.force,
        sample=args.sample,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
