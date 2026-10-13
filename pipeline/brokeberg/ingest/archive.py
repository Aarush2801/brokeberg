"""Raw-item archive to S3: `s3://$S3_RAW_BUCKET/{source}/{yyyy}/{mm}/{dd}/{content_hash}.json`.

Off when S3_RAW_BUCKET is unset (dev). The key is the content hash, so re-archiving an item
overwrites the same object: a retried ingest never duplicates anything.
"""

from datetime import datetime
from functools import lru_cache
from typing import Any

from brokeberg.config import get_settings


@lru_cache
def get_client() -> Any:
    import boto3

    return boto3.client("s3", region_name=get_settings().require("aws_region"))


def archive_key(source: str, content_hash: str, seen_at: datetime) -> str:
    return f"{source}/{seen_at:%Y/%m/%d}/{content_hash}.json"


def archive(row: dict[str, Any], body: str, seen_at: datetime) -> str | None:
    """Store one raw item's canonical JSON; returns the key, or None when archiving is off."""
    bucket = get_settings().s3_raw_bucket
    if not bucket:
        return None
    key = archive_key(row["source"], row["content_hash"], seen_at)
    get_client().put_object(
        Bucket=bucket, Key=key, Body=body.encode("utf-8"), ContentType="application/json"
    )
    return key
