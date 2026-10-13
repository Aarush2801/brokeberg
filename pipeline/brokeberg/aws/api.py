"""Lambda entry point for the query API (behind a Function URL): the unchanged FastAPI app via
Mangum. Config is loaded from Secrets Manager on the first invocation, before the app's first
settings read (not at import, so importing this module never calls AWS)."""

from typing import Any

from brokeberg.aws import secrets

_mangum: Any = None


def handler(event: dict[str, Any], context: Any) -> Any:
    global _mangum
    if _mangum is None:
        secrets.load()
        from mangum import Mangum

        from brokeberg.api.app import app

        _mangum = Mangum(app, lifespan="off")
    return _mangum(event, context)
