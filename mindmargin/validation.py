import json
import logging
from pathlib import Path

from mindmargin.utils.ffmpeg import probe_duration

logger = logging.getLogger(__name__)


def verify_pipeline_output(pipeline_dir: str | Path) -> dict:
    """Verify all outputs from an MVP pipeline run. Returns check results."""
    base = Path(pipeline_dir)
    results = {
        "pipeline_dir": str(base),
        "exists": base.exists(),
        "checks": [],
        "all_passed": False,
        "errors": [],
    }

    if not base.exists():
        results["errors"].append(f"Pipeline directory not found: {base}")
        return results

    checks = []

    # 1. Research outputs
    research_dir = base / "research"
    trend_file = research_dir / "trend_score.json"
    research_file = research_dir / "research_data.json"
    trend_ok = trend_file.exists() and trend_file.stat().st_size > 50
    research_ok = research_file.exists() and research_file.stat().st_size > 50
    checks.append({
        "check": "research_trend_score",
        "passed": trend_ok,
        "detail": "trend_score.json exists and non-empty" if trend_ok else "MISSING or empty",
    })
    checks.append({
        "check": "research_data",
        "passed": research_ok,
        "detail": "research_data.json exists and non-empty" if research_ok else "MISSING or empty",
    })

    # 2. Script outputs
    script_dir = base / "script"
    script_file = script_dir / "script.json"
    script_txt = script_dir / "full_script.txt"
    script_ok = script_file.exists() and script_file.stat().st_size > 100
    script_txt_ok = script_txt.exists() and script_txt.stat().st_size > 100
    checks.append({
        "check": "script_json",
        "passed": script_ok,
        "detail": "script.json exists and non-empty" if script_ok else "MISSING or empty",
    })
    checks.append({
        "check": "script_full_text",
        "passed": script_txt_ok,
        "detail": f"full_script.txt exists ({script_txt.stat().st_size}B)" if script_txt_ok else "MISSING",
    })

    # Read word count
    wc = 0
    if script_txt_ok:
        wc = len(script_txt.read_text(encoding="utf-8").split())
    checks.append({
        "check": "script_word_count",
        "passed": wc >= 100,
        "detail": f"{wc} words" if wc >= 100 else f"Only {wc} words (need >=100)",
    })

    # 3. Audio outputs
    audio_dir = base / "audio"
    wav_files = sorted(audio_dir.glob("*.wav")) if audio_dir.exists() else []
    audio_manifest = audio_dir / "voice_manifest.json"
    checks.append({
        "check": "audio_wav_count",
        "passed": len(wav_files) >= 9,
        "detail": f"{len(wav_files)} WAV files found (expected >=9)",
    })
    if wav_files:
        total_wav_size = sum(f.stat().st_size for f in wav_files)
        # Silent WAVs are ~88KB, real Piper is larger, anything >0 is fine
        checks.append({
            "check": "audio_nonzero",
            "passed": total_wav_size > 0,
            "detail": f"{total_wav_size / 1024:.1f} KB total audio",
        })
    checks.append({
        "check": "audio_manifest",
        "passed": audio_manifest.exists(),
        "detail": "voice_manifest.json exists" if audio_manifest.exists() else "MISSING",
    })

    # 4. Subtitle outputs
    srt_file = base / "captions" / "subtitles.srt"
    srt_ok = srt_file.exists() and srt_file.stat().st_size > 50
    if srt_ok:
        srt_lines = srt_file.read_text(encoding="utf-8").strip().split("\n")
        srt_entries = sum(1 for l in srt_lines if "-->" in l)
    checks.append({
        "check": "subtitles_exist",
        "passed": srt_ok,
        "detail": f"subtitles.srt exists ({srt_entries} entries)" if srt_ok else "MISSING",
    })

    # 5. Video output
    video_dir = base / "video"
    final_candidates = list(video_dir.glob("*_final.mp4")) if video_dir.exists() else []
    manifest_file = video_dir / "edit_manifest.json"

    if final_candidates:
        final_video = final_candidates[0]
        duration = probe_duration(final_video)
        video_size = final_video.stat().st_size
        checks.append({
            "check": "mp4_exists",
            "passed": True,
            "detail": f"Final MP4: {final_video.name} ({video_size / 1024:.1f} KB)",
        })
        checks.append({
            "check": "mp4_duration",
            "passed": duration > 1.0,
            "detail": f"Duration: {duration:.1f}s" if duration > 1.0 else f"Too short: {duration:.1f}s",
        })
    else:
        checks.append({
            "check": "mp4_exists",
            "passed": False,
            "detail": "No *_final.mp4 found in video/ directory",
        })
        checks.append({
            "check": "mp4_duration",
            "passed": False,
            "detail": "No video to measure",
        })

    checks.append({
        "check": "edit_manifest",
        "passed": manifest_file.exists(),
        "detail": "edit_manifest.json exists" if manifest_file.exists() else "MISSING",
    })

    results["checks"] = checks
    results["all_passed"] = all(c["passed"] for c in checks)
    results["pass_rate"] = f"{sum(1 for c in checks if c['passed'])}/{len(checks)}"
    return results


def print_validation(results: dict):
    """Pretty-print validation results."""
    status = "PASS" if results["all_passed"] else "FAIL"
    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  OUTPUT VALIDATION: {status}  ({results.get('pass_rate', '?')} checks passed)")
    print(bar)
    for c in results.get("checks", []):
        mark = "OK" if c["passed"] else "XX"
        print(f"  [{mark}] {c['check']:25s} {c['detail']}")
    if results.get("errors"):
        print(f"  Errors: {len(results['errors'])}")
        for e in results["errors"]:
            print(f"    - {e}")
    print(bar)
