import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

MAX_MEMORY_ENTRIES = 2000
MEMORY_CATEGORIES = (
    "strategy_success",
    "strategy_failure",
    "execution_history",
    "seasonality",
    "audience_preference",
    "content_fatigue",
    "provider_reliability",
    "trend_pattern",
    "experiment_outcome",
    "health_snapshot",
    "decision_rationale",
    "lesson_learned",
)


class ExecutiveMemory:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._mem_dir = root / "executive" / "memory"
        self._mem_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._mem_dir / "index.json"
        self._entries: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to load memory index: %s", e)
        return []

    def _save(self):
        if len(self._entries) > MAX_MEMORY_ENTRIES:
            self._entries = sorted(self._entries, key=lambda e: e.get("ts", ""), reverse=True)[:MAX_MEMORY_ENTRIES]
        self._index_path.write_text(
            json.dumps(self._entries, indent=2, default=str), encoding="utf-8"
        )

    def record(self, category: str, key: str, value: dict, score: float = 0.0) -> dict:
        entry = {
            "category": category,
            "key": key,
            "value": value,
            "score": score,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._entries.append(entry)
        self._save()
        return entry

    def query(self, category: Optional[str] = None, key: Optional[str] = None,
              limit: int = 50) -> list[dict]:
        results = self._entries
        if category:
            results = [e for e in results if e["category"] == category]
        if key:
            lower = key.lower()
            results = [e for e in results if lower in e.get("key", "").lower()]
        return sorted(results, key=lambda e: e.get("ts", ""), reverse=True)[:limit]

    def get_successful_strategies(self, limit: int = 20) -> list[dict]:
        return self.query(category="strategy_success", limit=limit)

    def get_failed_strategies(self, limit: int = 20) -> list[dict]:
        return self.query(category="strategy_failure", limit=limit)

    def get_lessons(self, limit: int = 50) -> list[dict]:
        return self.query(category="lesson_learned", limit=limit)

    def get_execution_history(self, limit: int = 100) -> list[dict]:
        return self.query(category="execution_history", limit=limit)

    def get_provider_reliability(self, provider: str) -> dict:
        entries = self.query(category="provider_reliability", key=provider, limit=10)
        if not entries:
            return {"provider": provider, "reliability": 1.0, "failures": 0, "successes": 0}
        successes = sum(1 for e in entries if e.get("value", {}).get("success", False))
        total = len(entries)
        reliability = successes / total if total > 0 else 1.0
        return {
            "provider": provider,
            "reliability": round(reliability, 3),
            "failures": total - successes,
            "successes": successes,
            "last_check": entries[0].get("ts", ""),
        }

    def get_seasonality(self) -> dict:
        entries = self.query(category="seasonality", limit=50)
        patterns = {}
        for e in entries:
            key = e.get("key", "")
            patterns.setdefault(key, []).append(e.get("value", {}))
        return patterns

    def get_content_fatigue(self, topic: str) -> float:
        entries = self.query(category="content_fatigue", key=topic, limit=10)
        if not entries:
            return 0.0
        return entries[0].get("score", 0.0)

    def get_decision_rationales(self, limit: int = 20) -> list[dict]:
        return self.query(category="decision_rationale", limit=limit)

    def clear_category(self, category: str):
        self._entries = [e for e in self._entries if e["category"] != category]
        self._save()

    def clear_all(self):
        self._entries.clear()
        self._save()

    def count(self) -> int:
        return len(self._entries)

    def to_dict(self) -> dict:
        categories = {}
        for e in self._entries:
            cat = e["category"]
            categories.setdefault(cat, 0)
            categories[cat] += 1
        return {
            "total": len(self._entries),
            "categories": categories,
            "oldest": self._entries[-1]["ts"] if self._entries else "",
            "newest": self._entries[0]["ts"] if self._entries else "",
        }
