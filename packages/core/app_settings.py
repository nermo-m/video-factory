"""Settings the owner changes in the interface, kept in the `setting` table.

Non-secret values only (NFR-01). Secrets and the provider mode come from the environment
and cannot be changed here.

Functions take a Session and never commit. The caller owns the transaction.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from packages.core.db.models import Setting

# The owner's confirmation that paid APIs may be used (section 3.4). Off unless stored true.
USE_PAID_APIS = "use_paid_apis"


def get_value(session: Session, key: str, default: Any = None) -> Any:
    found = session.scalar(select(Setting.value).where(Setting.key == key))
    return default if found is None else found


def set_value(session: Session, key: str, value: Any) -> None:
    """Store a value, replacing an earlier one."""
    statement = insert(Setting).values(key=key, value=value)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[Setting.key], set_={"value": statement.excluded.value}
        )
    )


def paid_apis_confirmed(session: Session) -> bool:
    """True only when the owner has switched "Use paid APIs" on."""
    return get_value(session, USE_PAID_APIS, False) is True


def set_paid_apis_confirmed(session: Session, confirmed: bool) -> None:
    set_value(session, USE_PAID_APIS, bool(confirmed))
