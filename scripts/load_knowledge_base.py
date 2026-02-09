"""
Load Telegram channel exports into the knowledge base.

Supports:
- HTML (Telegram Desktop export) — канал «Лобаново Наставничество»
- MD (text export) — канал «Бородатый, лысый, твой»

Usage:
  python scripts/load_knowledge_base.py --file data/лобаново.html --source nastavnichestvo_channel --format html
  python scripts/load_knowledge_base.py --file data/бородат1.md --source main_channel --format md
  python scripts/load_knowledge_base.py --all  # Load all files from data/
"""

import argparse
import asyncio
import re
import sys
import os
from html.parser import HTMLParser
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.connection import get_session
from src.database.models import KnowledgeBase


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
            if len(text) > 100:
                self.posts.append({"content": text, "date": self.current_date})
            self.in_text = False

    def handle_data(self, data):
        if self.in_text:
            self.current_text.append(data.strip())


# ─── MD Parser (for «Бородатый, лысый, твой») ─────────────

def parse_md_channel(file_path: str) -> list:
    """Parse MD export of Telegram channel."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split by channel name marker
    blocks = re.split(r"Бородатый, лысый, твой", content)
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

        if len(clean) > 100:
            posts.append({"content": clean, "date": date})

    return posts


# ─── Load into DB ─────────────────────────────────────────

async def load_posts(file_path: str, source: str, format: str = "html"):
    """Load posts from a file into the database (idempotent — checks for duplicates by content hash)."""
    import hashlib

    if format == "html":
        parser = TelegramHTMLParser()
        with open(file_path, "r", encoding="utf-8") as f:
            parser.feed(f.read())
        posts = parser.posts
    elif format == "md":
        posts = parse_md_channel(file_path)
    else:
        raise ValueError(f"Unknown format: {format}")

    print(f"Найдено постов: {len(posts)} из {file_path}")

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
        skipped = 0
        for i, post in enumerate(posts):
            content_hash = hashlib.md5(post["content"].encode()).hexdigest()
            if content_hash in existing_hashes:
                skipped += 1
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
                is_active=True,
            )
            session.add(kb_entry)
            existing_hashes.add(content_hash)
            added += 1

            if added % 50 == 0 and added > 0:
                await session.flush()
                print(f"  Загружено: {added}/{len(posts)}")

    print(f"✅ Загружено {added} новых постов из {source} (пропущено дубликатов: {skipped})")


async def load_all():
    """Load all data sources."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

    # Наставничество channel (HTML)
    html_file = os.path.join(data_dir, "лобаново.html")
    if os.path.exists(html_file):
        await load_posts(html_file, "nastavnichestvo_channel", "html")
    else:
        print(f"⚠️  Файл не найден: {html_file}")

    # Main channel (MD, 5 files)
    for i in range(1, 6):
        md_file = os.path.join(data_dir, f"бородат{i}.md")
        if os.path.exists(md_file):
            await load_posts(md_file, "main_channel", "md")
        else:
            print(f"⚠️  Файл не найден: {md_file}")

    print("=" * 50)
    print("✅ Все источники загружены!")
    print("Следующий шаг: python scripts/generate_embeddings.py")


def main():
    parser = argparse.ArgumentParser(description="Load knowledge base from channel exports")
    parser.add_argument("--file", help="Path to export file")
    parser.add_argument("--source", help="Source identifier (nastavnichestvo_channel / main_channel)")
    parser.add_argument("--format", choices=["html", "md"], help="File format")
    parser.add_argument("--all", action="store_true", help="Load all files from data/")

    args = parser.parse_args()

    if args.all:
        asyncio.run(load_all())
    elif args.file and args.source and args.format:
        asyncio.run(load_posts(args.file, args.source, args.format))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
