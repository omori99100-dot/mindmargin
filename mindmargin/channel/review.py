import logging
from typing import Optional

from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import ContentItem, ContentState

logger = logging.getLogger(__name__)

AUTO_APPROVE_CONFIDENCE = 0.7
AUTO_APPROVE_OPPORTUNITY = 50.0


class ContentReview:
    def __init__(self, lifecycle: Optional[ContentLifecycle] = None):
        self._lifecycle = lifecycle or ContentLifecycle()

    def review_item(self, content_id: str) -> dict:
        item = self._lifecycle.get(content_id)
        if not item:
            return {"status": "failed", "error": "content_not_found"}
        checks = self._run_checks(item)
        passed = all(c["passed"] for c in checks)
        result = {
            "content_id": content_id,
            "topic": item.topic,
            "status": "approved" if passed else "flagged",
            "checks": checks,
            "passed": passed,
            "total_checks": len(checks),
            "passed_checks": sum(1 for c in checks if c["passed"]),
        }
        if passed:
            self._lifecycle.update_item(content_id, review_notes="Auto-approved")
        else:
            failed = [c["name"] for c in checks if not c["passed"]]
            self._lifecycle.update_item(content_id, review_notes=f"Flagged: {', '.join(failed)}")
        return result

    def auto_approve(self, item: ContentItem) -> bool:
        if item.confidence >= AUTO_APPROVE_CONFIDENCE and item.opportunity_score >= AUTO_APPROVE_OPPORTUNITY:
            logger.info("Auto-approved '%s' (conf=%.2f, opp=%.1f)", item.topic, item.confidence, item.opportunity_score)
            return True
        return False

    def flag_for_review(self, item: ContentItem) -> bool:
        return not self.auto_approve(item)

    def _run_checks(self, item: ContentItem) -> list[dict]:
        checks = []
        checks.append(self._check_topic_quality(item))
        checks.append(self._check_confidence(item))
        checks.append(self._check_opportunity(item))
        checks.append(self._check_asset_requirements(item))
        checks.append(self._check_duplicate_content(item))
        return checks

    def _check_topic_quality(self, item: ContentItem) -> dict:
        topic = item.topic.strip()
        if len(topic) < 10:
            return {"name": "topic_quality", "passed": False, "detail": "Topic too short"}
        if len(topic) > 200:
            return {"name": "topic_quality", "passed": False, "detail": "Topic too long"}
        return {"name": "topic_quality", "passed": True, "detail": "OK"}

    def _check_confidence(self, item: ContentItem) -> dict:
        if item.confidence < 0.3:
            return {"name": "confidence", "passed": False, "detail": f"Confidence {item.confidence:.2f} < 0.3"}
        return {"name": "confidence", "passed": True, "detail": f"Confidence {item.confidence:.2f}"}

    def _check_opportunity(self, item: ContentItem) -> dict:
        if item.opportunity_score < 20:
            return {"name": "opportunity", "passed": False, "detail": f"Score {item.opportunity_score:.1f} < 20"}
        return {"name": "opportunity", "passed": True, "detail": f"Score {item.opportunity_score:.1f}"}

    def _check_asset_requirements(self, item: ContentItem) -> dict:
        if item.asset_requirements:
            return {"name": "assets", "passed": False, "detail": f"Requires: {', '.join(item.asset_requirements)}"}
        return {"name": "assets", "passed": True, "detail": "No special assets required"}

    def _check_duplicate_content(self, item: ContentItem) -> dict:
        try:
            from mindmargin.intelligence.knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph()
            is_dup, matched, strength = kg.is_duplicate_coverage(item.topic)
            if is_dup:
                return {"name": "duplicate", "passed": False, "detail": f"Similar to '{matched}' (strength={strength:.2f})"}
        except Exception as e:
            logger.warning("Duplicate check failed: %s", e)
        return {"name": "duplicate", "passed": True, "detail": "No duplicate detected"}
