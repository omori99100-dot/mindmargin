import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from mindmargin.config import settings


def setup_logger(name: str = "mindmargin") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(fmt)
    logger.addHandler(stdout)

    log_dir = Path(settings.storage.output_root)
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        str(log_dir / "pipeline.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


logger = setup_logger()
