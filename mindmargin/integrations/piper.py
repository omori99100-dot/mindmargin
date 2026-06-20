import logging
import subprocess
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


def piper_available() -> bool:
    try:
        subprocess.run([settings.piper.binary, "--help"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def generate_wav(text: str, output_path: str | Path,
                 length_scale: float = 1.0,
                 noise_scale: float = 0.667,
                 noise_w: float = 0.8,
                 duration_s: float = 2.0) -> Optional[Path]:
    """Generate a WAV file from text using Piper TTS. Returns path or None."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not piper_available():
        logger.warning("Piper binary not found — creating silent placeholder")
        _write_silent_wav(out, duration_s=duration_s)
        return out

    cmd = [
        settings.piper.binary,
        "--model", settings.piper.voice_model if not settings.piper.model_path else settings.piper.model_path,
        "--output-file", str(out),
        "--length-scale", str(length_scale),
        "--noise-scale", str(noise_scale),
        "--noise-w", str(noise_w),
        "--sample-rate", str(settings.piper.sample_rate),
    ]

    try:
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=300,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode().strip()
            logger.error(f"Piper failed (rc={proc.returncode}): {stderr}")
            _write_silent_wav(out, duration_s=duration_s)
            return out
        logger.info(f"Piper WAV: {out} ({out.stat().st_size / 1024:.1f} KB)")
        return out
    except FileNotFoundError:
        logger.warning("Piper not on PATH — creating silent placeholder")
        _write_silent_wav(out, duration_s=duration_s)
        return out
    except subprocess.TimeoutExpired:
        logger.error("Piper timed out after 300s")
        _write_silent_wav(out, duration_s=duration_s)
        return out
    except Exception as e:
        logger.error(f"Piper error: {e}")
        _write_silent_wav(out, duration_s=duration_s)
        return out


def _write_silent_wav(path: Path, duration_s: float = 2.0, sample_rate: int = 22050):
    """Write a silent WAV file as placeholder when Piper is unavailable."""
    import struct
    num_samples = int(sample_rate * duration_s)
    data_size = num_samples * 2
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00\x00" * num_samples)
