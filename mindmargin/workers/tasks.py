import logging
from mindmargin.workers.celery_app import app
from mindmargin.core.pipeline import Pipeline

logger = logging.getLogger(__name__)


@app.task(bind=True, name="run_pipeline", max_retries=2)
def run_pipeline(self, topic: str):
    pipe = Pipeline(topic=topic, pipeline_id=f"celery_{self.request.id[:8]}")
    result = pipe.run()
    if result["status"] == "failed":
        logger.error(f"Pipeline {result['pipeline_id']} failed: {result['errors']}")
    return result
