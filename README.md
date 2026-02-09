# Приёмная Лобанова — ИИ-наставник по личному бренду

Telegram-бот + веб-дашборд, который работает как масштабируемая система доступа к наставничеству Константина Лобанова.

## Возможности

- **RAG Q&A** — ответы на вопросы на основе 3000+ постов Лобанова
- **Аудит постов** — разбор контента по 6 критериям
- **Еженедельные задания** — трекинг прогресса котёнок → волчонок → волк
- **Прямая линия с Костей** — платный персональный вопрос с голосовым ответом
- **Веб-дашборд** — статистика и админ-панель

## Стек

- Python 3.11+ / FastAPI / python-telegram-bot 21.x
- PostgreSQL + pgvector
- OpenRouter (Claude Sonnet 4) / OpenAI Whisper
- Railway.com

## Запуск локально

```bash
# 1. Создать виртуальное окружение
python -m venv venv
source venv/bin/activate

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Скопировать и заполнить .env
cp .env.example .env

# 4. Применить миграции
alembic upgrade head

# 5. Запустить
python -m uvicorn src.main:app --reload --port 8000
```

## Загрузка базы знаний

```bash
# Загрузить посты из экспортов каналов
python scripts/load_knowledge_base.py --file data/лобаново.html --source nastavnichestvo_channel --format html
python scripts/load_knowledge_base.py --file data/бородат1.md --source main_channel --format md

# Сгенерировать эмбеддинги
python scripts/generate_embeddings.py

# Загрузить шаблоны заданий
python scripts/seed_tasks.py
```
