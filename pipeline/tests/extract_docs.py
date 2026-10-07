"""Fixture documents for the extraction tests (shapes mirror real connector payloads)."""

from datetime import UTC, datetime

from brokeberg.extract.doc import SourceDoc
from brokeberg.taxonomy import SourceType

WHEN = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)

X_TEXT = (
    "Tariffs on Canadian lumber are a tax on Alaska families building homes. "
    "I will vote against extending them. Sen. Chuck Schumer should bring the repeal to the floor."
)


def x_post(text: str = X_TEXT) -> SourceDoc:
    return SourceDoc.build(
        source="x",
        source_type=SourceType.SOCIAL_POST,
        url="https://x.com/LisaMurkowski/status/1",
        body=text,
        event_time=WHEN,
        raw={
            "author": {"handle": "LisaMurkowski", "user_id": "18061669", "bioguide": "M001153"},
            "tweet": {"id": "1", "text": text},
        },
        resolved=["bioguide:M001153"],
    )


def off_topic() -> SourceDoc:
    return SourceDoc.build(
        source="x",
        source_type=SourceType.NEWS,
        url="https://x.com/FT/status/2",
        body="Arsenal beat Chelsea 3-1 in a thrilling north London derby on Saturday.",
        event_time=WHEN,
        raw={"author": {"handle": "FT", "user_id": "1", "kind": "media"}, "tweet": {"id": "2"}},
        resolved=[],
    )


def bill() -> SourceDoc:
    return SourceDoc.build(
        source="congress",
        source_type=SourceType.GOVERNMENT_PRIMARY,
        url="https://www.congress.gov/bill/119th-congress/senate-bill/877",
        body=(
            "S. 877 (119th Congress): Lower Grocery Prices Act\n"
            "Latest action (2026-09-30): Read twice and referred to the Committee on Finance."
        ),
        event_time=WHEN,
        raw={
            "kind": "bill",
            "congress": 119,
            "type": "S",
            "number": "877",
            "title": "Lower Grocery Prices Act",
            "sponsors": [
                {"bioguideId": "O000174", "fullName": "Sen. Ossoff, Jon [D-GA]", "party": "D",
                 "state": "GA"}
            ],
        },
        resolved=["bioguide:O000174"],
    )


def vote() -> SourceDoc:
    return SourceDoc.build(
        source="senate_votes",
        source_type=SourceType.GOVERNMENT_PRIMARY,
        url="https://voteview.com/rollcall/RS1190500",
        body=(
            "Senate roll call vote 500 (2026-09-30): On Cloture on the Motion to Proceed - "
            "H.R. 9340\nResult: Cloture Motion Agreed to (61-37)"
        ),
        event_time=WHEN,
        raw={
            "kind": "vote",
            "congress": 119,
            "clerk_rollnumber": 500,
            "bill_number": "HR9340",
            "members": [
                {"bioguide": "M001153", "vote": "Yea"},
                {"bioguide": "O000174", "vote": "Nay"},
                {"bioguide": "S000148", "vote": "Not Voting"},
            ],
        },
        resolved=["bioguide:M001153", "bioguide:O000174", "bioguide:S000148"],
    )
