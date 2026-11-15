"""Episode: what the owner switched on or off for this video.

Director mode forces nothing on a video. Whether facts are looked up, and whether captions
and music are on, is the episode's own choice, stored here. An empty object means every
switch has its default (`packages/core/options.py`).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "episode",
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("episode", "options")
