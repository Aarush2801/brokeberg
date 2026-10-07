"""Recent posts from the curated account list (`ingest/x_accounts.yaml`) -> raw_items (social_post).

Read-only, `/2/users/:id/tweets`. X bills per post read, so every pull logs and prints its read
count; the budget is ~100-200 reads/day (20 live accounts x `max_results`=10 <= 200).
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.ids import bioguide
from brokeberg.ingest import http
from brokeberg.ingest.base import RawRecord
from brokeberg.taxonomy import SourceType

log = logging.getLogger(__name__)

ACCOUNTS_FILE = Path(__file__).resolve().parents[1] / "x_accounts.yaml"
TWEETS_URL = "https://api.x.com/2/users/{}/tweets"
MAX_ACCOUNTS = 20
DEFAULT_MAX_RESULTS = 10  # X minimum is 5, maximum 100
# The cassette was recorded with these limits; replay must request exactly the same URLs.
RECORDED_ACCOUNTS = 2
RECORDED_MAX_RESULTS = 5


class Account(BaseModel):
    handle: str | None
    user_id: str | None
    # member: a senator, linked to their bioguide node. media: a news outlet's account; there is
    # no canonical-ID registry for outlets yet, so its posts link to no entity.
    kind: Literal["member", "media"] = "member"
    bioguide: str | None = None

    @model_validator(mode="after")
    def _member_has_bioguide(self) -> "Account":
        if self.kind == "member" and not self.bioguide:
            raise ValueError(f"member account {self.handle!r} needs a bioguide ID")
        return self


def load_accounts(path: Path = ACCOUNTS_FILE) -> list[Account]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    accounts = [Account.model_validate(a) for a in data["accounts"]]
    if len(accounts) > MAX_ACCOUNTS:
        raise ValueError(f"{path.name} lists {len(accounts)} accounts; the cap is {MAX_ACCOUNTS}")
    return accounts


def post_record(session: Session, account: Account, tweet: dict[str, Any]) -> RawRecord:
    entity = bioguide.by_bioguide(session, account.bioguide) if account.bioguide else None
    # The author is a source, not a mention: only an unresolvable *member* goes to review.
    unresolved = [f"@{account.handle}"] if account.kind == "member" and entity is None else []
    created = tweet.get("created_at")
    return RawRecord(
        url=f"https://x.com/{account.handle or 'i'}/status/{tweet['id']}",
        text=tweet["text"],
        event_time=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
        # exclude_defaults keeps member payloads (and so their content hashes) as before `kind`.
        raw_payload={"author": account.model_dump(exclude_defaults=True), "tweet": tweet},
        entity_ids=[entity.canonical_id] if entity else [],
        unresolved=unresolved,
    )


class XConnector:
    source = "x"
    source_type = SourceType.SOCIAL_POST

    def __init__(
        self,
        client: httpx.Client | None = None,
        accounts: list[Account] | None = None,
        max_accounts: int | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> None:
        self.client = client or http.make_client()
        self.accounts = accounts if accounts is not None else load_accounts()
        self.max_accounts = max_accounts
        self.max_results = max_results
        self.reads = 0

    def fetch(self, session: Session, since: datetime) -> Iterator[RawRecord]:
        token = get_settings().require("x_bearer_token")
        live = [a for a in self.accounts if a.user_id]
        for a in self.accounts:
            if not a.user_id:
                log.info("x: skipping %s (%s): no user_id", a.handle, a.bioguide)
        if self.max_accounts is not None:
            live = live[: self.max_accounts]
        self.reads = 0
        for account in live:
            resp = http.get(
                self.client,
                TWEETS_URL.format(account.user_id),
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "max_results": self.max_results,
                    "start_time": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exclude": "retweets",
                    "tweet.fields": "created_at,public_metrics,referenced_tweets,lang",
                },
            )
            tweets = resp.json().get("data", [])
            self.reads += len(tweets)
            log.info("x: @%s read %d posts", account.handle, len(tweets))
            for tweet in tweets:
                yield post_record(session, account, tweet)
        print(f"x: read count this pull = {self.reads} posts across {len(live)} accounts")
