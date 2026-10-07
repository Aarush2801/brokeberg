"""Policy_Bill nodes, minted only from congress.gov / Voteview structured identifiers.

This is the one place extraction creates an entity, and it is deterministic: the ID comes from the
payload's `type`/`number` (or Voteview `bill_number`), never from LLM text (golden rule 1).
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity
from brokeberg.extract.doc import SourceDoc
from brokeberg.ids import bill
from brokeberg.ids.resolve import clear_cache
from brokeberg.taxonomy import EntityType


def bill_id_for(doc: SourceDoc) -> str | None:
    """The canonical bill ID this item is about, if its payload names one."""
    raw = doc.raw
    if doc.kind == "bill":
        return bill.canonical(int(raw["congress"]), str(raw["type"]), str(raw["number"]))
    if doc.kind == "vote":
        return bill.from_voteview(int(raw["congress"]), raw.get("bill_number"))
    return None


def ensure_bill(session: Session, doc: SourceDoc) -> Entity | None:
    cid = bill_id_for(doc)
    if cid is None:
        return None
    short = bill.label(cid)
    title = doc.raw.get("title") if doc.kind == "bill" else None
    name = f"{short}: {title}" if title else short
    inserted = session.execute(
        insert(Entity)
        .values(
            entity_type=EntityType.POLICY_BILL,
            canonical_id=cid,
            name=name,
            aliases=[short, short.split(" (")[0]],
            meta={"congress": doc.raw.get("congress"), "url": doc.url},
        )
        .on_conflict_do_nothing(index_elements=[Entity.canonical_id])
        .returning(Entity.id)
    ).scalar_one_or_none()
    if inserted is not None:
        clear_cache()  # so a later mention of this bill ("S. 877") can resolve to it
    entity = bill.by_bill_id(session, cid)
    if entity is not None and title and entity.name == short:
        entity.name = name  # first seen via a vote (no title); the bill item supplies it
    return entity
