from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Race, RawItem
from brokeberg.db.seed import seed
from brokeberg.ingest.replay import REPLAY_SINCE, cassette
from brokeberg.ingest.sources.fec import FecLoader


def test_fec_fills_races_and_maps_incumbent_to_bioguide(db_session: Session) -> None:
    seed(db_session)
    with cassette("fec"):
        first = FecLoader().load(db_session, REPLAY_SINCE)
    assert first.inserted > 0 and first.note == "races=10"

    ga = db_session.get(Race, "GA-SEN-2026")
    assert ga is not None
    assert "S8GA00180" in ga.fec_candidate_ids  # Ossoff
    assert ga.meta["finance"]["source_url"] == "https://www.fec.gov/data/elections/senate/GA/2026/"
    assert ga.meta["incumbent_bioguide"] == "O000174"  # seed meta survives the merge

    ossoff = db_session.scalars(
        select(RawItem).where(
            RawItem.source == "fec", RawItem.payload_jsonb["raw"]["candidate_id"].astext
            == "S8GA00180",
        )
    ).one()
    # One node per person: the incumbent's FEC ID resolves to the bioguide node.
    assert ossoff.payload_jsonb["_resolved"] == ["bioguide:O000174", "race:GA-SEN-2026"]

    with cassette("fec"):
        again = FecLoader().load(db_session, REPLAY_SINCE)
    assert (again.inserted, again.skipped) == (0, first.fetched)
