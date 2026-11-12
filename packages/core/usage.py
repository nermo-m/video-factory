"""Model call logging (FR-17, FR-29): one `model_call` row per call to a model.

The billing type is not passed in. It follows from the provider, and plan and demo calls
record cost 0 ("covered by plan"), whatever a caller believes the call cost. The database
has the same two rules as CHECK constraints (migration 0003).

The function takes a Session and never commits. Call it in the transaction that stores
the job's result, so a call is recorded exactly when its result is.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from packages.core.db.models import ModelCall
from packages.core.enums import Billing, Provider
from packages.core.providers import billing_of

ZERO = Decimal("0")


def record_model_call(
    session: Session,
    *,
    provider: Provider,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    latency_ms: int,
    skill: str | None = None,
    skill_version: str | None = None,
    input_hash: str | None = None,
    job_id: uuid.UUID | None = None,
) -> ModelCall:
    """Store one model call. Returns the new row."""
    billing = billing_of(provider)
    call = ModelCall(
        job_id=job_id,
        provider=provider,
        model=model,
        billing=billing,
        skill=skill,
        skill_version=skill_version,
        input_hash=input_hash,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd if billing is Billing.API else ZERO,
        latency_ms=latency_ms,
    )
    session.add(call)
    session.flush()
    return call
