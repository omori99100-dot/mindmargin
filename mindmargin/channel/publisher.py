import logging
from datetime import datetime, timezone
from typing import Optional

from mindmargin.channel.lifecycle import ContentLifecycle
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState
from mindmargin.core.hardening import utcnow
from mindmargin.core.workflows import WorkflowEngine
from mindmargin.operations.controller import OperationsController
from mindmargin.operations.models import OperationType

logger = logging.getLogger(__name__)


class ChannelPublisher:
    def __init__(self, lifecycle: Optional[ContentLifecycle] = None,
                 engine: Optional[WorkflowEngine] = None):
        self._lifecycle = lifecycle or ContentLifecycle()
        self._engine = engine or WorkflowEngine()

    def publish(self, content_id: str, auto_publish: bool = True,
                privacy: str = "unlisted") -> dict:
        item = self._lifecycle.get(content_id)
        if not item:
            return {"status": "failed", "error": "content_not_found"}
        if not item.can_transition_to(ContentState.PRODUCING):
            return {"status": "failed", "error": f"Cannot publish from state {item.state.value}"}

        self._lifecycle.transition_to(content_id, ContentState.PRODUCING)
        try:
            controller = OperationsController(engine=self._engine)
            result = controller.run_operation(
                OperationType.DECISION_EXECUTOR,
                metadata={
                    "topic": item.topic,
                    "content_id": content_id,
                    "auto_publish": auto_publish,
                    "privacy": privacy,
                    "format": item.format.value,
                },
            )
            if result.get("status") == "completed":
                self._lifecycle.update_item(
                    content_id,
                    workflow_id=result.get("workflow_id", ""),
                    pipeline_id=result.get("operation_id", ""),
                )
                self._lifecycle.transition_to(content_id, ContentState.REVIEWING)
            else:
                self._lifecycle.update_item(content_id, governance_blocked=True,
                                            governance_block_reason=result.get("error", ""))
            return result
        except Exception as e:
            logger.error("Publish failed for '%s': %s", item.topic, e)
            return {"status": "failed", "error": str(e)}

    def update_playlists(self, content_id: str, playlist_ids: list[str]) -> bool:
        return self._lifecycle.update_item(content_id, playlist_ids=playlist_ids)

    def mark_published(self, content_id: str, video_id: str = "",
                       pipeline_id: str = "") -> bool:
        item = self._lifecycle.get(content_id)
        if not item:
            return False
        self._lifecycle.update_item(
            content_id,
            video_id=video_id,
            pipeline_id=pipeline_id or item.pipeline_id,
            published_at=utcnow(),
        )
        return self._lifecycle.transition_to(content_id, ContentState.PUBLISHED)

    def mark_scheduled(self, content_id: str, publish_at: Optional[str] = None) -> bool:
        updates = {}
        if publish_at:
            updates["estimated_publish_at"] = publish_at
        if updates:
            self._lifecycle.update_item(content_id, **updates)
        return self._lifecycle.transition_to(content_id, ContentState.SCHEDULED)

    def push_to_pipeline(self, content_id: str) -> dict:
        item = self._lifecycle.get(content_id)
        if not item:
            return {"status": "failed", "error": "content_not_found"}
        from mindmargin.core.pipeline import Pipeline
        try:
            pipe = Pipeline(topic=item.topic, duration_scale=1.0)
            result = pipe.run()
            if result.get("status") == "completed":
                self._lifecycle.update_item(
                    content_id,
                    workflow_id=result.get("pipeline_id", ""),
                    pipeline_id=result.get("pipeline_id", ""),
                )
                self._lifecycle.transition_to(content_id, ContentState.REVIEWING)
            return result
        except Exception as e:
            logger.error("Pipeline push failed: %s", e)
            return {"status": "failed", "error": str(e)}
