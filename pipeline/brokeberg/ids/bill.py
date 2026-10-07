"""Bills -> `bill:<congress>-<type>-<number>` (congress.gov's own identifiers).

Bill IDs come only from structured source fields (congress.gov `type`/`number`, Voteview
`bill_number`), never from LLM text. Nominations (`PN1129`) are not bills and return None.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity
from brokeberg.ids.canonical import Namespace, is_valid, make

# Longest prefixes first, so 'SJRES' is not read as 'S' + junk.
_TYPES = ("SCONRES", "HCONRES", "SJRES", "HJRES", "SRES", "HRES", "HR", "S")
_VOTEVIEW = re.compile(rf"^({'|'.join(_TYPES)})(\d{{1,5}})$")


def canonical(congress: int, bill_type: str, number: str | int) -> str | None:
    """(119, 'S', '877') -> 'bill:119-s-877'; malformed -> None."""
    raw = f"{congress}-{bill_type.strip().lower().replace('.', '')}-{str(number).strip()}"
    return make(Namespace.BILL, raw) if is_valid(Namespace.BILL, raw) else None


def from_voteview(congress: int, bill_number: str | None) -> str | None:
    """(119, 'HR9340') -> 'bill:119-hr-9340'; 'PN1129' (a nomination) or None -> None."""
    m = _VOTEVIEW.fullmatch((bill_number or "").strip().upper())
    return canonical(congress, m.group(1), m.group(2)) if m else None


def label(canonical_id: str) -> str:
    """'bill:119-hr-9340' -> 'H.R. 9340 (119th)'."""
    congress, bill_type, number = canonical_id.partition(":")[2].split("-")
    pretty = {"s": "S.", "hr": "H.R."}.get(bill_type, bill_type.upper())
    return f"{pretty} {number} ({congress}th)"


def by_bill_id(session: Session, canonical_id: str) -> Entity | None:
    return session.scalar(select(Entity).where(Entity.canonical_id == canonical_id))
