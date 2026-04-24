"""Initial schema — pgvector extension + all tables.

Revision ID: 001
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="student"),
        sa.Column("photo_path", sa.String(512)),
        sa.Column("student_id", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_student_id", "users", ["student_id"])

    op.create_table(
        "face_embeddings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_face_embeddings_user_id", "face_embeddings", ["user_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("camera_id", sa.String(64), nullable=False, server_default="cam_01"),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("snapshot_path", sa.String(512)),
        sa.Column("clip_path", sa.String(512)),
        sa.Column("description", sa.Text()),
        sa.Column("metadata", sa.JSON()),
        sa.Column("acknowledged", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_created_at", "events", ["created_at"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # IVFFlat index for fast cosine search on embeddings
    op.execute(
        "CREATE INDEX IF NOT EXISTS face_embedding_cosine_idx "
        "ON face_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)"
    )


def downgrade():
    op.drop_table("settings")
    op.drop_table("events")
    op.drop_table("face_embeddings")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
