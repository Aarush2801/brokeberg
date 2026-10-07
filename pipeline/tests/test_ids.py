import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity
from brokeberg.db.seed import seed
from brokeberg.ids import bill, bioguide, fec, fips, fred
from brokeberg.ids.canonical import InvalidCanonicalIdError, Namespace, make, split
from brokeberg.ids.resolve import AliasIndex, AliasRecord, normalize, resolve
from brokeberg.taxonomy import EntityType

INDEX = AliasIndex.build(
    [
        AliasRecord(1, "bioguide:O000174", "Jon Ossoff",
                    ["Ossoff", "Ossoff (D-GA)", "@SenOssoff", "S8GA00180"]),
        AliasRecord(2, "bioguide:S001217", "Rick Scott", ["Scott", "Scott (R-FL)"]),
        AliasRecord(3, "bioguide:S001184", "Tim Scott", ["Scott", "Scott (R-SC)"]),
        AliasRecord(4, "bioguide:K000377", "Mark Kelly", ["Kelly", "Kelly (D-AZ)"]),
        AliasRecord(5, "bioguide:W000817", "Elizabeth Warren", ["Warren", "Warren (D-MA)"]),
    ]
)


# --- pure: normalization + alias index -------------------------------------------------------


def test_normalize_strips_honorifics_handles_and_tags() -> None:
    assert normalize("Sen. Rick Scott (R-FL)") == ["rick scott r fl", "rick scott"]
    assert normalize("@SenOssoff") == ["senossoff"]
    assert normalize("Angus S. King, Jr.") == ["angus s king"]
    assert normalize("Ben Ray Luján") == ["ben ray lujan"]


@pytest.mark.parametrize(
    "mention", ["Jon Ossoff", "Sen. Ossoff", "Senator Jon Ossoff", "@SenOssoff", "Ossoff (D-GA)",
                "S8GA00180"],
)
def test_exact_mentions_resolve(mention: str) -> None:
    r = INDEX.resolve(mention)
    assert (r.entity_id, r.canonical_id, r.method, r.confidence) == (
        1, "bioguide:O000174", "exact", 1.0
    )


def test_ambiguous_surname_is_unresolved_with_both_candidates() -> None:
    r = INDEX.resolve("Senator Scott")
    assert r.entity_id is None and r.method == "none"
    assert {c.entity_id for c in r.candidates} == {2, 3}


def test_party_state_tag_disambiguates() -> None:
    assert INDEX.resolve("Sen. Scott (R-SC)").canonical_id == "bioguide:S001184"


def test_fuzzy_typo_resolves_below_full_confidence() -> None:
    r = INDEX.resolve("Elizabeth Warrn")
    assert r.canonical_id == "bioguide:W000817" and r.method == "fuzzy"
    assert 0.9 <= r.confidence < 1.0


def test_surname_containment_does_not_link_a_different_person() -> None:
    assert INDEX.resolve("Megyn Kelly").entity_id is None


def test_unknown_name_returns_none_with_candidates() -> None:
    r = INDEX.resolve("John Smith")
    assert r.entity_id is None and r.canonical_id is None and r.confidence == 0.0
    assert 0 < len(r.candidates) <= 5


def test_id_like_aliases_are_exact_only() -> None:
    assert INDEX.resolve("S8GA00181").entity_id is None


def test_empty_mention() -> None:
    r = INDEX.resolve("  ")
    assert r.entity_id is None and r.candidates == []


# --- pure: registries ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["GA", "ga", "Georgia", " georgia ", "13"])
def test_fips_lookup(value: str) -> None:
    assert fips.to_fips(value) == "13"
    assert fips.canonical(value) == "fips:13"


def test_fips_unknown_and_coverage() -> None:
    assert fips.to_fips("Narnia") is None
    assert len(fips.STATES) == 51


def test_fred_normalize() -> None:
    assert fred.normalize(" cpiaucsl ") == "CPIAUCSL"
    assert fred.canonical("unrate") == "fred:UNRATE"
    assert fred.normalize("CPI-U") is None


def test_canonical_make_and_split() -> None:
    assert make(Namespace.BIOGUIDE, "S000148") == "bioguide:S000148"
    assert split("race:GA-SEN-2026") == (Namespace.RACE, "GA-SEN-2026")
    for bad in ("S000148", "bioguide:Schumer", "nope:1", "fips:6"):
        with pytest.raises(InvalidCanonicalIdError):
            split(bad)
    with pytest.raises(InvalidCanonicalIdError):
        make(Namespace.FEC, "12345")


# --- DB-backed: seeded reference data --------------------------------------------------------


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


@pytest.mark.parametrize(
    ("mention", "bioguide_id"),
    [
        ("Sen. Jon Ossoff", "O000174"),
        ("Chuck Schumer", "S000148"),
        ("Senator Lisa Murkowski", "M001153"),
        ("Angus King", "K000383"),
        ("Scott (R-SC)", "S001184"),
    ],
)
def test_known_senators_resolve(seeded: Session, mention: str, bioguide_id: str) -> None:
    assert bioguide.resolve_member(seeded, mention).canonical_id == f"bioguide:{bioguide_id}"


def test_unknown_member_is_none_with_candidates(seeded: Session) -> None:
    r = bioguide.resolve_member(seeded, "Senator Scott")
    assert r.entity_id is None
    assert {c.canonical_id for c in r.candidates} == {"bioguide:S001217", "bioguide:S001184"}


def test_resolve_never_mints_entities(seeded: Session) -> None:
    before = seeded.scalar(select(func.count()).select_from(Entity))
    assert resolve(seeded, "Senator Totally Madeup", EntityType.POLITICIAN).entity_id is None
    assert seeded.scalar(select(func.count()).select_from(Entity)) == before


def test_lookup_by_ids(seeded: Session) -> None:
    schumer = bioguide.by_bioguide(seeded, "s000148")
    assert schumer is not None and schumer.canonical_id == "bioguide:S000148"
    fec_id = schumer.meta["fec_ids"][0]
    holder = fec.by_fec_id(seeded, fec_id)
    assert holder is not None and holder.id == schumer.id
    assert fec.resolve_candidate(seeded, fec_id).entity_id == schumer.id


def test_fred_registration(seeded: Session) -> None:
    assert fred.is_registered(seeded, "cpiaucsl")
    assert not fred.is_registered(seeded, "NOTASERIES")


def test_bill_ids() -> None:
    assert bill.canonical(119, "S", "877") == "bill:119-s-877"
    assert bill.canonical(119, "H.R.", 5) == "bill:119-hr-5"
    assert bill.canonical(119, "XX", 5) is None
    assert bill.from_voteview(119, "HR9340") == "bill:119-hr-9340"
    assert bill.from_voteview(119, "SJRES12") == "bill:119-sjres-12"
    assert bill.from_voteview(119, "PN1129") is None  # a nomination, not a bill
    assert bill.from_voteview(119, None) is None
    assert bill.label("bill:119-hr-9340") == "H.R. 9340 (119th)"
    assert split("bill:119-s-877") == (Namespace.BILL, "119-s-877")
