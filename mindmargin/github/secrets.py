import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

REQUIRED_GITHUB_SECRETS = [
    "GITHUB_TOKEN",
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
]

OPTIONAL_GITHUB_SECRETS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "DISCORD_WEBHOOK_URL",
    "SLACK_WEBHOOK_URL",
    "NOTIFY_EMAIL",
    "NOTIFY_EMAIL_PASSWORD",
    "S3_BUCKET",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_ENDPOINT",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "WEBHOOK_SECRET",
    "PROMETHEUS_GATEWAY_URL",
]

REQUIRED_ENV_VARS = [
    "GITHUB_REPOSITORY",
    "GITHUB_REF",
    "GITHUB_SHA",
]


@dataclass
class SecretCheck:
    name: str = ""
    status: str = "missing"
    source: str = ""
    is_required: bool = True
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "source": self.source,
            "is_required": self.is_required,
            "message": self.message,
        }


@dataclass
class SecretsValidationReport:
    timestamp: str = ""
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    checks: list[SecretCheck] = field(default_factory=list)
    repository_config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_checks": self.total_checks,
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "valid": self.failed == 0,
            "checks": [c.to_dict() for c in self.checks],
            "repository_config": self.repository_config,
        }


class SecretsValidator:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._val_dir = root / "github" / "secrets"
        self._val_dir.mkdir(parents=True, exist_ok=True)
        self._history_path = self._val_dir / "validation_history.json"
        self._lock = threading.RLock()
        self._history: list[dict] = self._load_history()

    def _load_history(self) -> list[dict]:
        if self._history_path.exists():
            try:
                return json.loads(self._history_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_history(self):
        self._history_path.write_text(
            json.dumps(self._history[-100:], indent=2), encoding="utf-8"
        )

    def _check_secret(self, name: str, is_required: bool) -> SecretCheck:
        env_val = os.environ.get(name)
        if env_val:
            return SecretCheck(name=name, status="set", source="environment",
                               is_required=is_required, message="Set via environment")

        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        store_val = sm.get(name)
        if store_val:
            return SecretCheck(name=name, status="set", source="secret_store",
                               is_required=is_required, message="Set in secret store")

        status = "missing_required" if is_required else "missing_optional"
        return SecretCheck(
            name=name, status=status, source="none",
            is_required=is_required,
            message=f"{'Required' if is_required else 'Optional'} secret not configured",
        )

    def validate_secrets(self) -> SecretsValidationReport:
        checks = []
        for name in REQUIRED_GITHUB_SECRETS:
            checks.append(self._check_secret(name, is_required=True))
        for name in OPTIONAL_GITHUB_SECRETS:
            checks.append(self._check_secret(name, is_required=False))

        passed = sum(1 for c in checks if c.status == "set")
        failed = sum(1 for c in checks if c.status == "missing_required")
        warnings = sum(1 for c in checks if c.status == "missing_optional")

        report = SecretsValidationReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_checks=len(checks),
            passed=passed,
            failed=failed,
            warnings=warnings,
            checks=checks,
        )

        with self._lock:
            self._history.append(report.to_dict())
            self._save_history()

        return report

    def validate_env_vars(self) -> list[dict]:
        results = []
        for name in REQUIRED_ENV_VARS:
            val = os.environ.get(name)
            results.append({
                "name": name,
                "set": val is not None,
                "value_preview": (val[:20] + "...") if val and len(val) > 20 else (val or ""),
            })
        return results

    def validate_repository_config(self) -> dict:
        config = {
            "repository": os.environ.get("GITHUB_REPOSITORY", ""),
            "ref": os.environ.get("GITHUB_REF", ""),
            "sha": os.environ.get("GITHUB_SHA", ""),
            "actor": os.environ.get("GITHUB_ACTOR", ""),
            "workflow": os.environ.get("GITHUB_WORKFLOW", ""),
            "run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "run_number": os.environ.get("GITHUB_RUN_NUMBER", ""),
            "event_name": os.environ.get("GITHUB_EVENT_NAME", ""),
            "server_url": os.environ.get("GITHUB_SERVER_URL", ""),
            "api_url": os.environ.get("GITHUB_API_URL", ""),
            "workspace": os.environ.get("GITHUB_WORKSPACE", ""),
            "is_github_actions": os.environ.get("GITHUB_ACTIONS") == "true",
        }
        return config

    def validate_all(self) -> dict:
        secrets_report = self.validate_secrets()
        env_vars = self.validate_env_vars()
        repo_config = self.validate_repository_config()

        secrets_report.repository_config = repo_config

        return {
            "secrets": secrets_report.to_dict(),
            "env_vars": env_vars,
            "repository_config": repo_config,
            "overall_valid": secrets_report.failed == 0 and all(e["set"] for e in env_vars),
        }

    def get_validation_history(self, limit: int = 10) -> list[dict]:
        with self._lock:
            return self._history[-limit:]

    def get_status(self) -> dict:
        last = self._history[-1] if self._history else {}
        return {
            "last_validation": last.get("timestamp", ""),
            "total_validations": len(self._history),
            "last_result": last.get("valid", None),
            "required_count": len(REQUIRED_GITHUB_SECRETS),
            "optional_count": len(OPTIONAL_GITHUB_SECRETS),
            "env_var_count": len(REQUIRED_ENV_VARS),
        }
