"""Episode: the mark of a deleted video.

The owner can delete a video. `deleted_at` hides it at once. Its rows and files are
removed as soon as none of its jobs is running (`packages/core/removal.py`).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_episode_deleted_at"


def upgrade() -> None:
    op.add_column("episode", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f(INDEX), "episode", ["deleted_at"])


def downgrade() -> None:
    op.drop_index(op.f(INDEX), table_name="episode")
    op.drop_column("episode", "deleted_at")
