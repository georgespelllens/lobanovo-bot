"""Main application entry point — FastAPI + Telegram Bot."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from src.config import get_settings
from src.database.connection import get_engine, close_engine
from src.utils.logger import logger

# Bot handlers
from src.bot.handlers.start import handle_start
from src.bot.handlers.audit import handle_audit_command
from src.bot.handlers.tasks import handle_tasks_command, handle_progress_command
from src.bot.handlers.payment import handle_plan_command, handle_consult_command
from src.bot.handlers.direct_line import handle_direct_line_command
from src.bot.handlers.admin import (
    handle_admin_stats,
    handle_admin_escalations,
    handle_admin_top_questions,
    handle_admin_users,
    handle_admin_broadcast,
    handle_admin_add_knowledge,
)
from src.bot.handlers.voice import handle_voice
from src.bot.callbacks import route_callback
from src.bot.scheduler import init_scheduler

# Web routes
from src.web.routes.auth import router as auth_router
from src.web.routes.dashboard import router as dashboard_router
from src.web.routes.admin import router as admin_router

# Mini App API
from src.api.miniapp.router import router as miniapp_router


# ─── Telegram Bot Application ────────────────────────────────

_bot_app: Application = None


async def error_handler(update: object, context) -> None:
    """Log errors caused by updates."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)


def create_bot_application() -> Application:
    """Create and configure the Telegram bot application."""
    settings = get_settings()

    app = Application.builder().token(settings.telegram_bot_token).build()

    # ─── Error handler ───
    app.add_error_handler(error_handler)

    # ─── User commands ───
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("app", handle_open_miniapp))
    app.add_handler(CommandHandler("audit", handle_audit_command))
    app.add_handler(CommandHandler("ask", handle_ask_mode))
    app.add_handler(CommandHandler("progress", handle_progress_command))
    app.add_handler(CommandHandler("tasks", handle_tasks_command))
    app.add_handler(CommandHandler("consult", handle_consult_command))
    app.add_handler(CommandHandler("ask_kostya", handle_direct_line_command))
    app.add_handler(CommandHandler("plan", handle_plan_command))
    app.add_handler(CommandHandler("feedback", handle_feedback))

    # ─── Admin commands ───
    app.add_handler(CommandHandler("admin_stats", handle_admin_stats))
    app.add_handler(CommandHandler("admin_top_questions", handle_admin_top_questions))
    app.add_handler(CommandHandler("admin_escalations", handle_admin_escalations))
    app.add_handler(CommandHandler("admin_users", handle_admin_users))
    app.add_handler(CommandHandler("admin_broadcast", handle_admin_broadcast))
    app.add_handler(CommandHandler("admin_add_knowledge", handle_admin_add_knowledge))

    # ─── Messages ───
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_photo_or_document))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Regex(r"^/"), handle_unknown_command))

    # ─── Callbacks ───
    app.add_handler(CallbackQueryHandler(route_callback))

    return app


# ─── Inline handlers that need to be defined ─────────────────

async def handle_help(update: Update, context) -> None:
    """Handle /help command."""
    await update.message.reply_text(
        "🐺 Приёмная Лобанова — чем могу помочь:\n\n"
        "💬 Просто напиши вопрос — я отвечу в стиле Лобанова\n"
        "📝 /audit — разбор твоего поста по 6 критериям\n"
        "💬 /ask — режим Q&A (вопросы-ответы)\n"
        "📋 /tasks — задания на неделю\n"
        "📊 /progress — твой уровень и прогресс\n"
        "🎤 /ask_kostya — задать вопрос Косте лично (1000₽)\n"
        "📞 /consult — записаться на консультацию\n"
        "💎 /plan — твой тариф и лимиты\n"
        "💌 /feedback — обратная связь\n\n"
        "Голосовые тоже принимаю! 🎙"
    )


async def handle_open_miniapp(update: Update, context) -> None:
    """Handle /app — open Mini App."""
    from telegram import WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup

    settings = get_settings()
    miniapp_url = f"{settings.app_url}/miniapp/"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text="🚀 Открыть приёмную",
            web_app=WebAppInfo(url=miniapp_url),
        )]
    ])

    await update.message.reply_text(
        "Открой приёмную, чтобы увидеть свой прогресс, задания и чат с ментором:",
        reply_markup=keyboard,
    )


async def handle_ask_mode(update: Update, context) -> None:
    """Handle /ask — switch to Q&A mode."""
    from src.database.connection import get_session
    from src.database.repository import get_or_create_user

    async with get_session() as session:
        user = await get_or_create_user(
            session, telegram_id=update.effective_user.id
        )
        user.current_mode = "qa"

    await update.message.reply_text(
        "💬 Режим Q&A включён. Задавай вопросы о личном бренде, карьере и контенте."
    )


async def handle_feedback(update: Update, context) -> None:
    """Handle /feedback command."""
    from src.database.connection import get_session
    from src.database.repository import get_or_create_user, save_feedback

    if context.args:
        text = " ".join(context.args)
        async with get_session() as session:
            user = await get_or_create_user(
                session, telegram_id=update.effective_user.id
            )
            await save_feedback(session, user.id, text)

        await update.message.reply_text("💌 Спасибо за обратную связь! Обязательно прочитаем.")
    else:
        await update.message.reply_text(
            "💌 Напиши свой отзыв или предложение после команды:\n"
            "/feedback Твой текст здесь"
        )


async def handle_photo_or_document(update: Update, context) -> None:
    """Handle photo/document messages — extract caption and route."""
    caption = update.message.caption
    if not caption or not caption.strip():
        # No caption — tell user to send text
        from src.database.connection import get_session
        from src.database.repository import get_or_create_user

        async with get_session() as session:
            user = await get_or_create_user(
                session, telegram_id=update.effective_user.id
            )
            mode = user.current_mode or "qa"

        if mode == "audit":
            await update.message.reply_text(
                "📷 Вижу фото/файл, но без текста.\n"
                "Пришли текст поста обычным сообщением — я его разберу."
            )
        else:
            await update.message.reply_text(
                "📷 Вижу фото/файл, но мне нужен текст.\n"
                "Напиши свой вопрос текстом или голосовым."
            )
        return

    # Has caption — route as regular text message
    logger.info(f"Processing photo/document caption ({len(caption)} chars) from user {update.effective_user.id}")
    await _route_text_to_handler(update, context, caption)


async def handle_message(update: Update, context) -> None:
    """Route text messages based on user mode."""
    text = update.message.text
    if not text:
        return

    await _route_text_to_handler(update, context, text)


async def _route_text_to_handler(update: Update, context, text: str) -> None:
    """Shared routing logic for text messages and photo captions.
    
    Uses a single DB session for the entire handler to avoid consistency issues.
    Direct Line state is checked via DB (not bot_data) to survive restarts.
    """
    from src.database.connection import get_session
    from src.database.repository import get_or_create_user, get_user_active_tasks
    from src.bot.handlers.qa import handle_qa_message
    from src.bot.handlers.audit import handle_audit_message
    from src.services.direct_line_service import submit_question, generate_admin_card
    from src.database.models import DirectQuestion
    from sqlalchemy import select

    tg_user = update.effective_user
    settings = get_settings()

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)
        mode = user.current_mode or "qa"

        # Check if user has a paid Direct Line question awaiting input (DB-based, survives restarts)
        dq_result = await session.execute(
            select(DirectQuestion).where(
                DirectQuestion.user_id == user.id,
                DirectQuestion.status == "paid",
            ).order_by(DirectQuestion.created_at.desc()).limit(1)
        )
        pending_dq = dq_result.scalar_one_or_none()

        if pending_dq:
            # Submit the DL question
            dq = await submit_question(session, pending_dq.id, question_text=text)

            if dq:
                # Generate admin card
                card_text = await generate_admin_card(session, dq, user)

                # Send to admin
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                    admin_msg = await context.bot.send_message(
                        chat_id=settings.admin_chat_id,
                        text=card_text,
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Ответил",
                                        callback_data=f"adl:answered:{dq.id}",
                                    ),
                                    InlineKeyboardButton(
                                        "⏭ Больше контекста",
                                        callback_data=f"adl:morecontext:{dq.id}",
                                    ),
                                ],
                                [
                                    InlineKeyboardButton(
                                        "↩️ Вернуть деньги",
                                        callback_data=f"adl:refund:{dq.id}",
                                    ),
                                    InlineKeyboardButton(
                                        "📚 В базу знаний",
                                        callback_data=f"adl:addkb:{dq.id}",
                                    ),
                                ],
                            ]
                        ),
                    )
                    dq.admin_card_message_id = admin_msg.message_id
                except Exception as e:
                    logger.error(f"Failed to send DL card to admin: {e}")

                user.current_mode = "qa"

                await update.message.reply_text(
                    "✅ Вопрос отправлен Косте!\n\n"
                    "Он получил твой профиль, историю наших разговоров и вопрос.\n"
                    "Ожидай ответ в течение 48 часов ⏳"
                )
            return

        # Check if user has pending tasks and text looks like submission — ask for confirmation
        if mode == "qa":
            active_tasks = await get_user_active_tasks(session, user.id)
            pending_tasks = [t for t in active_tasks if t.status == "assigned"]

            if pending_tasks and len(text) > 100:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                task = pending_tasks[0]
                # Store submission text in user_data for later use
                context.user_data["pending_submission_text"] = text
                context.user_data["pending_submission_task_id"] = task.id

                await update.message.reply_text(
                    "У тебя есть невыполненное задание. Это сдача задания или обычный вопрос?",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "📝 Сдать задание",
                                callback_data=f"submit_task:{task.id}",
                            ),
                            InlineKeyboardButton(
                                "💬 Обычный вопрос",
                                callback_data="continue_qa",
                            ),
                        ]
                    ]),
                )
                return

    # Regular message routing
    if mode == "audit":
        await handle_audit_message(update, context, text)
    else:
        await handle_qa_message(update, context, text)


async def handle_unknown_command(update: Update, context) -> None:
    """Handle unknown commands."""
    await update.message.reply_text(
        "Не знаю такую команду 🤔\nПосмотри список доступных: /help"
    )


# ─── FastAPI Application ─────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    global _bot_app

    settings = get_settings()

    # Initialize DB engine
    engine = get_engine()
    logger.info("Database engine initialized")

    # Verify DB connectivity (tables are created by Alembic in release phase)
    from sqlalchemy import text as sa_text
    async with engine.begin() as conn:
        result = await conn.execute(sa_text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        tables = [row[0] for row in result.fetchall()]
        if "users" in tables:
            logger.info(f"Database OK — {len(tables)} tables found")
        else:
            logger.warning("Tables not found — ensure 'alembic upgrade head' has been run")

    # Initialize Telegram bot
    _bot_app = create_bot_application()
    await _bot_app.initialize()
    await _bot_app.start()

    # Set webhook
    webhook_url = f"{settings.app_url}/webhook"
    await _bot_app.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

    # Initialize scheduler
    init_scheduler(_bot_app.bot)

    yield

    # Shutdown
    logger.info("Shutting down...")
    await _bot_app.stop()
    await _bot_app.shutdown()
    await close_engine()


app = FastAPI(
    title="Приёмная Лобанова",
    description="AI-наставник по личному бренду",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="src/web/static"), name="static")

# Include routers
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(miniapp_router)


# ─── Mini App Static Files ────────────────────────────────────
import os

_miniapp_dist = os.path.join(os.path.dirname(__file__), "web", "miniapp", "dist")
_miniapp_exists = os.path.isdir(_miniapp_dist)
# #region agent log
logger.info(
    "Mini App mount | hypothesis=H1,H2 path=%s exists=%s dirname=%s cwd=%s",
    _miniapp_dist, _miniapp_exists, os.path.dirname(__file__), os.getcwd()
)
# #endregion
if _miniapp_exists:
    app.mount("/miniapp", StaticFiles(directory=_miniapp_dist, html=True), name="miniapp")


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates via webhook."""
    global _bot_app

    if _bot_app is None:
        logger.error("Webhook called but _bot_app is None")
        return {"error": "Bot not initialized"}

    try:
        data = await request.json()
        update = Update.de_json(data, _bot_app.bot)
        await _bot_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}", exc_info=True)

    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index():
    """Landing page."""
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Приёмная Лобанова</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #0f0f0f; color: #e8e8e8;
                display: flex; justify-content: center; align-items: center;
                min-height: 100vh; text-align: center;
            }
            .hero { max-width: 600px; padding: 2rem; }
            h1 { font-size: 2.5rem; margin-bottom: 1rem; }
            .accent { color: #ff6b35; }
            p { color: #888; font-size: 1.1rem; line-height: 1.6; margin-bottom: 1.5rem; }
            .btn {
                display: inline-block; padding: 1rem 2.5rem;
                background: #ff6b35; color: white; border-radius: 8px;
                font-size: 1.1rem; font-weight: 600; text-decoration: none;
                transition: background 0.2s;
            }
            .btn:hover { background: #ff8555; }
            .features { margin-top: 3rem; text-align: left; }
            .feature { padding: 0.75rem 0; border-bottom: 1px solid #222; }
            .feature:last-child { border-bottom: none; }
        </style>
    </head>
    <body>
        <div class="hero">
            <h1>🐺 <span class="accent">Приёмная Лобанова</span></h1>
            <p>ИИ-наставник по личному бренду, карьере и контенту. 
            Работает на базе 3000+ постов Константина Лобанова.</p>
            <a href="https://t.me/lobanov_mentor_bot" class="btn">Открыть бот в Telegram</a>
            
            <div class="features">
                <div class="feature">💬 Ответы на вопросы в стиле Лобанова</div>
                <div class="feature">📝 Аудит постов по 6 критериям</div>
                <div class="feature">📋 Еженедельные задания с трекингом прогресса</div>
                <div class="feature">🎤 Прямая линия с Костей — персональный голосовой ответ</div>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "lobanov-mentor-bot"}

