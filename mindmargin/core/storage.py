import os
from pathlib import Path

from mindmargin.config import settings


def _safe_base() -> Path:
    base = Path(settings.storage.output_root)
    try:
        base_str = str(base.resolve())
        base_str.encode("ascii")
        return base.resolve()
    except (UnicodeEncodeError, OSError):
        temp = Path(os.environ.get("TEMP", "C:\\Temp")) / "mindmargin_output"
        temp.mkdir(parents=True, exist_ok=True)
        return temp.resolve()


def sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip().replace(" ", "_")[:64]


def project_dir(topic: str, pipeline_id: str) -> Path:
    slug = sanitize(topic)
    base = _safe_base() / f"{pipeline_id}_{slug}"
    return base


def ensure_dirs(topic: str, pipeline_id: str) -> dict[str, Path]:
    base = project_dir(topic, pipeline_id)
    dirs = {
        "root": base,
        "research": base / "research",
        "script": base / "script",
        "audio": base / "audio",
        "video": base / "video",
        "captions": base / "captions",
        "temp": base / "temp",
        "thumbnails": base / "thumbnails",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path

