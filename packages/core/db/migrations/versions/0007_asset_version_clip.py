"""Asset version: the clip made from this picture.

A clip is made from one version of a picture, by the open video model on the owner's
graphics card. It is stored with that version, so a picture that is made again has no
clip until one is made from the new picture.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("asset_version", sa.Column("clip_path", sa.Text(), nullable=True))
    op.add_column("asset_version", sa.Column("clip_prompt", sa.Text(), nullable=True))
    op.add_column("asset_version", sa.Column("clip_model", sa.String(120), nullable=True))
    op.add_column("asset_version", sa.Column("clip_s", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("asset_version", "clip_s")
    op.drop_column("asset_version", "clip_model")
    op.drop_column("asset_version", "clip_prompt")
    op.drop_column("asset_version", "clip_path")
