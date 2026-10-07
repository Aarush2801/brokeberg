"""Senate bills and roll-call votes -> raw_items (government_primary).

- Bills: Congress.gov v3 API.
- Votes: Voteview (UCLA). Congress.gov has no Senate vote endpoint and senate.gov's CDN refuses
  non-browser clients (robots.txt included), so we read Voteview's mirror of the Senate clerk's
  record. It lags the clerk by days. The clerk's own URL is kept in the payload for verification.

Members arrive with bioguide IDs in both, so mapping is an exact registry lookup (never fuzzy).

TODO: member statements (Congressional Record) are deferred; X covers official statements for now.
"""

import csv
import io
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.ids import bioguide
from brokeberg.ingest import http
from brokeberg.ingest.base import RawRecord
from brokeberg.taxonomy import SourceType

API = "https://api.congress.gov/v3"
MAX_BILLS = 20  # most recently updated first; each needs a detail call for the sponsor

VOTEVIEW_ROLLCALLS = "https://voteview.com/static/data/out/rollcalls/S{congress}_rollcalls.csv"
VOTEVIEW_ROLLCALL_API = "https://voteview.com/api/download"
VOTEVIEW_PAGE = "https://voteview.com/rollcall/{}"
CLERK_VOTE_URL = (
    "https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/"
    "vote_{congress}_{session}_{number:05d}.htm"
)
MAX_VOTES = 20  # newest first; each needs one per-rollcall call for member votes


def congress_for(year: int) -> int:
    """2025/2026 -> 119."""
    return (year - 1789) // 2 + 1


def public_bill_url(congress: int, number: str) -> str:
    return f"https://www.congress.gov/bill/{congress}th-congress/senate-bill/{number}"


def bill_record(session: Session, summary: dict[str, Any], detail: dict[str, Any]) -> RawRecord:
    congress = int(summary["congress"])
    action = detail.get("latestAction") or summary.get("latestAction") or {}
    entity_ids: list[str] = []
    unresolved: list[str] = []
    for sponsor in detail.get("sponsors", []):
        entity = bioguide.by_bioguide(session, sponsor.get("bioguideId", ""))
        if entity is not None:
            entity_ids.append(entity.canonical_id)
        else:
            unresolved.append(sponsor.get("fullName") or sponsor.get("bioguideId", ""))
    title = detail.get("title") or summary["title"]
    text = f"S. {summary['number']} ({congress}th Congress): {title}"
    if action:
        text += f"\nLatest action ({action.get('actionDate')}): {action.get('text')}"
    event_time = (
        datetime.fromisoformat(action["actionDate"]).replace(tzinfo=UTC)
        if action.get("actionDate")
        else None
    )
    return RawRecord(
        url=public_bill_url(congress, summary["number"]),
        text=text,
        event_time=event_time,
        raw_payload={
            "kind": "bill",
            "congress": congress,
            "type": summary["type"],
            "number": summary["number"],
            "title": title,
            "introducedDate": detail.get("introducedDate"),
            "latestAction": action,
            "policyArea": (detail.get("policyArea") or {}).get("name"),
            "sponsors": [
                {k: s.get(k) for k in ("bioguideId", "fullName", "party", "state")}
                for s in detail.get("sponsors", [])
            ],
        },
        entity_ids=entity_ids,
        unresolved=unresolved,
    )


class CongressConnector:
    source = "congress"
    source_type = SourceType.GOVERNMENT_PRIMARY

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or http.make_client()

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        key = get_settings().require("congress_api_key")
        resp = http.get(
            self.client, f"{API}/{path}", params={**params, "format": "json", "api_key": key}
        )
        data: dict[str, Any] = resp.json()
        return data

    def fetch(self, session: Session, since: datetime) -> Iterator[RawRecord]:
        congress = congress_for(since.year)
        listing = self._get(
            f"bill/{congress}/s",
            fromDateTime=since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            sort="updateDate desc",
            limit=MAX_BILLS,
        )
        for summary in listing.get("bills", []):
            detail = self._get(f"bill/{congress}/s/{summary['number']}")["bill"]
            yield bill_record(session, summary, detail)


def vote_record(session: Session, rollcall: dict[str, Any]) -> RawRecord:
    entity_ids: list[str] = []
    unresolved: list[str] = []
    members = []
    for v in rollcall.get("votes", []):
        entity = bioguide.by_bioguide(session, v.get("bioguide_id") or "")
        if entity is not None:
            entity_ids.append(entity.canonical_id)
        else:
            unresolved.append(v.get("member_full") or v.get("name") or "")
        members.append({"bioguide": v.get("bioguide_id"), "vote": v.get("cast_str")})
    congress = int(rollcall["congress"])
    year = int(rollcall["date"][:4])
    session_no = 1 if year % 2 else 2
    clerk_no = int(rollcall["clerk_rollnumber"])
    text = (
        f"Senate roll call vote {clerk_no} ({rollcall['date']}): "
        f"{rollcall.get('vote_question_text')}"
        f" - {rollcall.get('vote_document_text') or rollcall.get('description') or ''}\n"
        f"Result: {rollcall.get('vote_result')} ({rollcall.get('yea_count')}-"
        f"{rollcall.get('nay_count')})"
    )
    return RawRecord(
        url=VOTEVIEW_PAGE.format(rollcall["id"]),
        text=text,
        event_time=datetime.fromisoformat(rollcall["date"]).replace(tzinfo=UTC),
        raw_payload={
            "kind": "vote",
            "voteview_id": rollcall["id"],
            "official_url": CLERK_VOTE_URL.format(
                congress=congress, session=session_no, number=clerk_no
            ),
            "congress": congress,
            "session": session_no,
            "clerk_rollnumber": clerk_no,
            "date": rollcall["date"],
            "question": rollcall.get("vote_question_text"),
            "document": rollcall.get("vote_document_text"),
            "bill_number": rollcall.get("bill_number"),
            "result": rollcall.get("vote_result"),
            "yea_count": rollcall.get("yea_count"),
            "nay_count": rollcall.get("nay_count"),
            "members": sorted(members, key=lambda m: m["bioguide"] or ""),
        },
        entity_ids=entity_ids,
        unresolved=unresolved,
    )


class SenateVotesConnector:
    source = "senate_votes"
    source_type = SourceType.GOVERNMENT_PRIMARY

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or http.make_client()

    def fetch(self, session: Session, since: datetime) -> Iterator[RawRecord]:
        congress = congress_for(since.year)
        listing = http.get(self.client, VOTEVIEW_ROLLCALLS.format(congress=congress)).text
        rows = [
            r for r in csv.DictReader(io.StringIO(listing)) if r["date"] >= since.date().isoformat()
        ]
        rows.sort(key=lambda r: int(r["rollnumber"]), reverse=True)
        for row in rows[:MAX_VOTES]:
            rollcall_id = f"RS{congress}{int(row['rollnumber']):04d}"
            data = http.get(
                self.client, VOTEVIEW_ROLLCALL_API, params={"rollcall_id": rollcall_id}
            ).json()
            for rollcall in data.get("rollcalls", []):
                yield vote_record(session, rollcall)
