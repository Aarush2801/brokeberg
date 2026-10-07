import os

# Tests never touch the network: the embedding model must come from the local HF cache.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["EMBED_PROVIDER"] = "local"
os.environ["LLM_PROVIDER"] = "anthropic"

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402

from brokeberg.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
