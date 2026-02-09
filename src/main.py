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


async def handle_message(update: Update, context) -> None:
    """Route text messages based on user mode."""
    from src.database.connection import get_session
    from src.database.repository import get_or_create_user
    from src.bot.handlers.qa import handle_qa_message
    from src.bot.handlers.audit import handle_audit_message
    from src.services.task_service import review_task_submission
    from src.database.repository import get_user_active_tasks
    from src.services.direct_line_service import submit_question, generate_admin_card

    text = update.message.text
    if not text:
        return

    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)
        mode = user.current_mode or "qa"

    # Check if user is in Direct Line question mode
    dq_key = f"dq_awaiting_{tg_user.id}"
    if dq_key in context.bot_data:
        dq_id = context.bot_data.pop(dq_key)
        settings = get_settings()

        async with get_session() as session:
            user = await get_or_create_user(session, telegram_id=tg_user.id)
            dq = await submit_question(session, dq_id, question_text=text)

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
                                        callback_data=f"adl_answered_{dq.id}",
                                    ),
                                    InlineKeyboardButton(
                                        "⏭ Больше контекста",
                                        callback_data=f"adl_morecontext_{dq.id}",
                                    ),
                                ],
                                [
                                    InlineKeyboardButton(
                                        "↩️ Вернуть деньги",
                                        callback_data=f"adl_refund_{dq.id}",
                                    ),
                                    InlineKeyboardButton(
                                        "📚 В базу знаний",
                                        callback_data=f"adl_addkb_{dq.id}",
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

    # Check if user is submitting a task
    if mode == "qa":
        async with get_session() as session:
            user = await get_or_create_user(session, telegram_id=tg_user.id)
            active_tasks = await get_user_active_tasks(session, user.id)
            pending_tasks = [t for t in active_tasks if t.status == "assigned"]

            # Heuristic: if text is long (>100 chars) and user has pending tasks,
            # treat as task submission
            if pending_tasks and len(text) > 100:
                task = pending_tasks[0]
                result = await review_task_submission(session, task, text)

                response = result["review_text"]
                response += f"\n\n⭐ +{result['xp_earned']} XP"
                response += f"\n📊 Итого: {result['total_xp']} XP"

                if result["level_up"]:
                    level_emoji = {
                        "wolfling": "🐺 Волчонок",
                        "wolf": "🐺🔥 Волк",
                    }
                    new_level = level_emoji.get(result["level"], result["level"])
                    response += f"\n\n🎉 Поздравляю! Ты теперь {new_level}!"

                await update.message.reply_text(response)
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
    get_engine()
    logger.info("Database engine initialized")

    # #region agent log
    # Verify tables exist
    try:
        from sqlalchemy import text as sa_text
        from src.database.connection import get_session
        async with get_session() as session:
            result = await session.execute(sa_text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
            tables = [row[0] for row in result.fetchall()]
            logger.warning(f"[DEBUG][H1][H3] Tables in DB: {tables}")
            logger.warning(f"[DEBUG][H1][H3] 'users' table exists: {'users' in tables}")
    except Exception as e:
        logger.warning(f"[DEBUG][H2][H3] DB table check FAILED: {e}")
    # #endregion

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


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates via webhook."""
    global _bot_app

    if _bot_app is None:
        # #region agent log
        logger.warning("[DEBUG][H5] Webhook called but _bot_app is None!")
        # #endregion
        return {"error": "Bot not initialized"}

    try:
        data = await request.json()
        # #region agent log
        logger.warning(f"[DEBUG][H4] Webhook received update: {data.get('update_id', 'no_id')}, message: {bool(data.get('message'))}")
        # #endregion
        update = Update.de_json(data, _bot_app.bot)
        await _bot_app.process_update(update)
        # #region agent log
        logger.warning(f"[DEBUG][H4] process_update completed for update_id={data.get('update_id')}")
        # #endregion
    except Exception as e:
        # #region agent log
        logger.warning(f"[DEBUG][H3][H4] Webhook exception: {type(e).__name__}: {e}")
        # #endregion
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


# #region agent log
@app.get("/debug/db-check")
async def debug_db_check():
    """Debug endpoint: check if database tables exist."""
    from sqlalchemy import text as sa_text
    from src.database.connection import get_session
    try:
        async with get_session() as session:
            result = await session.execute(sa_text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
            tables = [row[0] for row in result.fetchall()]
            has_users = "users" in tables
            # Check pgvector
            try:
                ext_result = await session.execute(sa_text("SELECT extname FROM pg_extension WHERE extname='vector'"))
                has_pgvector = ext_result.scalar_one_or_none() is not None
            except Exception:
                has_pgvector = False
            return {
                "tables": tables,
                "users_table_exists": has_users,
                "pgvector_installed": has_pgvector,
                "table_count": len(tables),
            }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}
# #endregion
