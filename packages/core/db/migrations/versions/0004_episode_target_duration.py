"""Episode: its own target length.

Section 11.2: the New episode screen asks for "target duration (45 or 60)". Until now the
length came from the channel alone. `target_duration_s` holds the episode's own choice.
Empty means the channel's length.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_episode_target_duration_in_range"


def upgrade() -> None:
    op.add_column("episode", sa.Column("target_duration_s", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f(CHECK), "episode", "target_duration_s IS NULL OR target_duration_s BETWEEN 15 AND 180"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(CHECK), "episode", type_="check")
    op.drop_column("episode", "target_duration_s")
