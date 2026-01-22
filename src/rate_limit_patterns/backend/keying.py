"""Helpers for Redis key construction and cluster hashing."""

from __future__ import annotations

import re

HASH_TAG_PATTERN = re.compile(r"\{[^}]+\}")


def has_hash_tag(key: str) -> bool:
    """Return True if the key contains a Redis Cluster hash tag."""
    return HASH_TAG_PATTERN.search(key) is not None


def extract_hash_tag(key: str) -> str | None:
    """Extract the hash tag from a key, if present."""
    match = HASH_TAG_PATTERN.search(key)
    if match is None:
        return None
    return match.group(0)[1:-1]


def build_redis_cluster_key(*, tag: str, suffix: str, prefix: str = "") -> str:
    """Build a Redis Cluster-compatible key using a hash tag.

    Args:
        tag: Hash tag value to keep related keys in the same slot.
        suffix: Logical key suffix (e.g., "window" or "user:123").
        prefix: Optional namespace prefix (e.g., "rate" or "rate:api").
    """
    normalized_prefix = prefix.rstrip(":")
    normalized_suffix = suffix.lstrip(":")
    if normalized_prefix:
        return f"{normalized_prefix}:{{{tag}}}:{normalized_suffix}"
    return f"{{{tag}}}:{normalized_suffix}"
