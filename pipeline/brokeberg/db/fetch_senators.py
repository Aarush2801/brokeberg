"""One-off: snapshot current senators from unitedstates/congress-legislators into seed_data.

Run manually (`make fetch-senators`) when the Senate changes; commit the JSON it writes.
Seeding and tests read only the committed snapshot and never touch the network.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

BASE = "https://unitedstates.github.io/congress-legislators"
LEGISLATORS_URL = f"{BASE}/legislators-current.json"
SOCIAL_URL = f"{BASE}/legislators-social-media.json"
OUT = Path(__file__).parent / "seed_data" / "senators.json"

PARTY_ABBREV = {"Democrat": "D", "Republican": "R", "Independent": "I"}


def _senator(rec: dict[str, Any], social: dict[str, dict[str, Any]]) -> dict[str, Any]:
    term = rec["terms"][-1]
    name = rec["name"]
    bioguide = rec["id"]["bioguide"]
    return {
        "bioguide": bioguide,
        "lis": rec["id"].get("lis"),
        "fec": rec["id"].get("fec", []),
        "ballotpedia": rec["id"].get("ballotpedia"),
        "first": name["first"],
        "middle": name.get("middle"),
        "last": name["last"],
        "suffix": name.get("suffix"),
        "nickname": name.get("nickname"),
        "official_full": name.get("official_full") or f"{name['first']} {name['last']}",
        "state": term["state"],
        "party": PARTY_ABBREV.get(term["party"], term["party"]),
        "senate_class": term.get("class"),
        "term_end": term["end"],
        "twitter": social.get(bioguide, {}).get("twitter"),
    }


def fetch() -> dict[str, Any]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        legislators = client.get(LEGISLATORS_URL).raise_for_status().json()
        social_rows = client.get(SOCIAL_URL).raise_for_status().json()
    social = {row["id"]["bioguide"]: row.get("social", {}) for row in social_rows}
    senators = [_senator(r, social) for r in legislators if r["terms"][-1]["type"] == "sen"]
    senators.sort(key=lambda s: (s["state"], s["last"]))
    return {
        "source_urls": [LEGISLATORS_URL, SOCIAL_URL],
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "senators": senators,
    }


def main() -> None:
    snapshot = fetch()
    OUT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(snapshot['senators'])} senators to {OUT}")


if __name__ == "__main__":
    main()
