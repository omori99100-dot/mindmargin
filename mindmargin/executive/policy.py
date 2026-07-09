import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


class PolicyType(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    GROWTH = "growth"
    CUSTOM = "custom"


@dataclass
class PolicyConfig:
    policy_type: PolicyType = PolicyType.BALANCED
    publishing_frequency_hours: int = 24
    risk_tolerance: float = 0.5
    experiment_frequency_hours: int = 168
    budget_usage_pct: float = 50.0
    auto_approve_threshold: float = 0.7
    max_concurrent_workflows: int = 3
    health_check_interval_hours: int = 6
    provider_timeout_s: int = 30
    enable_auto_publish: bool = True
    enable_auto_experiments: bool = True
    enable_provider_fallback: bool = True
    description: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["policy_type"] = self.policy_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyConfig":
        if "policy_type" in d and isinstance(d["policy_type"], str):
            d["policy_type"] = PolicyType(d["policy_type"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


PRESETS = {
    PolicyType.CONSERVATIVE: PolicyConfig(
        policy_type=PolicyType.CONSERVATIVE,
        publishing_frequency_hours=48,
        risk_tolerance=0.2,
        experiment_frequency_hours=336,
        budget_usage_pct=30.0,
        auto_approve_threshold=0.85,
        max_concurrent_workflows=2,
        health_check_interval_hours=12,
        enable_auto_publish=False,
        enable_auto_experiments=False,
        description="Minimal risk. Manual publish approval. Infrequent experiments.",
    ),
    PolicyType.BALANCED: PolicyConfig(
        policy_type=PolicyType.BALANCED,
        publishing_frequency_hours=24,
        risk_tolerance=0.5,
        experiment_frequency_hours=168,
        budget_usage_pct=50.0,
        auto_approve_threshold=0.7,
        max_concurrent_workflows=3,
        health_check_interval_hours=6,
        enable_auto_publish=True,
        enable_auto_experiments=True,
        description="Moderate risk. Auto-publish high-confidence. Weekly experiments.",
    ),
    PolicyType.AGGRESSIVE: PolicyConfig(
        policy_type=PolicyType.AGGRESSIVE,
        publishing_frequency_hours=12,
        risk_tolerance=0.8,
        experiment_frequency_hours=72,
        budget_usage_pct=75.0,
        auto_approve_threshold=0.5,
        max_concurrent_workflows=5,
        health_check_interval_hours=3,
        enable_auto_publish=True,
        enable_auto_experiments=True,
        description="High frequency. Accept risk. Frequent experiments.",
    ),
    PolicyType.GROWTH: PolicyConfig(
        policy_type=PolicyType.GROWTH,
        publishing_frequency_hours=18,
        risk_tolerance=0.7,
        experiment_frequency_hours=48,
        budget_usage_pct=80.0,
        auto_approve_threshold=0.6,
        max_concurrent_workflows=4,
        health_check_interval_hours=4,
        enable_auto_publish=True,
        enable_auto_experiments=True,
        description="Maximum growth. Aggressive experiments. High output.",
    ),
}


class PolicyEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._policy_dir = root / "executive" / "policy"
        self._policy_dir.mkdir(parents=True, exist_ok=True)
        self._config: PolicyConfig = self._load()

    def _config_path(self) -> Path:
        return self._policy_dir / "policy.json"

    def _load(self) -> PolicyConfig:
        p = self._config_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return PolicyConfig.from_dict(data)
            except Exception as e:
                logger.warning("Failed to load policy: %s", e)
        return PRESETS[PolicyType.BALANCED]

    def _save(self):
        self._config_path().write_text(
            json.dumps(self._config.to_dict(), indent=2), encoding="utf-8"
        )

    def get_config(self) -> PolicyConfig:
        return self._config

    def set_policy(self, policy_type: PolicyType) -> PolicyConfig:
        preset = PRESETS[policy_type]
        self._config = PolicyConfig(**{k: v for k, v in preset.to_dict().items() if k in PolicyConfig.__dataclass_fields__})
        self._config.policy_type = policy_type
        self._save()
        logger.info("Policy set to %s", policy_type.value)
        return self._config

    def update_config(self, **kwargs) -> PolicyConfig:
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        self._save()
        return self._config

    def should_publish(self, confidence: float, hours_since_last: float) -> bool:
        if not self._config.enable_auto_publish:
            return False
        if hours_since_last < self._config.publishing_frequency_hours:
            return False
        return confidence >= self._config.auto_approve_threshold

    def should_experiment(self, hours_since_last: float) -> bool:
        if not self._config.enable_auto_experiments:
            return False
        return hours_since_last >= self._config.experiment_frequency_hours

    def max_concurrent(self) -> int:
        return self._config.max_concurrent_workflows

    def risk_tolerance(self) -> float:
        return self._config.risk_tolerance

    def budget_pct(self) -> float:
        return self._config.budget_usage_pct

    def get_all_preset_names(self) -> list[str]:
        return [p.value for p in PolicyType]

    def get_preset(self, policy_type: PolicyType) -> PolicyConfig:
        return PRESETS[policy_type]
