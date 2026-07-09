import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

_FFMPEG_DIRS = [
    r"C:\Users\A Center\AppData\Local\Temp\ffmpeg_gpl\ffmpeg-n7.1-latest-win64-gpl-7.1\bin",
    r"C:\Users\A Center\AppData\Local\ffmpeg",
    r"C:\Users\A Center\AppData\Local\ffmpeg\ffmpeg-n7.1-latest-win64-lgpl-7.1\bin",
]

_BEST_ENCODER_CACHE: Optional[str] = None


def _find_ffmpeg() -> list[str]:
    for d in _FFMPEG_DIRS:
        exe = os.path.join(d, "ffmpeg.exe")
        if os.path.isfile(exe):
            return [exe]
    return ["ffmpeg"]


def _verify_encoder(ffmpeg: str, encoder: str) -> bool:
    import tempfile, uuid
    test_path = os.path.join(tempfile.gettempdir(), f"enc_test_{uuid.uuid4().hex[:8]}.mp4")
    try:
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1:r=10",
               "-c:v", encoder, "-pix_fmt", "yuv420p", test_path]
        proc = subprocess.run(cmd, capture_output=True, timeout=15)
        if proc.returncode == 0 and os.path.isfile(test_path) and os.path.getsize(test_path) > 0:
            return True
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False
    finally:
        try:
            if os.path.isfile(test_path):
                os.remove(test_path)
        except Exception:
            pass


def _benchmark_encoder(ffmpeg: str, encoder: str, label: str) -> Optional[tuple[str, str, float]]:
    """Benchmark encoder with a 5-second 1080p render, return (encoder, label, fps)."""
    import tempfile, uuid
    test_path = os.path.join(tempfile.gettempdir(), f"enc_bench_{uuid.uuid4().hex[:8]}.mp4")
    try:
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
               f"color=c=blue:s=1920x1080:d=5:r=30",
               "-c:v", encoder, "-pix_fmt", "yuv420p", test_path]
        start = time.time()
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        elapsed = time.time() - start
        if proc.returncode == 0 and os.path.isfile(test_path) and os.path.getsize(test_path) > 0:
            fps = (5 * 30) / elapsed  # frames / seconds
            logger.debug(f"Encoder benchmark: {encoder} ({label}) = {fps:.1f} fps ({elapsed:.2f}s)")
            return (encoder, label, fps)
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return None
    finally:
        try:
            if os.path.isfile(test_path):
                os.remove(test_path)
        except Exception:
            pass


def detect_best_encoder() -> str:
    global _BEST_ENCODER_CACHE
    if _BEST_ENCODER_CACHE:
        return _BEST_ENCODER_CACHE

    ffmpeg = _find_ffmpeg()[0]
    candidates = []
    bench_results: list[tuple[str, str, float]] = []

    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, timeout=15, text=True,
        )
        available = proc.stdout + proc.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        available = ""

    encoder_priorities = [
        ("av1_nvenc", "AV1 NVENC"),
        ("h264_nvenc", "NVIDIA NVENC"),
        ("av1_qsv", "Intel AV1 QSV"),
        ("h264_qsv", "Intel QSV"),
        ("h264_amf", "AMD AMF"),
    ]

    for enc_name, label in encoder_priorities:
        if enc_name in available:
            try:
                if not _verify_encoder(ffmpeg, enc_name):
                    continue
                bench = _benchmark_encoder(ffmpeg, enc_name, label)
                if bench:
                    bench_results.append(bench)
                    candidates.append((enc_name, label))
                    logger.info(f"Encoder available: {label} ({enc_name}) — {bench[2]:.1f} fps")
                elif _verify_encoder(ffmpeg, enc_name):
                    candidates.append((enc_name, label))
                    logger.info(f"Encoder available: {label} ({enc_name}) — verified")
            except Exception:
                pass

    if bench_results:
        bench_results.sort(key=lambda x: x[2], reverse=True)
        encoder, name, fps = bench_results[0]
        logger.info(f"FFmpeg encoder: {name} ({encoder}) @ {fps:.1f} fps (benchmarked)")
    elif candidates:
        encoder, name = candidates[0]
        logger.info(f"FFmpeg encoder: {name} ({encoder})")
    else:
        encoder = "libx264"
        name = "software (libx264)"
        logger.info("FFmpeg encoder: no HW acceleration found, using libx264")

    _BEST_ENCODER_CACHE = encoder

    try:
        from mindmargin.analytics.monitoring import record_event
        record_event("encoder_selection", encoder, 1,
                     metadata={"encoder": encoder, "name": name})
    except Exception:
        pass

    return encoder


def ffmpeg_available() -> bool:
    cmd = _find_ffmpeg()
    try:
        subprocess.run(cmd + ["-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run(cmd: list[str], desc: str = "", timeout: int = 3600,
        cwd: str | None = None, retries: int = 2) -> tuple[bool, str]:
    """Run FFmpeg with automatic retry and configurable timeout.
    
    Returns (ok: bool, error: str).
    """
    ffmpeg_exe = _find_ffmpeg()[0]
    if not os.path.isfile(ffmpeg_exe) and ffmpeg_exe == "ffmpeg":
        if not ffmpeg_available():
            return False, "FFmpeg not found on PATH"

    cmd[0] = ffmpeg_exe
    last_error = ""

    for attempt in range(1 + retries):
        try:
            logger.info(f"FFmpeg: {desc or ' '.join(cmd[-3:])}"
                        f"{' (attempt ' + str(attempt + 1) + ')' if retries else ''}")
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=cwd)
            if proc.returncode == 0:
                return True, ""
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()[-500:]
            last_error = f"FFmpeg failed (rc={proc.returncode}): {stderr}"
            logger.warning(last_error)
            if attempt < retries:
                time.sleep(2 ** attempt)
        except subprocess.TimeoutExpired:
            last_error = f"FFmpeg timed out after {timeout}s"
            logger.error(last_error)
            return False, last_error
        except Exception as e:
            last_error = f"FFmpeg error: {e}"
            logger.error(last_error)
            if attempt < retries:
                time.sleep(2 ** attempt)

    logger.error(last_error)
    return False, last_error


def _find_ffprobe() -> str:
    for d in _FFMPEG_DIRS:
        exe = os.path.join(d, "ffprobe.exe")
        if os.path.isfile(exe):
            return exe
    return "ffprobe"


def probe_duration(path: str | Path) -> float:
    try:
        ffprobe = _find_ffprobe()
        cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
               "-of", "json", str(path)]
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


def _video_encoder_params() -> list[str]:
    encoder = detect_best_encoder()
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", str(settings.video.crf)]
    elif encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", str(settings.video.crf),
                "-rc", "vbr", "-b:v", "5M", "-maxrate", "10M"]
    elif encoder == "av1_nvenc":
        return ["-c:v", "av1_nvenc", "-preset", "p1", "-cq", str(settings.video.crf),
                "-rc", "vbr", "-b:v", "4M", "-maxrate", "8M"]
    elif encoder == "av1_qsv":
        return ["-c:v", "av1_qsv", "-preset", "veryfast", "-global_quality", str(settings.video.crf)]
    elif encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp",
                "-qp_i", str(settings.video.crf), "-qp_p", str(settings.video.crf)]
    elif encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", str(settings.video.crf)]
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", str(settings.video.crf)]


def section_video(color: str, output_path: str | Path, duration: float = 10.0,
                  text: str = "", width: int = 0, height: int = 0) -> Optional[Path]:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    w = width or settings.video.width
    h = height or settings.video.height
    fps = settings.video.fps

    if text:
        safe = text.replace("'", "").replace(":", " ").replace("\n", " ")[:200]
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d={duration}:r={fps}",
            "-vf",
            f"drawtext=text='{safe}':fontcolor=white:fontsize=32:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"shadowcolor=black:shadowx=2:shadowy=2",
            *_video_encoder_params(),
            "-pix_fmt", "yuv420p",
            str(out),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d={duration}:r={fps}",
            *_video_encoder_params(),
            "-pix_fmt", "yuv420p",
            str(out),
        ]

    ok, _ = run(cmd, desc=f"section_video: {Path(output_path).name}")
    return out if ok else None


def burn_subtitles(video_path: str | Path, srt_path: str | Path,
                   output_path: str | Path) -> Optional[Path]:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    srt_resolved = Path(srt_path).resolve()

    import shutil
    local_srt = out.parent / "subs.srt"
    shutil.copy2(str(srt_resolved), str(local_srt))

    style_opts = "FontSize=18,PrimaryColour=&HFFFFFF,BackColour=&H80000000,BorderStyle=4,Alignment=2"
    safe_style = style_opts.replace(",", "\\,")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"subtitles=subs.srt:force_style={safe_style}",
        *_video_encoder_params(),
        "-c:a", "copy",
        str(out),
    ]

    ok, _ = run(cmd, desc="burn subtitles", cwd=str(out.parent))
    return out if ok else None


def concat_videos(input_paths: list[Path], output_path: str | Path) -> Optional[Path]:
    if not input_paths:
        logger.error("concat_videos: no input paths provided")
        return None
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    import shutil, uuid, os as _os
    safe_dir = Path(_os.environ.get("TEMP", "C:\\Temp")) / f"mindmargin_concat_{uuid.uuid4().hex[:8]}"
    safe_dir.mkdir(parents=True, exist_ok=True)
    safe_paths = []
    for i, p in enumerate(input_paths):
        if p.exists():
            dst = safe_dir / f"clip_{i:03d}.mp4"
            shutil.copy2(str(p), str(dst))
            safe_paths.append(dst)

    if not safe_paths:
        logger.error("No valid input files after copy")
        return None

    filelist = safe_dir / "filelist.txt"
    with open(filelist, "w", encoding="ascii") as f:
        for p in safe_paths:
            f.write(f"file '{p.name}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", "filelist.txt",
        *_video_encoder_params(),
        "-c:a", "aac", "-b:a", settings.video.audio_bitrate,
        "-pix_fmt", "yuv420p",
        str(out),
    ]

    ok, _ = run(cmd, desc="concat videos", cwd=str(safe_dir))
    try:
        shutil.rmtree(safe_dir, ignore_errors=True)
    except OSError:
        pass
    return out if ok else None


def add_audio(video_path: str | Path, audio_path: str | Path,
              output_path: str | Path) -> Optional[Path]:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", settings.video.audio_bitrate,
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        str(out),
    ]

    ok, _ = run(cmd, desc="add audio track")
    return out if ok else None


def add_audio_and_subs(video_path: str | Path, audio_path: str | Path,
                        srt_path: str | Path, output_path: str | Path) -> Optional[Path]:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    import shutil
    local_srt = out.parent / "subs.srt"
    shutil.copy2(str(Path(srt_path).resolve()), str(local_srt))

    style_opts = "FontSize=18,PrimaryColour=&HFFFFFF,BackColour=&H80000000,BorderStyle=4,Alignment=2"
    safe_style = style_opts.replace(",", "\\,")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-filter_complex", f"[0:v]subtitles=subs.srt:force_style={safe_style}[vid]",
        "-map", "[vid]", "-map", "1:a:0",
        *_video_encoder_params(),
        "-c:a", "aac", "-b:a", settings.video.audio_bitrate,
        "-shortest",
        str(out),
    ]
    ok, _ = run(cmd, desc="add audio + subs", cwd=str(out.parent))
    return out if ok else None


def concat_audio(input_paths: list[Path], output_path: str | Path) -> Optional[Path]:
    if not input_paths:
        logger.warning("concat_audio: empty input list, generating silent track")
        return generate_silent_audio(output_path, duration=30.0)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    inputs = []
    filter_parts = []
    for i, p in enumerate(input_paths):
        inputs.extend(["-i", str(p.resolve())])
        filter_parts.append(f"[{i}:0]")
    filter_str = f"{''.join(filter_parts)}concat=n={len(input_paths)}:v=0:a=1[out]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "aac", "-b:a", settings.video.audio_bitrate,
        "-ar", "44100",
        "-ac", "2",
        str(out),
    ]

    ok, _ = run(cmd, desc="concat audio")
    return out if ok else None


def generate_silent_audio(output_path: str | Path, duration: float = 10.0) -> Optional[Path]:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={duration}",
        "-c:a", "aac", "-b:a", settings.video.audio_bitrate,
        "-ar", "44100",
        "-ac", "2",
        str(out),
    ]
    ok, _ = run(cmd, desc="silent audio")
    return out if ok else None


def generate_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = seg.get("start_s", 0)
        end = seg.get("end_s", start + 3)
        text = seg.get("text", "")
        lines.append(str(i))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(text.strip())
        lines.append("")
    return "\n".join(lines)


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
