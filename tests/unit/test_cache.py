"""Tests for core/cache.py — Asset Fingerprinting."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mindmargin.core.cache import AssetCache, hash_file, hash_text, hash_dict


@pytest.fixture
def mock_base(tmp_path):
    with patch("mindmargin.core.cache._safe_base", return_value=tmp_path):
        yield tmp_path


def test_hash_text():
    h1 = hash_text("hello world")
    h2 = hash_text("hello world")
    h3 = hash_text("hello world!")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex


def test_hash_dict():
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 2, "a": 1}  # same content, different order
    d3 = {"a": 1, "b": 3}
    assert hash_dict(d1) == hash_dict(d2)
    assert hash_dict(d1) != hash_dict(d3)


def test_hash_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    h1 = hash_file(f)
    h2 = hash_file(f)
    assert h1 == h2

    f.write_text("hello world!")
    h3 = hash_file(f)
    assert h1 != h3


def test_cache_hit_miss(mock_base):
    cache = AssetCache("pipe_001")
    assert cache.check("key1", "abc123") is False
    assert cache._misses == 1

    cache.update("key1", "abc123")
    assert cache.check("key1", "abc123") is True
    assert cache._hits == 1

    assert cache.check("key1", "different") is False


def test_cache_persistence(mock_base):
    cache1 = AssetCache("pipe_persist")
    cache1.update("render_hash", "sha256abc")

    cache2 = AssetCache("pipe_persist")
    assert cache2.check("render_hash", "sha256abc") is True


def test_cache_invalidate(mock_base):
    cache = AssetCache("pipe_inv")
    cache.update("some_key", "hash123")
    assert cache.check("some_key", "hash123") is True

    cache.invalidate("some_key")
    assert cache.check("some_key", "hash123") is False


def test_cache_invalidate_all(mock_base):
    cache = AssetCache("pipe_all")
    cache.update("a", "1")
    cache.update("b", "2")
    cache.invalidate_all()
    assert cache.stats["hits"] == 0
    assert cache.stats["misses"] == 0


def test_cache_stats(mock_base):
    cache = AssetCache("pipe_stats")
    cache.check("k", "v1")
    cache.check("k", "v1")
    cache.update("k", "v1")
    assert cache.check("k", "v1") is True

    stats = cache.stats
    assert stats["hits"] == 1
    assert stats["misses"] == 2
    assert stats["ratio"] == pytest.approx(1/3, rel=0.01)


def test_cache_file_methods(mock_base, tmp_path):
    cache = AssetCache("pipe_file")
    f = tmp_path / "asset.txt"
    f.write_text("content")

    assert cache.check_file("asset", f) is False
    cache.update_file("asset", f)
    assert cache.check_file("asset", f) is True

    f.write_text("modified")
    assert cache.check_file("asset", f) is False


def test_cache_text_methods(mock_base):
    cache = AssetCache("pipe_text")
    assert cache.check_text("script", "hello") is False
    cache.update_text("script", "hello")
    assert cache.check_text("script", "hello") is True
    assert cache.check_text("script", "world") is False


def test_cache_version_mismatch(mock_base):
    cache = AssetCache("pipe_ver")
    cache.update("some_key", "hash")

    # Directly write a file with old version to test invalidation
    import json
    raw = cache._path.read_text(encoding="utf-8")
    data = json.loads(raw)
    data["_version"] = "0"
    cache._path.write_text(json.dumps(data), encoding="utf-8")

    cache2 = AssetCache("pipe_ver")
    assert cache2.check("some_key", "hash") is False  # cleared due to version mismatch


def test_cache_fingerprints_property(mock_base):
    cache = AssetCache("pipe_fp")
    cache.update("a", "hash_a")
    cache.update("b", "hash_b")
    fps = cache.fingerprints
    assert fps["a"] == "hash_a"
    assert fps["b"] == "hash_b"
    assert "_version" not in fps


class TestCacheEdgeCases:
    def test_check_file_not_exists(self, mock_base, tmp_path):
        cache = AssetCache("pipe_miss")
        result = cache.check_file("asset", tmp_path / "nonexistent.txt")
        assert result is False
        assert cache._misses == 1

    def test_load_corrupt_json(self, mock_base):
        cache = AssetCache("pipe_corrupt_load")
        cache._path.parent.mkdir(parents=True, exist_ok=True)
        cache._path.write_text("not valid json")
        data = cache._load()
        assert data == {}
