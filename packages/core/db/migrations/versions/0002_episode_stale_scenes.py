"""Episode: remember which scenes an edit of the spec made stale.

Section 9 gives the episode a marker for stale states (`stale_from_state`). Section 4.2
also asks for scene-level staleness: after an edit, only the affected scenes are spoken
and rendered again. `stale_scenes` holds those scene ids, as
{"voice": [...], "render": [...]}. An empty object means no scene is stale.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "episode",
        sa.Column(
            "stale_scenes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("episode", "stale_scenes")
