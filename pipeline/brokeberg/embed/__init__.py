"""Embedding interface: `embed()` routed by EMBED_PROVIDER.

Dev and prod both produce EMBED_DIM (1024) normalized vectors so they share the pgvector column.
"""

import json
from functools import lru_cache
from typing import Any

from brokeberg.config import get_settings

__all__ = ["EmbeddingDimError", "embed"]


class EmbeddingDimError(RuntimeError):
    """A provider returned vectors of the wrong dimension."""


@lru_cache
def _local_model() -> Any:
    # Imported lazily: sentence-transformers pulls in torch, which is slow to import.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embed_model)


@lru_cache
def _bedrock_client() -> Any:
    import boto3

    return boto3.client("bedrock-runtime", region_name=get_settings().require("aws_region"))


def _embed_local(texts: list[str]) -> list[list[float]]:
    vectors = _local_model().encode(texts, normalize_embeddings=True)
    return [[float(x) for x in v] for v in vectors]


def _embed_bedrock(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    out: list[list[float]] = []
    for text in texts:  # Titan v2 embeds one input per call.
        body = {"inputText": text, "dimensions": settings.embed_dim, "normalize": True}
        resp = _bedrock_client().invoke_model(modelId=settings.embed_model, body=json.dumps(body))
        out.append(json.loads(resp["body"].read())["embedding"])
    return out


def embed(texts: list[str]) -> list[list[float]]:
    """Embed each text; every returned vector has length EMBED_DIM."""
    if not texts:
        return []
    settings = get_settings()
    vectors = _embed_local(texts) if settings.embed_provider == "local" else _embed_bedrock(texts)
    for v in vectors:
        if len(v) != settings.embed_dim:
            raise EmbeddingDimError(
                f"{settings.embed_model} returned dim {len(v)}, expected {settings.embed_dim}"
            )
    return vectors
