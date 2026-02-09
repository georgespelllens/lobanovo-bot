"""Initial migration — create all tables.

Revision ID: 001_initial
Revises: 
Create Date: 2026-02-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # #region agent log
    print("[DEBUG][H1] upgrade() started — attempting to create pgvector extension")
    # #endregion
    # Enable pgvector extension
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # #region agent log
        print("[DEBUG][H1] pgvector extension created successfully")
        # #endregion
    except Exception as e:
        # #region agent log
        print(f"[DEBUG][H1] pgvector extension FAILED: {e}")
        # #endregion
        raise

    # Users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(255)),
        sa.Column("first_name", sa.String(255)),
        sa.Column("last_name", sa.String(255)),
        # Onboarding
        sa.Column("level", sa.String(20), server_default="kitten"),
        sa.Column("xp", sa.Integer(), server_default="0"),
        sa.Column("role", sa.String(20), server_default="student"),
        sa.Column("workplace", sa.String(50)),
        sa.Column("has_blog", sa.String(20)),
        sa.Column("main_goal", sa.String(50)),
        sa.Column("hours_per_week", sa.Integer()),
        sa.Column("onboarding_completed", sa.Boolean(), server_default="false"),
        sa.Column("onboarding_step", sa.Integer(), server_default="0"),
        # Subscription
        sa.Column("subscription_tier", sa.String(20), server_default="free"),
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True)),
        # Weekly limits
        sa.Column("weekly_questions_used", sa.Integer(), server_default="0"),
        sa.Column("weekly_audits_used", sa.Integer(), server_default="0"),
        sa.Column("week_start_date", sa.Date()),
        # Metadata
        sa.Column("is_admin", sa.Boolean(), server_default="false"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_interaction", sa.DateTime(timezone=True)),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        # Mode
        sa.Column("current_mode", sa.String(20), server_default="qa"),
        # Negative feedback
        sa.Column("negative_streak", sa.Integer(), server_default="0"),
    )
    op.create_index("idx_users_telegram_id", "users", ["telegram_id"])
    op.create_index("idx_users_level", "users", ["level"])
    op.create_index("idx_users_subscription", "users", ["subscription_tier"])

    # Knowledge Base
    op.create_table(
        "knowledge_base",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("original_post_id", sa.String(100)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_summary", sa.Text()),
        sa.Column("embedding", Vector(1536)),
        sa.Column("category", sa.String(50)),
        sa.Column("tags", postgresql.ARRAY(sa.Text())),
        sa.Column("quality_score", sa.Float(), server_default="0.5"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("original_date", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_kb_category", "knowledge_base", ["category"])

    # Conversations
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="qa"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("message_count", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
    )
    op.create_index("idx_conv_user", "conversations", ["user_id"])

    # Messages
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("input_type", sa.String(20), server_default="text"),
        sa.Column("retrieved_knowledge_ids", postgresql.ARRAY(sa.Integer())),
        sa.Column("rating", sa.SmallInteger()),
        sa.Column("rating_reason", sa.String(50)),
        sa.Column("tokens_input", sa.Integer()),
        sa.Column("tokens_output", sa.Integer()),
        sa.Column("model_used", sa.String(100)),
        sa.Column("cost_usd", sa.Numeric(10, 6)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_msg_conversation", "messages", ["conversation_id"])
    op.create_index("idx_msg_user", "messages", ["user_id"])
    op.create_index("idx_msg_created", "messages", ["created_at"])

    # Task Templates
    op.create_table(
        "task_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("review_criteria", sa.Text()),
        sa.Column("xp_reward", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("estimated_hours", sa.Float(), server_default="1.0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_tasks_level", "task_templates", ["level"])

    # User Tasks
    op.create_table(
        "user_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "task_template_id",
            sa.Integer(),
            sa.ForeignKey("task_templates.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), server_default="assigned"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("submission_text", sa.Text()),
        sa.Column("submission_type", sa.String(20)),
        sa.Column("review_text", sa.Text()),
        sa.Column("review_score", sa.Float()),
        sa.Column("xp_earned", sa.Integer(), server_default="0"),
        sa.Column("week_number", sa.Integer()),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
    )
    op.create_index("idx_utasks_user", "user_tasks", ["user_id"])
    op.create_index("idx_utasks_status", "user_tasks", ["status"])
    op.create_index("idx_utasks_week", "user_tasks", ["week_number"])

    # Escalations
    op.create_table(
        "escalations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id")),
        sa.Column("trigger_type", sa.String(50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("last_messages", postgresql.JSONB()),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("admin_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_esc_status", "escalations", ["status"])

    # Subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_method", sa.String(50)),
        sa.Column("payment_amount", sa.Integer()),
        sa.Column("payment_confirmed", sa.Boolean(), server_default="false"),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
    )
    op.create_index("idx_sub_user", "subscriptions", ["user_id"])

    # System Prompts
    op.create_table(
        "system_prompts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Feedback
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Direct Questions
    op.create_table(
        "direct_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        # Question
        sa.Column("question_text", sa.Text()),
        sa.Column("question_voice_file_id", sa.String(255)),
        sa.Column("question_voice_transcript", sa.Text()),
        sa.Column("question_type", sa.String(20), server_default="text"),
        # Context
        sa.Column("user_context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ai_summary", sa.Text()),
        sa.Column("admin_card_message_id", sa.BigInteger()),
        # Answer
        sa.Column("answer_voice_file_id", sa.String(255)),
        sa.Column("answer_voice_transcript", sa.Text()),
        sa.Column("answer_voice_duration", sa.Integer()),
        # Follow-up
        sa.Column("followup_question", sa.Text()),
        sa.Column("followup_answer", sa.Text()),
        # Payment
        sa.Column("payment_amount", sa.Integer(), server_default="1000"),
        sa.Column("payment_confirmed", sa.Boolean(), server_default="false"),
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True)),
        # Knowledge base
        sa.Column("added_to_knowledge_base", sa.Boolean(), server_default="false"),
        sa.Column("knowledge_base_id", sa.Integer(), sa.ForeignKey("knowledge_base.id")),
        # Status
        sa.Column("status", sa.String(20), server_default="pending_payment"),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        # Dates
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
    )
    op.create_index("idx_dq_user", "direct_questions", ["user_id"])
    op.create_index("idx_dq_status", "direct_questions", ["status"])

    # #region agent log
    print("[DEBUG][H1][H2] ALL TABLES CREATED SUCCESSFULLY")
    # #endregion


def downgrade() -> None:
    op.drop_table("direct_questions")
    op.drop_table("feedback")
    op.drop_table("system_prompts")
    op.drop_table("subscriptions")
    op.drop_table("escalations")
    op.drop_table("user_tasks")
    op.drop_table("task_templates")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("knowledge_base")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
