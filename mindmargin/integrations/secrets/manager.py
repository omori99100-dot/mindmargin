import json
import logging
import os
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

REQUIRED_SECRETS = [
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
]

OPTIONAL_SECRETS = [
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
    "GOOGLE_DRIVE_CREDENTIALS",
    "PROMETHEUS_GATEWAY_URL",
    "OPENTELEMETRY_ENDPOINT",
    "WEBHOOK_SECRET",
]


class SecretManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._sec_dir = root / "integrations" / "secrets"
        self._sec_dir.mkdir(parents=True, exist_ok=True)
        self._store_path = self._sec_dir / "secrets.json"
        self._store: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self._store_path.exists():
            try:
                return json.loads(self._store_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to load secrets: %s", e)
        return {}

    def _save(self):
        self._store_path.write_text(
            json.dumps(self._store, indent=2), encoding="utf-8"
        )

    def get(self, name: str) -> Optional[str]:
        env_val = os.environ.get(name)
        if env_val:
            return env_val
        return self._store.get(name)

    def set(self, name: str, value: str):
        self._store[name] = value
        self._save()

    def set_many(self, secrets: dict[str, str]):
        self._store.update(secrets)
        self._save()

    def delete(self, name: str) -> bool:
        if name in self._store:
            del self._store[name]
            self._save()
            return True
        return False

    def list_all(self) -> dict[str, str]:
        result = {}
        for name in REQUIRED_SECRETS + OPTIONAL_SECRETS:
            val = self.get(name)
            result[name] = "set" if val else "missing"
        return result

    def validate(self) -> dict:
        missing_required = []
        missing_optional = []
        for name in REQUIRED_SECRETS:
            if not self.get(name):
                missing_required.append(name)
        for name in OPTIONAL_SECRETS:
            if not self.get(name):
                missing_optional.append(name)
        return {
            "valid": len(missing_required) == 0,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "total_required": len(REQUIRED_SECRETS),
            "total_optional": len(OPTIONAL_SECRETS),
            "set_count": sum(1 for n in REQUIRED_SECRETS + OPTIONAL_SECRETS if self.get(n)),
        }

    def is_configured(self, name: str) -> bool:
        return self.get(name) is not None

    def require(self, name: str) -> str:
        val = self.get(name)
        if not val:
            raise ValueError(f"Secret '{name}' is not configured")
        return val
