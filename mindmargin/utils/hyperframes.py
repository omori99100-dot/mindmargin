"""HyperFrames composition layer — animated titles, transitions, lower thirds."""

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

SECTION_COLORS = {
    "hook": "#1B2838", "context": "#2E4A2E", "historical_background": "#4A2E2E",
    "growth_story": "#3A2E4A", "critical_decisions": "#4A3A2E",
    "main_mistakes": "#4A2E1A", "collapse": "#2E1A1A", "consequences": "#1A2E3A",
    "lessons_learned": "#2E3A2E", "closing": "#1B2838",
    "rise": "#2E4A2E", "first_crack": "#4A2E2E", "overconfidence_loop": "#3A2E4A",
    "escalation": "#4A3A2E", "twist": "#1A2E3A", "lesson": "#2E3A2E", "close": "#1B2838",
}

TRANSITION_MOOD = {
    "neutral": "blur",
    "informative": "blur",
    "calm": "blur",
    "peaceful": "blur",
    "dramatic": "push",
    "tense": "push",
    "exciting": "scale",
    "energetic": "scale",
    "sad": "blur",
    "hopeful": "blur",
}


def hyperframes_available() -> bool:
    try:
        npx = os.path.join(os.environ.get("PROGRAMFILES", ""), "nodejs", "npx.cmd")
        if not os.path.isfile(npx):
            npx = "npx.cmd"
        proc = subprocess.run(
            [npx, "--yes", "hyperframes", "--version"],
            capture_output=True, timeout=120, text=True,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        logger.warning(f"HyperFrames not available: {e}")
        return False


def _find_npx() -> str:
    """Find npx.cmd on Windows or npx on Unix."""
    npx = "npx"
    if os.name == "nt":
        candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "nodejs", "npx.cmd"),
            os.path.join(os.environ.get("PROGRAMFILES(x86)", ""), "nodejs", "npx.cmd"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        npx = "npx.cmd"
    return npx


def render_full_composition(
    sections: list[dict],
    voice_segments: list[dict],
    duration_scale: float,
    output_path: str | Path,
    work_dir: str | Path,
) -> Optional[Path]:
    """Render a single HyperFrames composition for the entire video."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Build section timing
    section_timings = _compute_section_timing(sections, voice_segments, duration_scale)
    total_duration = sum(s["duration_s"] for s in section_timings)

    # Generate HTML
    html = _build_composition_html(section_timings, total_duration)
    html_path = work / "index.html"
    html_path.write_text(html, encoding="utf-8")

    # Render via CLI (run from the composition directory)
    logger.info(f"HyperFrames: rendering {len(section_timings)} scenes ({total_duration:.1f}s total)")
    start = time.time()

    npx = _find_npx()
    cmd = [
        npx, "hyperframes", "render",
        "--quality", "high",
        "--output", str(out.resolve()),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=3600, text=True, cwd=str(work))
        elapsed = time.time() - start
        if proc.returncode != 0:
            stderr = proc.stderr[-500:] if proc.stderr else ""
            logger.warning(f"HyperFrames render failed (rc={proc.returncode}): {stderr}")
            return None
        if not out.exists() or out.stat().st_size == 0:
            logger.warning("HyperFrames render produced no output")
            return None
        logger.info(f"HyperFrames render: {elapsed:.1f}s → {out}")
        return out
    except subprocess.TimeoutExpired:
        logger.error("HyperFrames render timed out after 3600s")
        return None
    except Exception as e:
        logger.warning(f"HyperFrames render error: {e}")
        return None


def _compute_section_timing(
    sections: list[dict],
    voice_segments: list[dict],
    duration_scale: float,
) -> list[dict]:
    """Compute per-section timing with offset, title window, content window."""
    result = []
    offset = 0.0
    for i, sec in enumerate(sections):
        vs = voice_segments[i] if i < len(voice_segments) else {}
        actual_s = vs.get("actual_duration_s", 0) or 0
        max_s = sec.get("duration_target_s", 60) * duration_scale
        duration_s = max(min(actual_s, max_s) if actual_s > 0 else max_s, 4.0)
        title_dur = min(max(duration_s * 0.15, 2.0), duration_s * 0.3)
        section_dur = max(duration_s - title_dur, 1.0)

        scene_plan = sec.get("scene_plan", [])
        first_scene = scene_plan[0] if scene_plan else {}
        emotion = first_scene.get("emotion", "neutral")
        on_screen_text = first_scene.get("on_screen_text", "")
        display_text = on_screen_text if on_screen_text else sec["title"]

        result.append({
            "index": i,
            "section_id": sec["section_id"],
            "name": sec["name"],
            "title": sec["title"],
            "display_text": display_text,
            "color": SECTION_COLORS.get(sec["name"], "#1B2838"),
            "emotion": emotion,
            "duration_s": duration_s,
            "title_dur": title_dur,
            "section_dur": section_dur,
            "offset": offset,
        })
        offset += duration_s
    return result


def _build_composition_html(section_timings: list[dict], total_duration: float) -> str:
    w = settings.video.width
    h = settings.video.height
    scenes_html = ""
    timeline_js = ""
    transition_t = 0.0

    transition_duration = 0.4  # seconds

    for i, sec in enumerate(section_timings):
        scene_id = f"scene{i}"
        offset = sec["offset"]
        dur = sec["duration_s"]
        bg = sec["color"]
        title_text = sec["display_text"]
        section_name = sec["name"].replace("_", " ").title()
        emotion = sec["emotion"]
        mood = TRANSITION_MOOD.get(emotion, "blur")

        # Scene div
        opacity_style = "opacity: 0;" if i > 0 else ""
        z_index = i + 1
        scenes_html += f"""
<div id="{scene_id}" class="scene" style="background: {bg}; z-index: {z_index}; {opacity_style}">
  <div class="title-group">
    <h1 id="{scene_id}-title">{_escape_html(title_text)}</h1>
    <div id="{scene_id}-accent" class="accent-line"></div>
  </div>
  <div id="{scene_id}-lower" class="lower-third">{_escape_html(section_name)}</div>
</div>"""

        # Animation timeline for this scene
        title_enter_t = offset + 0.2
        lower_t = offset + min(2.0, dur * 0.15)
        scene_exit_t = offset + dur - transition_duration

        timeline_js += f"""
  // Scene {i}: {sec["title"]}
  tl.fromTo("#{scene_id}-title", {{ y: 48, opacity: 0 }}, {{ y: 0, opacity: 1, duration: 0.6, ease: "power3.out" }}, {title_enter_t});
  tl.fromTo("#{scene_id}-accent", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.4, ease: "power2.out" }}, {title_enter_t + 0.1});
  tl.to("#{scene_id}-lower", {{ opacity: 1, duration: 0.4, ease: "power1.out" }}, {lower_t});

  // Hold until exit
  tl.to("#{scene_id}-lower", {{ opacity: 0.3, duration: 0.6, ease: "sine.inOut" }}, {offset + dur * 0.6});"""

        # Transition to next scene
        if i < len(section_timings) - 1:
            next_scene = f"scene{i+1}"
            scene_exit_start = offset + dur - transition_duration

            if mood == "blur":
                timeline_js += f"""
  // Transition {i} → {i+1} (blur crossfade)
  tl.to("#{scene_id}", {{ filter: "blur(12px)", opacity: 0.6, duration: {transition_duration}, ease: "power2.in" }}, {scene_exit_start});
  tl.to("#{next_scene}", {{ opacity: 1, filter: "blur(0px)", duration: {transition_duration}, ease: "power2.out" }}, {scene_exit_start});"""
            elif mood == "push":
                timeline_js += f"""
  // Transition {i} → {i+1} (push slide)
  tl.to("#{scene_id}", {{ xPercent: -100, filter: "blur(4px)", duration: {transition_duration}, ease: "power3.in" }}, {scene_exit_start});
  tl.fromTo("#{next_scene}", {{ xPercent: 100, opacity: 1 }}, {{ xPercent: 0, duration: {transition_duration}, ease: "power3.out" }}, {scene_exit_start});"""
            else:  # scale zoom
                timeline_js += f"""
  // Transition {i} → {i+1} (scale zoom)
  tl.to("#{scene_id}", {{ scale: 1.15, opacity: 0, duration: {transition_duration}, ease: "power3.in" }}, {scene_exit_start});
  tl.fromTo("#{next_scene}", {{ scale: 0.85, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: {transition_duration}, ease: "power3.out" }}, {scene_exit_start});"""
        else:
            # Final scene: gentle fade out
            timeline_js += f"""
  // Final fade out
  tl.to("#{scene_id}", {{ opacity: 0, duration: 0.6, ease: "power1.in" }}, {offset + dur - 0.6});"""

        transition_t = offset + dur

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={w}, height={h}" />
<title>MindMargin Composition</title>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
  body {{ margin: 0; width: {w}px; height: {h}px; overflow: hidden; background: #000; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }}
  #root {{ position: relative; width: {w}px; height: {h}px; overflow: hidden; }}
  .scene {{ position: absolute; top: 0; left: 0; width: {w}px; height: {h}px; overflow: hidden; }}
  .title-group {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; width: 80%; }}
  .title-group h1 {{ font-size: 72px; color: #fff; margin: 0; line-height: 1.2; text-shadow: 0 2px 12px rgba(0,0,0,0.4); font-weight: 700; }}
  .accent-line {{ width: 120px; height: 4px; background: rgba(255,255,255,0.6); margin: 24px auto 0; border-radius: 2px; }}
  .lower-third {{ position: absolute; bottom: 60px; left: 60px; font-size: 22px; color: rgba(255,255,255,0.5); opacity: 0; letter-spacing: 1px; text-transform: uppercase; }}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-width="{w}" data-height="{h}" data-duration="{total_duration:.1f}">
{scenes_html}
</div>
<script>
  window.__timelines = window.__timelines || {{}};
  var tl = gsap.timeline({{ paused: true }});
{timeline_js}
  window.__timelines["main"] = tl;
</script>
</body>
</html>"""
    return html


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
