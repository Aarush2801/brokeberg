import importlib
import pkgutil

import brokeberg
from brokeberg import taxonomy
from brokeberg.config import get_settings
from brokeberg.embed import embed


def test_every_module_imports() -> None:
    names = [m.name for m in pkgutil.walk_packages(brokeberg.__path__, prefix="brokeberg.")]
    assert "brokeberg.config" in names
    for name in names:
        importlib.import_module(name)


def test_embed_dim() -> None:
    vectors = embed(["x"])
    assert len(vectors) == 1
    assert len(vectors[0]) == get_settings().embed_dim == 1024


def test_embed_empty() -> None:
    assert embed([]) == []


def test_taxonomy_enums_non_empty() -> None:
    for enum in taxonomy.ALL_ENUMS:
        assert len(enum) > 0, enum.__name__


def test_no_causal_edges() -> None:
    assert "CAUSES" not in {e.value for e in taxonomy.EdgeType}


def test_every_source_type_has_trust_tier() -> None:
    assert set(taxonomy.SOURCE_TRUST) == set(taxonomy.SourceType)
