"""Unit tests for mindmargin.integrations.storage.connector."""

import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def local_storage(tmp_path):
    from mindmargin.integrations.storage.connector import LocalStorage
    storage = LocalStorage()
    storage._root = tmp_path / "storage"
    storage._root.mkdir(parents=True, exist_ok=True)
    return storage


class TestStorageObject:
    def test_to_dict(self):
        from mindmargin.integrations.storage.connector import StorageObject
        obj = StorageObject(key="test.mp4", size=1024, content_type="video/mp4")
        d = obj.to_dict()
        assert d["key"] == "test.mp4"
        assert d["size"] == 1024
        assert d["content_type"] == "video/mp4"

    def test_default_metadata(self):
        from mindmargin.integrations.storage.connector import StorageObject
        obj = StorageObject(key="x")
        assert obj.metadata == {}


class TestLocalStorage:
    def test_upload_and_exists(self, local_storage, tmp_path):
        src = tmp_path / "test.txt"
        src.write_text("hello")
        result = local_storage.upload(str(src), "test.txt")
        assert result.key == "test.txt"
        assert result.size == 5
        assert local_storage.exists("test.txt") is True

    def test_upload_nonexistent_raises(self, local_storage):
        with pytest.raises(FileNotFoundError):
            local_storage.upload("/nonexistent/file.txt", "x.txt")

    def test_download(self, local_storage, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("data")
        local_storage.upload(str(src), "dl.txt")
        dest = tmp_path / "dest.txt"
        ok = local_storage.download("dl.txt", str(dest))
        assert ok is True
        assert dest.read_text() == "data"

    def test_download_nonexistent(self, local_storage, tmp_path):
        ok = local_storage.download("no_such.txt", str(tmp_path / "out.txt"))
        assert ok is False

    def test_delete(self, local_storage, tmp_path):
        src = tmp_path / "del.txt"
        src.write_text("x")
        local_storage.upload(str(src), "del.txt")
        assert local_storage.delete("del.txt") is True
        assert local_storage.delete("del.txt") is False

    def test_list_objects(self, local_storage, tmp_path):
        for name in ["a.txt", "b.txt", "sub/c.txt"]:
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
            local_storage.upload(str(p), name)
        objs = local_storage.list_objects()
        assert len(objs) == 3

    def test_list_objects_with_prefix(self, local_storage, tmp_path):
        for name in ["a.txt", "sub/b.txt"]:
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
            local_storage.upload(str(p), name)
        objs = local_storage.list_objects("sub")
        assert len(objs) == 1
        assert objs[0].key.replace("\\", "/") == "sub/b.txt"

    def test_get_url(self, local_storage):
        url = local_storage.get_url("test.mp4")
        assert "test.mp4" in url

    def test_get_info(self, local_storage, tmp_path):
        src = tmp_path / "info.txt"
        src.write_text("content")
        local_storage.upload(str(src), "info.txt")
        info = local_storage.get_info()
        assert info["backend"] == "local"
        assert info["total_objects"] == 1


class TestStorageConnector:
    def test_uses_local_backend(self, tmp_path):
        from mindmargin.integrations.storage.connector import StorageConnector, LocalStorage
        storage = StorageConnector()
        assert isinstance(storage._backend, LocalStorage)

    def test_upload_delegates(self, tmp_path):
        from mindmargin.integrations.storage.connector import StorageConnector
        storage = StorageConnector()
        src = tmp_path / "deleg.txt"
        src.write_text("hello")
        result = storage.upload(str(src), "deleg.txt")
        assert result.key == "deleg.txt"
