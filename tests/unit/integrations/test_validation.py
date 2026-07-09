"""Unit tests for mindmargin.integrations.validation.validator."""

import pytest
from pathlib import Path


@pytest.fixture
def validator():
    from mindmargin.integrations.validation.validator import ProductionValidator
    return ProductionValidator()


class TestValidationResult:
    def test_to_dict(self):
        from mindmargin.integrations.validation.validator import ValidationResult
        r = ValidationResult(check="test", passed=True, message="ok")
        d = r.to_dict()
        assert d["check"] == "test"
        assert d["passed"] is True


class TestValidateAssets:
    def test_video_not_provided(self, validator):
        results = validator.validate_assets("")
        assert any(not r.passed for r in results)

    def test_video_not_found(self, validator):
        results = validator.validate_assets("/nonexistent/video.mp4")
        assert any(not r.passed for r in results)

    def test_video_valid(self, validator, tmp_path):
        vid = tmp_path / "video.mp4"
        vid.write_bytes(b"\x00" * 1000)
        results = validator.validate_assets(str(vid))
        assert all(r.passed for r in results)

    def test_thumbnail_valid(self, validator, tmp_path):
        vid = tmp_path / "video.mp4"
        vid.write_bytes(b"\x00" * 1000)
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"\x00" * 500)
        results = validator.validate_assets(str(vid), str(thumb))
        assert all(r.passed for r in results)

    def test_subtitle_valid(self, validator, tmp_path):
        vid = tmp_path / "video.mp4"
        vid.write_bytes(b"\x00" * 1000)
        sub = tmp_path / "subs.srt"
        sub.write_text("1\n00:00:01 --> 00:00:02\nHello")
        results = validator.validate_assets(str(vid), "", str(sub))
        assert all(r.passed for r in results)

    def test_bad_extension(self, validator, tmp_path):
        vid = tmp_path / "video.exe"
        vid.write_bytes(b"\x00" * 1000)
        results = validator.validate_assets(str(vid))
        ext_check = [r for r in results if r.check == "video"]
        assert len(ext_check) > 0
        assert any(not r.passed for r in ext_check)


class TestValidateMetadata:
    def test_title_too_short(self, validator):
        results = validator.validate_metadata("ab")
        title_check = [r for r in results if r.check == "title_valid"][0]
        assert title_check.passed is False

    def test_title_too_long(self, validator):
        results = validator.validate_metadata("x" * 101)
        title_check = [r for r in results if r.check == "title_valid"][0]
        assert title_check.passed is False

    def test_title_valid(self, validator):
        results = validator.validate_metadata("My Good Title")
        title_check = [r for r in results if r.check == "title_valid"][0]
        assert title_check.passed is True

    def test_description_too_long(self, validator):
        results = validator.validate_metadata("Good Title", "x" * 5001)
        desc_check = [r for r in results if r.check == "description_valid"][0]
        assert desc_check.passed is False

    def test_tags_too_many(self, validator):
        results = validator.validate_metadata("Good Title", "desc", tags=[f"tag{i}" for i in range(31)])
        tags_check = [r for r in results if r.check == "tags_valid"][0]
        assert tags_check.passed is False

    def test_tags_valid(self, validator):
        results = validator.validate_metadata("Good Title", "desc", tags=["a", "b"])
        tags_check = [r for r in results if r.check == "tags_valid"][0]
        assert tags_check.passed is True


class TestValidateAll:
    def test_all_pass(self, validator, tmp_path):
        vid = tmp_path / "video.mp4"
        vid.write_bytes(b"\x00" * 1000)
        result = validator.validate_all(str(vid), "My Good Title", "Description", ["tag1"])
        assert "passed" in result
        assert "total_checks" in result
        assert "failed_checks" in result

    def test_fails_on_bad_input(self, validator):
        result = validator.validate_all("/nonexistent", "ab")
        assert result["passed"] is False
        assert len(result["failed_checks"]) > 0
