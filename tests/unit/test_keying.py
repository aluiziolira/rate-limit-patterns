"""Unit tests for Redis key helpers."""

from rate_limit_patterns.backend.keying import build_redis_cluster_key, extract_hash_tag


class TestRedisKeying:
    """Tests for keying helpers."""

    def test_build_cluster_key_is_deterministic(self) -> None:
        key = build_redis_cluster_key(tag="user:123", prefix="rate:api", suffix="window")
        assert key == "rate:api:{user:123}:window"
        assert build_redis_cluster_key(tag="user:123", prefix="rate:api", suffix="window") == key

    def test_seq_key_shares_same_hash_tag(self) -> None:
        base_key = build_redis_cluster_key(tag="tenant-42", prefix="rate", suffix="window")
        seq_key = f"{base_key}:seq"
        assert extract_hash_tag(base_key) == extract_hash_tag(seq_key) == "tenant-42"
