"""Model calls and usage: the database keeps the billing type honest (FR-29).

Every model call records its billing type: demo, plan or api. Two CHECK constraints on
`model_call` and on `provider_usage` make a wrong record impossible:

* the billing type must be the one of the provider (a call to a paid API cannot be stored
  as covered by a plan, and the other way round);
* only api calls may carry a cost. Plan and demo calls record cost 0.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("model_call", "provider_usage")
BILLING_MATCHES_PROVIDER = (
    "(billing = 'demo') = (provider IN ('demo')) AND "
    "(billing = 'plan') = (provider IN ('claude_plan', 'chatgpt_plan')) AND "
    "(billing = 'api') = (provider IN ('anthropic_api', 'openai_api'))"
)
ONLY_API_CALLS_COST = "billing = 'api' OR cost_usd = 0"


def upgrade() -> None:
    for table in TABLES:
        op.create_check_constraint(
            op.f(f"ck_{table}_billing_matches_provider"), table, BILLING_MATCHES_PROVIDER
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_only_api_calls_cost"), table, ONLY_API_CALLS_COST
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_only_api_calls_cost"), table, type_="check")
        op.drop_constraint(op.f(f"ck_{table}_billing_matches_provider"), table, type_="check")
