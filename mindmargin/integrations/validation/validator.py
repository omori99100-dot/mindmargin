import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    check: str = ""
    passed: bool = True
    message: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "passed": self.passed,
            "message": self.message,
            "details": self.details,
        }


class ProductionValidator:
    def validate_assets(self, video_path: str, thumbnail_path: str = "",
                        subtitle_path: str = "") -> list[ValidationResult]:
        results = []
        results.append(self._check_file_exists(video_path, "video_file"))
        if thumbnail_path:
            results.append(self._check_file_exists(thumbnail_path, "thumbnail"))
            results.append(self._check_file_size(thumbnail_path, "thumbnail", max_mb=5))
        if subtitle_path:
            results.append(self._check_file_exists(subtitle_path, "subtitle"))
        if video_path and Path(video_path).exists():
            results.append(self._check_file_size(video_path, "video", max_mb=5000))
            results.append(self._check_file_extension(video_path, "video", [".mp4", ".mov", ".avi", ".mkv"])
                           )
        return results

    def validate_metadata(self, title: str, description: str = "",
                          tags: list[str] = None) -> list[ValidationResult]:
        results = []
        if not title or len(title.strip()) < 5:
            results.append(ValidationResult("title_valid", False, "Title too short (min 5 chars)"))
        elif len(title) > 100:
            results.append(ValidationResult("title_valid", False, "Title too long (max 100 chars)"))
        else:
            results.append(ValidationResult("title_valid", True, "Title OK"))

        if description and len(description) > 5000:
            results.append(ValidationResult("description_valid", False, "Description too long"))
        else:
            results.append(ValidationResult("description_valid", True, "Description OK"))

        if tags:
            if len(tags) > 30:
                results.append(ValidationResult("tags_valid", False, "Too many tags (max 30)"))
            else:
                results.append(ValidationResult("tags_valid", True, f"{len(tags)} tags"))
        else:
            results.append(ValidationResult("tags_valid", True, "No tags"))

        return results

    def validate_credentials(self) -> list[ValidationResult]:
        results = []
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        validation = sm.validate()
        results.append(ValidationResult(
            "youtube_credentials",
            validation["valid"],
            f"Missing: {', '.join(validation['missing_required'])}" if validation["missing_required"] else "All set",
            validation,
        ))
        return results

    def validate_quota(self) -> list[ValidationResult]:
        results = []
        try:
            from mindmargin.integrations.youtube.connector import YouTubeConnector
            yt = YouTubeConnector()
            quota = yt.get_quota()
            results.append(ValidationResult(
                "upload_quota",
                quota.can_upload(),
                f"Remaining: {quota.upload_remaining}/{quota.upload_limit}",
                quota.to_dict(),
            ))
        except Exception as e:
            results.append(ValidationResult("upload_quota", False, str(e)))
        return results

    def validate_upload_size(self, file_path: str, max_mb: int = 5000) -> list[ValidationResult]:
        results = []
        if not file_path or not Path(file_path).exists():
            results.append(ValidationResult("upload_size", False, "File not found"))
            return results
        size_mb = Path(file_path).stat().st_size / (1024 * 1024)
        results.append(ValidationResult(
            "upload_size",
            size_mb <= max_mb,
            f"{size_mb:.1f}MB / {max_mb}MB",
            {"size_mb": round(size_mb, 1), "max_mb": max_mb},
        ))
        return results

    def validate_all(self, video_path: str, title: str, description: str = "",
                     tags: list[str] = None, thumbnail_path: str = "",
                     subtitle_path: str = "") -> dict:
        results = []
        results.extend(self.validate_assets(video_path, thumbnail_path, subtitle_path))
        results.extend(self.validate_metadata(title, description, tags))
        results.extend(self.validate_credentials())
        results.extend(self.validate_quota())
        results.extend(self.validate_upload_size(video_path))

        passed = all(r.passed for r in results)
        failed = [r.to_dict() for r in results if not r.passed]

        return {
            "passed": passed,
            "total_checks": len(results),
            "passed_checks": sum(1 for r in results if r.passed),
            "failed_checks": failed,
            "results": [r.to_dict() for r in results],
        }

    def _check_file_exists(self, path: str, label: str) -> ValidationResult:
        if not path:
            return ValidationResult(label, False, "Path not provided")
        if not Path(path).exists():
            return ValidationResult(label, False, f"File not found: {path}")
        return ValidationResult(label, True, "File exists")

    def _check_file_size(self, path: str, label: str, max_mb: int = 100) -> ValidationResult:
        try:
            size_mb = Path(path).stat().st_size / (1024 * 1024)
            if size_mb > max_mb:
                return ValidationResult(label, False, f"{size_mb:.1f}MB exceeds {max_mb}MB limit")
            return ValidationResult(label, True, f"{size_mb:.1f}MB OK")
        except Exception as e:
            return ValidationResult(label, False, str(e))

    def _check_file_extension(self, path: str, label: str, allowed: list[str]) -> ValidationResult:
        ext = Path(path).suffix.lower()
        if ext not in allowed:
            return ValidationResult(label, False, f"Extension '{ext}' not in {allowed}")
        return ValidationResult(label, True, f"Extension '{ext}' OK")
