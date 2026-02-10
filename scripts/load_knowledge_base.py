"""
Load Telegram channel exports into the knowledge base.

Supports:
- HTML (Telegram Desktop export) — канал «Лобаново Наставничество»
- MD (text export) — канал «Бородатый, лысый, твой»

Pipeline:
  1. load_knowledge_base.py --all --dry-run   # Посмотреть статистику (без записи в БД)
  2. load_knowledge_base.py --all             # Загрузить с предфильтрацией
  3. filter_quality.py                        # LLM-оценка качества ($2-3)
  4. generate_embeddings.py                   # Эмбеддинги для семантического поиска

Usage:
  python scripts/load_knowledge_base.py --all --dry-run
  python scripts/load_knowledge_base.py --all
  python scripts/load_knowledge_base.py --file data/лобаново.html --source nastavnichestvo_channel --format html
  python scripts/load_knowledge_base.py --file data/бородат1.md --source main_channel --format md
"""

import argparse
import asyncio
import hashlib
import re
import sys
import os
from html.parser import HTMLParser
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# DB imports are deferred — not needed for --dry-run
_db_imported = False
get_session = None
KnowledgeBase = None


def _ensure_db_imports():
    """Lazy-import DB modules (not needed for --dry-run)."""
    global _db_imported, get_session, KnowledgeBase
    if not _db_imported:
        from src.database.connection import get_session as _gs
        from src.database.models import KnowledgeBase as _kb
        get_session = _gs
        KnowledgeBase = _kb
        _db_imported = True


# ─── Content filters (pre-LLM, rule-based) ────────────────

MIN_CONTENT_LENGTH = 200  # Минимум символов для полезного поста

# Паттерны мусора — посты, которые точно не содержат полезного контента
JUNK_PATTERNS = [
    # Репосты и ссылки без контента
    re.compile(r"^https?://\S+$"),                        # Просто ссылка
    re.compile(r"^(Forwarded from|Переслано из)"),         # Репост
    # Голосования, стикеры, медиа без текста
    re.compile(r"^(Anonymous poll|Quiz)"),                 # Опрос
    re.compile(r"^Photo$|^Video$|^Sticker$"),              # Медиа-заглушки
    # Служебные сообщения
    re.compile(r"^(Pinned message|Channel created)"),      # Системные
    re.compile(r"^(joined|left) the (group|channel)"),     # Входы/выходы
]

# Если >60% текста — ссылки, это не контент
URL_RATIO_THRESHOLD = 0.6


def is_junk_content(text: str) -> str | None:
    """Check if content is junk. Returns reason string or None if OK."""
    # Длина
    if len(text) < MIN_CONTENT_LENGTH:
        return f"too_short ({len(text)} < {MIN_CONTENT_LENGTH})"

    # Паттерны мусора
    for pattern in JUNK_PATTERNS:
        if pattern.search(text):
            return f"junk_pattern ({pattern.pattern[:40]})"

    # Слишком много ссылок
    urls = re.findall(r"https?://\S+", text)
    url_chars = sum(len(u) for u in urls)
    if len(text) > 0 and url_chars / len(text) > URL_RATIO_THRESHOLD:
        return f"mostly_links ({url_chars}/{len(text)} = {url_chars/len(text):.0%})"

    # Слишком много эмодзи / мало букв (поздравления, реакции)
    letters = len(re.findall(r"[а-яА-Яa-zA-Z]", text))
    if len(text) > 0 and letters / len(text) < 0.3:
        return f"low_text_ratio ({letters}/{len(text)} = {letters/len(text):.0%})"

    return None


# ─── HTML Parser (for «Лобаново Наставничество») ─────────

class TelegramHTMLParser(HTMLParser):
    """Parser for Telegram Desktop HTML export."""

    def __init__(self):
        super().__init__()
        self.posts = []
        self.current_text = []
        self.current_date = None
        self.in_text = False

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "")
        if "text" in classes and "from_name" not in classes and "date" not in classes:
            self.in_text = True
            self.current_text = []
        if "date details" in classes:
            title = dict(attrs).get("title", "")
            if title:
                self.current_date = title

    def handle_endtag(self, tag):
        if self.in_text and tag == "div":
            text = " ".join(self.current_text).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                self.posts.append({"content": text, "date": self.current_date})
            self.in_text = False

    def handle_data(self, data):
        if self.in_text:
            self.current_text.append(data.strip())


# ─── MD Parser (for «Бородатый, лысый, твой») ─────────────

def parse_md_channel(file_path: str, channel_name: str = None) -> list:
    """Parse MD export of Telegram channel.
    
    Auto-detects channel name from first line if not provided.
    Splits content by channel name marker to extract individual posts.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Auto-detect channel name: pick the candidate with most occurrences
    if not channel_name:
        candidates = [
            "Бородатый, лысый, твой",
            "Лобаново Наставничество",
        ]
        best_name = None
        best_count = 0
        for c in candidates:
            count = content.count(c)
            if count > best_count:
                best_count = count
                best_name = c
        channel_name = best_name or "Бородатый, лысый, твой"

    # Split by channel name marker
    blocks = re.split(re.escape(channel_name), content)
    posts = []

    for block in blocks:
        # Extract date if present
        date_match = re.search(r"(\d{1,2}\.\d{2}\.\d{4})", block)
        date_str = date_match.group(1) if date_match else None

        # Parse date
        date = None
        if date_str:
            try:
                date = datetime.strptime(date_str, "%d.%m.%Y")
            except ValueError:
                pass

        # Clean metadata
        clean = block
        clean = re.sub(r"PhotoNot included.*?KB", "", clean)
        clean = re.sub(r"Video fileNot included.*?MB", "", clean)
        clean = re.sub(r"StickerNot included.*?KB", "", clean)
        clean = re.sub(r"\[Previous messages\]\(.*?\)", "", clean)
        clean = re.sub(r"Anonymous poll.*?votes", "", clean, flags=re.DOTALL)
        # Remove reactions
        clean = re.sub(r"[🔥❤👍🌚😁⭐🫡💯❤‍🔥👋🌭🍓👾💩🗿]\d*", "", clean)
        # Remove markdown bold
        clean = re.sub(r"\*\*", "", clean)
        # Normalize whitespace
        clean = re.sub(r"\s+", " ", clean).strip()

        if clean:
            posts.append({"content": clean, "date": date})

    return posts


# ─── Parsing dispatcher ───────────────────────────────────

def parse_file(file_path: str, format: str) -> list:
    """Parse a file and return raw posts. Auto-detects channel name for MD."""
    if format == "html":
        parser = TelegramHTMLParser()
        with open(file_path, "r", encoding="utf-8") as f:
            parser.feed(f.read())
        return parser.posts
    elif format == "md":
        return parse_md_channel(file_path)  # Auto-detects channel name
    else:
        raise ValueError(f"Unknown format: {format}")


def filter_posts(posts: list) -> tuple[list, dict]:
    """Apply rule-based filters. Returns (good_posts, stats)."""
    stats = {"total_parsed": len(posts), "accepted": 0, "rejected": {}}
    good = []

    for post in posts:
        reason = is_junk_content(post["content"])
        if reason:
            bucket = reason.split(" ")[0]  # e.g. "too_short"
            stats["rejected"][bucket] = stats["rejected"].get(bucket, 0) + 1
        else:
            good.append(post)
            stats["accepted"] += 1

    return good, stats


# ─── Dry-run: statistics only ─────────────────────────────

def print_dry_run_stats(source: str, file_path: str, posts_raw: list, posts_good: list, stats: dict):
    """Print detailed statistics without writing to DB."""
    print(f"\n{'='*60}")
    print(f"📊 {source} — {os.path.basename(file_path)}")
    print(f"{'='*60}")
    print(f"  Спарсено:       {stats['total_parsed']}")
    print(f"  Принято:        {stats['accepted']} ({stats['accepted']/max(stats['total_parsed'],1)*100:.0f}%)")
    print(f"  Отфильтровано:  {stats['total_parsed'] - stats['accepted']}")

    if stats["rejected"]:
        print(f"  Причины отсева:")
        for reason, count in sorted(stats["rejected"].items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}")

    if posts_good:
        lengths = [len(p["content"]) for p in posts_good]
        print(f"\n  Длина постов (принятых):")
        print(f"    мин:     {min(lengths)} симв.")
        print(f"    медиана: {sorted(lengths)[len(lengths)//2]} симв.")
        print(f"    макс:    {max(lengths)} симв.")
        print(f"    средняя: {sum(lengths)/len(lengths):.0f} симв.")

        # Distribution by length buckets
        buckets = {"200-500": 0, "500-1000": 0, "1000-2000": 0, "2000+": 0}
        for l in lengths:
            if l < 500:
                buckets["200-500"] += 1
            elif l < 1000:
                buckets["500-1000"] += 1
            elif l < 2000:
                buckets["1000-2000"] += 1
            else:
                buckets["2000+"] += 1
        print(f"    распределение: {buckets}")

        # Date range
        dates = [p["date"] for p in posts_good if p.get("date")]
        if dates:
            date_objs = []
            for d in dates:
                if isinstance(d, datetime):
                    date_objs.append(d)
                elif isinstance(d, str):
                    try:
                        date_objs.append(datetime.strptime(d, "%d.%m.%Y %H:%M:%S"))
                    except ValueError:
                        pass
            if date_objs:
                print(f"\n  Даты постов:")
                print(f"    от: {min(date_objs).strftime('%d.%m.%Y')}")
                print(f"    до: {max(date_objs).strftime('%d.%m.%Y')}")

    # Show examples of filtered content
    rejected_examples = [p for p in posts_raw if is_junk_content(p["content"])]
    if rejected_examples:
        print(f"\n  Примеры отфильтрованных (первые 3):")
        for p in rejected_examples[:3]:
            reason = is_junk_content(p["content"])
            preview = p["content"][:80].replace("\n", " ")
            print(f"    [{reason}] «{preview}...»")


# ─── Load into DB ─────────────────────────────────────────

async def load_posts(file_path: str, source: str, format: str = "html", dry_run: bool = False):
    """Load posts from a file into the database.

    Applies rule-based pre-filtering. Idempotent (checks content hashes).
    Use --dry-run to preview statistics without writing.
    """
    posts_raw = parse_file(file_path, format)
    posts_good, stats = filter_posts(posts_raw)

    if dry_run:
        print_dry_run_stats(source, file_path, posts_raw, posts_good, stats)
        return stats

    # Only import DB when actually writing
    _ensure_db_imports()

    print(f"Найдено постов: {len(posts_raw)}, после фильтрации: {len(posts_good)} из {file_path}")

    async with get_session() as session:
        # Get existing content hashes for this source to avoid duplicates
        from sqlalchemy import select
        existing_result = await session.execute(
            select(KnowledgeBase.content).where(KnowledgeBase.source == source)
        )
        existing_hashes = {
            hashlib.md5(row[0].encode()).hexdigest()
            for row in existing_result.fetchall()
        }

        added = 0
        skipped_dup = 0
        for i, post in enumerate(posts_good):
            content_hash = hashlib.md5(post["content"].encode()).hexdigest()
            if content_hash in existing_hashes:
                skipped_dup += 1
                continue

            date = post.get("date")
            if isinstance(date, str):
                try:
                    date = datetime.strptime(date, "%d.%m.%Y %H:%M:%S")
                except (ValueError, TypeError):
                    date = None

            kb_entry = KnowledgeBase(
                source=source,
                content=post["content"],
                original_date=date,
                quality_score=0.5,  # Default — will be scored by filter_quality.py
                is_active=True,
            )
            session.add(kb_entry)
            existing_hashes.add(content_hash)
            added += 1

            if added % 50 == 0 and added > 0:
                await session.flush()
                print(f"  Загружено: {added}/{len(posts_good)}")

    print(
        f"✅ Загружено {added} новых постов из {source} "
        f"(дубликатов: {skipped_dup}, отфильтровано: {stats['total_parsed'] - stats['accepted']})"
    )
    return stats


async def load_all(dry_run: bool = False):
    """Load all data sources."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

    total_stats = {"total_parsed": 0, "accepted": 0, "rejected": {}}

    def merge_stats(s):
        total_stats["total_parsed"] += s["total_parsed"]
        total_stats["accepted"] += s["accepted"]
        for k, v in s["rejected"].items():
            total_stats["rejected"][k] = total_stats["rejected"].get(k, 0) + v

    # Наставничество channel (MD or HTML)
    # Try MD first (more common export), then HTML
    md_nastavnichestvo = os.path.join(data_dir, "лобаново.md")
    html_nastavnichestvo = os.path.join(data_dir, "лобаново.html")
    if os.path.exists(md_nastavnichestvo):
        s = await load_posts(md_nastavnichestvo, "nastavnichestvo_channel", "md", dry_run)
        if s:
            merge_stats(s)
    elif os.path.exists(html_nastavnichestvo):
        s = await load_posts(html_nastavnichestvo, "nastavnichestvo_channel", "html", dry_run)
        if s:
            merge_stats(s)
    else:
        print(f"⚠️  Файл не найден: {md_nastavnichestvo} или {html_nastavnichestvo}")

    # Main channel (MD, 5 files)
    for i in range(1, 6):
        md_file = os.path.join(data_dir, f"бородат{i}.md")
        if os.path.exists(md_file):
            s = await load_posts(md_file, "main_channel", "md", dry_run)
            if s:
                merge_stats(s)
        else:
            print(f"⚠️  Файл не найден: {md_file}")

    # Summary
    print(f"\n{'='*60}")
    print(f"📊 ИТОГО по всем источникам")
    print(f"{'='*60}")
    print(f"  Спарсено:       {total_stats['total_parsed']}")
    print(f"  Принято:        {total_stats['accepted']}")
    rejected_total = total_stats["total_parsed"] - total_stats["accepted"]
    print(f"  Отфильтровано:  {rejected_total}")
    if total_stats["rejected"]:
        for reason, count in sorted(total_stats["rejected"].items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}")

    if not dry_run:
        print(f"\n✅ Все источники загружены!")
        print(f"Следующий шаг: python scripts/filter_quality.py")
    else:
        print(f"\n💡 Это dry-run. Для загрузки убери --dry-run")


def main():
    parser = argparse.ArgumentParser(description="Load knowledge base from channel exports")
    parser.add_argument("--file", help="Path to export file")
    parser.add_argument("--source", help="Source identifier (nastavnichestvo_channel / main_channel)")
    parser.add_argument("--format", choices=["html", "md"], help="File format")
    parser.add_argument("--all", action="store_true", help="Load all files from data/")
    parser.add_argument("--dry-run", action="store_true", help="Parse and show statistics without writing to DB")

    args = parser.parse_args()

    if args.all:
        asyncio.run(load_all(dry_run=args.dry_run))
    elif args.file and args.source and args.format:
        asyncio.run(load_posts(args.file, args.source, args.format, dry_run=args.dry_run))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
