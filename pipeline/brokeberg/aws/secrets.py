"""Prod config from Secrets Manager -> `os.environ`, before the first `get_settings()`.

Two secrets, both created by the BrokebergData stack:
- `brokeberg/prod/app`: a flat JSON object of Settings env vars (LLM_PROVIDER, LLM_MODEL, API
  keys, ...). Filled by `infra/scripts/push_secrets.py`.
- `brokeberg/prod/db`: the RDS-generated Aurora credentials; DATABASE_URL is built from it.

Variables already set on the process (e.g. a per-function X_MAX_RESULTS) win over the secret.

`python -m brokeberg.aws.secrets` prints `export` lines for a local shell
(`infra/scripts/prod_env.sh`), so `make migrate` / `make eval` can run against prod.
"""

import json
import os
import shlex
from typing import Any

from sqlalchemy import URL

from brokeberg.config import get_settings

APP_SECRET_ID = "brokeberg/prod/app"
DB_SECRET_ID = "brokeberg/prod/db"
# Aurora at 0 ACU takes ~15-30s to resume; the first connection waits for it.
CONNECT_TIMEOUT_S = 60


def _get(client: Any, secret_id: str) -> dict[str, Any]:
    return dict(json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"]))


def database_url(db: dict[str, Any]) -> str:
    return URL.create(
        "postgresql+psycopg",
        username=db["username"],
        password=db["password"],
        host=db["host"],
        port=int(db.get("port", 5432)),
        database=db.get("dbname", "brokeberg"),
        query={"sslmode": "require", "connect_timeout": str(CONNECT_TIMEOUT_S)},
    ).render_as_string(hide_password=False)


def resolve(client: Any) -> dict[str, str]:
    """The env vars prod runs with: the app secret plus DATABASE_URL."""
    env = {k.upper(): str(v) for k, v in _get(client, APP_SECRET_ID).items()}
    env["DATABASE_URL"] = database_url(_get(client, DB_SECRET_ID))
    return env


def load(client: Any | None = None) -> None:
    if client is None:
        import boto3

        client = boto3.client("secretsmanager")
    for key, value in resolve(client).items():
        os.environ.setdefault(key, value)
    get_settings.cache_clear()


def main() -> None:
    import boto3

    region = os.environ.get("AWS_REGION") or get_settings().aws_region
    for key, value in resolve(boto3.client("secretsmanager", region_name=region)).items():
        print(f"export {key}={shlex.quote(value)}")


if __name__ == "__main__":
    main()
