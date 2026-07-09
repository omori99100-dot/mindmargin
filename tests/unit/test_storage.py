"""Tests for core/storage.py — file-system helpers."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from mindmargin.core import storage as st


class TestSanitize:
    def test_removes_special_chars_and_truncates_to_64(self):
        raw = "hello world!!! @#$%^&*() more_text_here_to_exceed_sixty_four_characters_1234567890"
        result = st.sanitize(raw)
        assert "!" not in result
        assert "@" not in result
        assert "#" not in result
        assert len(result) <= 64

    def test_handles_empty_string(self):
        assert st.sanitize("") == ""

    def test_replaces_spaces_with_underscores(self):
        assert st.sanitize("my topic name") == "my_topic_name"

    def test_allows_alphanumeric_and_hyphen(self):
        assert st.sanitize("valid-name_123") == "valid-name_123"


class TestProjectDir:
    def test_returns_path(self):
        with patch("mindmargin.core.storage._safe_base", return_value=Path("/fake/base")):
            result = st.project_dir("test topic", "pipe_001")
        assert isinstance(result, Path)
        assert result.name == "pipe_001_test_topic"

    def test_includes_sanitized_topic(self):
        with patch("mindmargin.core.storage._safe_base", return_value=Path("/fake/base")):
            result = st.project_dir("Hello!!! World", "p1")
        assert result.name == "p1_Hello____World"


class TestEnsureDirs:
    def test_creates_all_directories(self, tmp_path):
        with patch("mindmargin.core.storage._safe_base", return_value=tmp_path):
            result = st.ensure_dirs("mytopic", "pid_1")
        for key, path in result.items():
            assert path.exists(), f"{key} directory missing"

    def test_returns_dict_with_all_expected_keys(self, tmp_path):
        with patch("mindmargin.core.storage._safe_base", return_value=tmp_path):
            result = st.ensure_dirs("t", "p")
        expected = {"root", "research", "script", "audio", "video", "captions", "temp", "thumbnails"}
        assert set(result.keys()) == expected


class TestWriteText:
    def test_creates_file_with_content(self, tmp_path):
        target = tmp_path / "sub" / "test.txt"
        result = st.write_text(target, "hello world")
        assert result == target
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "out.txt"
        st.write_text(target, "nested")
        assert target.exists()


class TestSafeBase:
    def test_resolves_correctly(self):
        with patch("mindmargin.core.storage.settings") as mock_settings:
            mock_settings.storage.output_root = str(Path.cwd() / "test_output")
            result = st._safe_base()
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_fallback_on_encoding_error(self):
        with patch("mindmargin.core.storage.settings") as mock_settings:
            mock_settings.storage.output_root = "/tmp/üñîçödé"
            with patch.dict(os.environ, {"TEMP": "C:\\Temp"}, clear=True):
                result = st._safe_base()
        assert "mindmargin_output" in str(result)

    def test_fallback_on_os_error(self):
        with patch("mindmargin.core.storage.settings") as mock_settings:
            original_resolve = Path.resolve
            call_count = [0]

            def _side_effect(self_path):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise OSError("bad path")
                return original_resolve(self_path)

            mock_settings.storage.output_root = "/bad/path"
            with patch.object(Path, "resolve", _side_effect):
                with patch.dict(os.environ, {"TEMP": "C:\\Temp"}, clear=True):
                    result = st._safe_base()
        assert "mindmargin_output" in str(result)
