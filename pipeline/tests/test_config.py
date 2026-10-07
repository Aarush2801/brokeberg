import pytest

from brokeberg.config import MissingConfigError, Settings


def test_settings_load_without_keys() -> None:
    s = Settings(_env_file=None, fred_api_key=None)  # type: ignore[call-arg]
    assert s.embed_dim == 1024


def test_require_raises_on_missing_key() -> None:
    s = Settings(_env_file=None, fred_api_key=None)  # type: ignore[call-arg]
    with pytest.raises(MissingConfigError, match="FRED_API_KEY"):
        s.require("fred_api_key")


def test_require_returns_value() -> None:
    s = Settings(_env_file=None, fred_api_key="abc")  # type: ignore[call-arg]
    assert s.require("fred_api_key") == "abc"
