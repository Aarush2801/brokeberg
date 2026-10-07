"""Canonical-ID resolvers. Mentions link to existing IDs here; nothing in this package mints one."""

from brokeberg.ids.canonical import InvalidCanonicalIdError, Namespace, make, split
from brokeberg.ids.resolve import Candidate, ResolveResult, resolve

__all__ = [
    "Candidate",
    "InvalidCanonicalIdError",
    "Namespace",
    "ResolveResult",
    "make",
    "resolve",
    "split",
]
