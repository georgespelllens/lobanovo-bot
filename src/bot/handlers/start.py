"""Start command and onboarding handler."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.database.connection import get_session
from src.database.repository import get_or_create_user, update_user
from src.utils.logger import logger


ONBOARDING_QUESTIONS = [
    {
        "step": 1,
        "text": "Кто ты по уровню?",
        "options": [
            ("Студент", "student"),
            ("Джуниор", "junior"),
            ("Мидл", "middle"),
            ("Сеньор", "senior"),
            ("Руководитель", "lead"),
        ],
        "field": "role",
    },
    {
        "step": 2,
        "text": "Где работаешь?",
        "options": [
            ("Фриланс", "freelance"),
            ("Агентство", "agency"),
            ("Продуктовая компания", "product"),
            ("Учусь", "studying"),
            ("Ищу работу", "searching"),
        ],
        "field": "workplace",
    },
    {
        "step": 3,
        "text": "Есть ли блог?",
        "options": [
            ("Да, веду активно", "active"),
            ("Да, но заброшен", "abandoned"),
            ("Нет", "none"),
        ],
        "field": "has_blog",
    },
    {
        "step": 4,
        "text": "Главная цель?",
        "options": [
            ("Найти работу", "find_job"),
            ("Поднять чек", "raise_price"),
            ("Начать блог", "start_blog"),
            ("Стать спикером", "become_speaker"),
        ],
        "field": "main_goal",
    },
    {
        "step": 5,
        "text": "Сколько часов в неделю готов уделять?",
        "options": [
            ("1–2 часа", "2"),
            ("3–5 часов", "4"),
            ("5–10 часов", "7"),
            ("10+ часов", "12"),
        ],
        "field": "hours_per_week",
    },
]


def determine_level(role: str, has_blog: str, hours: int) -> str:
    """Determine user level based on onboarding answers."""
    score = 0

    # Role scoring
    role_scores = {"student": 0, "junior": 1, "middle": 2, "senior": 3, "lead": 4}
    score += role_scores.get(role, 0)

    # Blog scoring
    if has_blog == "active":
        score += 2
    elif has_blog == "abandoned":
        score += 1

    # Hours scoring
    if hours and hours >= 7:
        score += 1

    if score >= 5:
        return "wolf"
    elif score >= 3:
        return "wolfling"
    return "kitten"


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    tg_user = update.effective_user

    try:
        async with get_session() as session:
            user = await get_or_create_user(
                session,
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
            )

            if user.onboarding_completed:
                # Returning user
                level_emoji = {"kitten": "🐱", "wolfling": "🐺", "wolf": "🐺🔥"}
                emoji = level_emoji.get(user.level, "🐱")

                await update.message.reply_text(
                    f"С возвращением, {tg_user.first_name}! {emoji}\n\n"
                    "Чем могу помочь?\n\n"
                    "💬 Задай вопрос — я отвечу в стиле Лобанова\n"
                    "📝 /audit — разберу твой пост\n"
                    "📋 /tasks — задания на неделю\n"
                    "📊 /progress — твой прогресс\n"
                    "🎤 /ask_kostya — задать вопрос Косте лично"
                )
                return

            # New user — start onboarding
            user.onboarding_step = 0
            user.current_mode = "onboarding"

            await update.message.reply_text(
                f"Привет, {tg_user.first_name}! 👋\n\n"
                "Я — ИИ-помощник Кости Лобанова. "
                "Помогу с личным брендом, карьерой и контентом.\n\n"
                "Для начала, давай познакомимся — "
                "ответь на 5 вопросов, чтобы я понял, как могу помочь."
            )

            # Send first question
            await send_onboarding_question(update, context, step=1)
    except Exception as e:
        logger.error(f"handle_start error for user {tg_user.id}: {type(e).__name__}: {e}")
        raise


async def send_onboarding_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE, step: int
) -> None:
    """Send an onboarding question with inline buttons."""
    if step > len(ONBOARDING_QUESTIONS):
        return

    q = ONBOARDING_QUESTIONS[step - 1]
    keyboard = []
    for label, value in q["options"]:
        keyboard.append(
            [InlineKeyboardButton(label, callback_data=f"onboard:{step}:{value}")]
        )

    reply_markup = InlineKeyboardMarkup(keyboard)

    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Вопрос {step}/5: {q['text']}",
        reply_markup=reply_markup,
    )


async def handle_onboarding_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle onboarding inline button callback."""
    query = update.callback_query
    await query.answer()

    data = query.data  # format: onboard:STEP:VALUE
    parts = data.split(":", 2)
    if len(parts) < 3:
        return

    step = int(parts[1])
    value = parts[2]

    tg_user = update.effective_user

    async with get_session() as session:
        user = await get_or_create_user(session, telegram_id=tg_user.id)

        # Save the answer
        q = ONBOARDING_QUESTIONS[step - 1]
        field = q["field"]

        if field == "hours_per_week":
            setattr(user, field, int(value))
        else:
            setattr(user, field, value)

        user.onboarding_step = step

        # Edit the message to show selected answer
        selected_label = next(
            (label for label, val in q["options"] if val == value), value
        )
        await query.edit_message_text(
            f"Вопрос {step}/5: {q['text']}\n✅ {selected_label}"
        )

        if step < 5:
            # Next question
            await send_onboarding_question(update, context, step + 1)
        else:
            # Onboarding complete
            level = determine_level(
                user.role, user.has_blog, user.hours_per_week
            )
            user.level = level
            user.onboarding_completed = True
            user.current_mode = "qa"

            level_info = {
                "kitten": ("🐱 Котёнок", "мы начнём с базы. Не парься — все так начинали"),
                "wolfling": ("🐺 Волчонок", "у тебя уже есть опыт, будем его упаковывать"),
                "wolf": (
                    "🐺🔥 Волк",
                    "ты уже многое знаешь, поработаем над стратегией",
                ),
            }
            emoji_name, description = level_info.get(
                level, ("🐱 Котёнок", "начнём с базы")
            )

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    f"Готово! Ты — {emoji_name}.\n"
                    f"Это значит, {description}.\n\n"
                    "Что я умею:\n"
                    "💬 Отвечаю на вопросы о личном бренде, карьере и контенте\n"
                    "📝 Разбираю посты по критериям Лобанова (/audit)\n"
                    "📋 Даю еженедельные задания (/tasks)\n"
                    "📊 Отслеживаю твой прогресс (/progress)\n"
                    "🎤 Прямая линия с Костей — задать вопрос лично (/ask_kostya)\n\n"
                    "Начинай — задай мне любой вопрос! 🚀"
                ),
            )

            logger.info(
                f"User {tg_user.id} completed onboarding: level={level}, "
                f"role={user.role}, goal={user.main_goal}"
            )
