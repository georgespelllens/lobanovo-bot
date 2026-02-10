"""SQLAlchemy ORM models."""

from datetime import datetime, date, timezone
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    Boolean,
    Float,
    SmallInteger,
    Numeric,
    Date,
    ForeignKey,
    Index,
)
from sqlalchemy.types import DateTime
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship

# pgvector may not be available on all PostgreSQL instances
try:
    from pgvector.sqlalchemy import Vector
    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255))
    first_name = Column(String(255))
    last_name = Column(String(255))

    # Onboarding
    level = Column(String(20), default="kitten")  # kitten / wolfling / wolf
    xp = Column(Integer, default=0)
    role = Column(String(20), default="student")  # student / junior / middle / senior / lead
    workplace = Column(String(50))  # freelance / agency / product / studying / searching
    has_blog = Column(String(20))  # active / abandoned / none
    main_goal = Column(String(50))  # find_job / raise_price / start_blog / become_speaker
    hours_per_week = Column(Integer)
    onboarding_completed = Column(Boolean, default=False)
    onboarding_step = Column(Integer, default=0)

    # Subscription
    subscription_tier = Column(String(20), default="free")  # free / pro / premium
    subscription_expires_at = Column(DateTime(timezone=True))

    # Weekly limits
    weekly_questions_used = Column(Integer, default=0)
    weekly_audits_used = Column(Integer, default=0)
    week_start_date = Column(Date)

    # Metadata
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_interaction = Column(DateTime(timezone=True))
    metadata_ = Column("metadata", JSONB, default=dict)

    # Current bot mode
    current_mode = Column(String(20), default="qa")  # qa / audit / onboarding / task_review / direct_line

    # Negative feedback streak
    negative_streak = Column(Integer, default=0)

    # Mini App
    miniapp_token_hash = Column(String(255))
    miniapp_last_seen = Column(DateTime(timezone=True))

    # Relationships
    conversations = relationship("Conversation", back_populates="user")
    messages = relationship("Message", back_populates="user")
    user_tasks = relationship("UserTask", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user", foreign_keys="Subscription.user_id")
    escalations = relationship("Escalation", back_populates="user")
    feedback_list = relationship("Feedback", back_populates="user")
    direct_questions = relationship("DirectQuestion", back_populates="user")

    __table_args__ = (
        Index("idx_users_level", "level"),
        Index("idx_users_subscription", "subscription_tier"),
    )


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False)  # nastavnichestvo_channel / main_channel / direct_line / manual
    original_post_id = Column(String(100))
    content = Column(Text, nullable=False)
    content_summary = Column(Text)
    # Use JSONB for embeddings (works without pgvector extension)
    # Switch to Vector(1536) when pgvector is available on the DB server
    embedding = Column(JSONB)

    # Classification
    category = Column(String(50))  # career / personal_brand / pr / ...
    tags = Column(ARRAY(Text))

    # Quality
    quality_score = Column(Float, default=0.5)
    is_active = Column(Boolean, default=True)

    # Dates
    original_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_kb_category", "category"),
        Index("idx_kb_quality", quality_score.desc()),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    mode = Column(String(20), nullable=False, default="qa")  # qa / audit / onboarding / task_review
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_message_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    message_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSONB, default=dict)

    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation")

    __table_args__ = (
        Index("idx_conv_user", "user_id"),
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    user_id = Column(Integer, ForeignKey("users.id"))

    role = Column(String(20), nullable=False)  # user / assistant / system
    content = Column(Text, nullable=False)
    input_type = Column(String(20), default="text")  # text / voice / forward / command

    # RAG data
    retrieved_knowledge_ids = Column(ARRAY(Integer))

    # Rating
    rating = Column(SmallInteger)  # 1 (thumbs up) / -1 (thumbs down) / NULL
    rating_reason = Column(String(50))  # off_topic / too_general / wrong_advice / want_human

    # Tokens & cost
    tokens_input = Column(Integer)
    tokens_output = Column(Integer)
    model_used = Column(String(100))
    cost_usd = Column(Numeric(10, 6))

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    user = relationship("User", back_populates="messages")

    __table_args__ = (
        Index("idx_msg_conversation", "conversation_id"),
        Index("idx_msg_user", "user_id"),
        Index("idx_msg_created", "created_at"),
    )


class TaskTemplate(Base):
    __tablename__ = "task_templates"

    id = Column(Integer, primary_key=True)
    level = Column(String(20), nullable=False)  # kitten / wolfling / wolf
    category = Column(String(50), nullable=False)  # blog / speaking / networking / positioning / portfolio
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    review_criteria = Column(Text)
    xp_reward = Column(Integer, nullable=False, default=10)
    estimated_hours = Column(Float, default=1.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    user_tasks = relationship("UserTask", back_populates="task_template")

    __table_args__ = (
        Index("idx_tasks_level", "level"),
    )


class UserTask(Base):
    __tablename__ = "user_tasks"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_template_id = Column(Integer, ForeignKey("task_templates.id"), nullable=False)

    status = Column(String(20), default="assigned")  # assigned / submitted / reviewed / completed / skipped
    assigned_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    submitted_at = Column(DateTime(timezone=True))
    reviewed_at = Column(DateTime(timezone=True))

    # User submission
    submission_text = Column(Text)
    submission_type = Column(String(20))  # text / voice / link

    # AI review
    review_text = Column(Text)
    review_score = Column(Float)  # 0.0-1.0
    xp_earned = Column(Integer, default=0)

    week_number = Column(Integer)
    metadata_ = Column("metadata", JSONB, default=dict)

    # Relationships
    user = relationship("User", back_populates="user_tasks")
    task_template = relationship("TaskTemplate", back_populates="user_tasks")

    __table_args__ = (
        Index("idx_utasks_user", "user_id"),
        Index("idx_utasks_status", "status"),
        Index("idx_utasks_week", "week_number"),
    )


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))

    trigger_type = Column(String(50), nullable=False)  # user_request / negative_feedback / complex_question / wolf_level
    summary = Column(Text, nullable=False)
    last_messages = Column(JSONB)

    status = Column(String(20), default="pending")  # pending / viewed / resolved / converted
    admin_notes = Column(Text)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True))

    # Relationships
    user = relationship("User", back_populates="escalations")

    __table_args__ = (
        Index("idx_esc_status", "status"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tier = Column(String(20), nullable=False)  # pro / premium

    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)

    payment_method = Column(String(50))  # manual / yukassa
    payment_amount = Column(Integer)  # in rubles
    payment_confirmed = Column(Boolean, default=False)
    confirmed_by = Column(Integer, ForeignKey("users.id"))

    is_active = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSONB, default=dict)

    # Relationships
    user = relationship("User", back_populates="subscriptions", foreign_keys=[user_id])

    __table_args__ = (
        Index("idx_sub_user", "user_id"),
    )


class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String(20), default="new")  # new / read / acted_on
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="feedback_list")


class DirectQuestion(Base):
    __tablename__ = "direct_questions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Question
    question_text = Column(Text)
    question_voice_file_id = Column(String(255))
    question_voice_transcript = Column(Text)
    question_type = Column(String(20), default="text")  # text / voice

    # Context (auto-generated for Lobanov)
    user_context = Column(JSONB, nullable=False, default=dict)
    ai_summary = Column(Text)
    admin_card_message_id = Column(BigInteger)

    # Lobanov's answer
    answer_voice_file_id = Column(String(255))
    answer_voice_transcript = Column(Text)
    answer_voice_duration = Column(Integer)

    # Follow-up (free, 1 per question)
    followup_question = Column(Text)
    followup_answer = Column(Text)

    # Payment
    payment_amount = Column(Integer, default=1000)
    payment_confirmed = Column(Boolean, default=False)
    payment_confirmed_at = Column(DateTime(timezone=True))

    # Knowledge base enrichment
    added_to_knowledge_base = Column(Boolean, default=False)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_base.id"))

    # Status & deadlines
    status = Column(String(20), default="pending_payment")
    # pending_payment -> paid -> question_sent -> answered -> delivered -> completed
    # OR: pending_payment -> paid -> question_sent -> refunded

    deadline_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    paid_at = Column(DateTime(timezone=True))
    answered_at = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))

    metadata_ = Column("metadata", JSONB, default=dict)

    # Relationships
    user = relationship("User", back_populates="direct_questions")

    __table_args__ = (
        Index("idx_dq_user", "user_id"),
        Index("idx_dq_status", "status"),
    )
