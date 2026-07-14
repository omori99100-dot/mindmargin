"""HyperFrames composition layer — DISABLED (rolled back due to performance regression)."""

import logging

logger = logging.getLogger(__name__)


def hyperframes_available() -> bool:
    logger.info("HyperFrames disabled — all rendering uses FFmpeg")
    return False
