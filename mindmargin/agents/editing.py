import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text
from mindmargin.utils import ffmpeg
from mindmargin.agents.script import validate_scene_plan

logger = logging.getLogger(__name__)

SECTION_COLORS = {
    "hook":                "#1B2838",
    "context":             "#2E4A2E",
    "historical_background": "#4A2E2E",
    "growth_story":        "#3A2E4A",
    "critical_decisions":  "#4A3A2E",
    "main_mistakes":       "#4A2E1A",
    "collapse":            "#2E1A1A",
    "consequences":        "#1A2E3A",
    "lessons_learned":     "#2E3A2E",
    "closing":             "#1B2838",
    # Legacy section names for backward compatibility
    "rise":                "#2E4A2E",
    "first_crack":         "#4A2E2E",
    "overconfidence_loop": "#3A2E4A",
    "escalation":          "#4A3A2E",
    "twist":               "#1A2E3A",
    "lesson":              "#2E3A2E",
    "close":               "#1B2838",
}

MAX_PARALLEL_SECTIONS = settings.production.max_parallel_sections


class EditingAgent:
    """Resumable, parallel, profiled FFmpeg video assembler."""

    def __init__(self, editing_timeout: Optional[int] = None, force: bool = False):
        self.name = "editing"
        self.editing_timeout = editing_timeout
        self.force = force
        self.profile: dict[str, object] = {"stages": {}}

    # ── Public entry ──

    def run(self, topic: str, pipeline_id: str, sections: list[dict],
            voice_segments: list[dict], duration_scale: float = 1.0) -> dict:
        logger.info(f"EditingAgent: assembling video for '{topic}' ({len(sections)} sections)")
        p_start = time.time()

        dirs = ensure_dirs(topic, pipeline_id)
        progress = self._load_progress(pipeline_id)

        clips: list[Path] = []

        # Stage 1: render all section clips (parallel + resumable)
        self._profile_stage("section_rendering")
        clips = self._render_sections(pipeline_id, sections, voice_segments,
                                       duration_scale, dirs, progress)
        self._profile_stage_end("section_rendering", len(clips))

        if clips is None:
            return self._error("section rendering failed", dirs)

        # Stage 2: concat all clips into raw video
        self._profile_stage("concat_video")
        raw_video = self._concat_video(clips, pipeline_id, dirs, progress)
        if not raw_video:
            return self._error("concat_video failed", dirs)
        self._profile_stage_end("concat_video")

        # Audio concat
        self._profile_stage("concat_audio")
        audio_file = self._concat_audio(voice_segments, dirs)
        self._profile_stage_end("concat_audio")

        # Generate subtitles
        self._profile_stage("subtitles")
        srt_path = self._generate_subtitles(sections, voice_segments, dirs)
        self._profile_stage_end("subtitles")

        # Final merge (audio + subs)
        self._profile_stage("final_merge")
        final = self._final_merge(raw_video, audio_file, srt_path, pipeline_id, dirs, progress)
        if not final:
            return self._error("final merge failed", dirs)
        self._profile_stage_end("final_merge")

        # Probe final duration
        duration = ffmpeg.probe_duration(final)

        # Write manifest
        manifest = self._write_manifest(topic, pipeline_id, clips, final, duration, audio_file)
        self._write_profile(pipeline_id, dirs, p_start)

        logger.info(f"Final video: {final} ({duration:.1f}s)")
        return {
            "agent": self.name,
            "status": "completed",
            "video_path": str(final),
            "duration_s": round(duration, 1),
            "manifest": manifest,
        }

    # ── Stage 2: parallel section rendering ──

    def _render_sections(self, pipeline_id: str, sections: list[dict],
                          voice_segments: list[dict], duration_scale: float,
                          dirs: dict, progress: dict) -> Optional[list[Path]]:
        """Render all section clips in parallel, skipping completed. Returns clip list or None on fatal error."""
        progress_entry = progress.setdefault("sections", {})
        clip_order: list[tuple[int, str]] = []  # (index, clip_key) ordered
        tasks: list[tuple[str, dict, Path, float]] = []  # (clip_key, params)

        for i, sec in enumerate(sections):
            sec_id = sec["section_id"]
            name = sec["name"]
            color = SECTION_COLORS.get(name, "#1B2838")
            vs = voice_segments[i] if i < len(voice_segments) else {}
            actual_s = vs.get("actual_duration_s", 0) or 0
            max_s = sec.get("duration_target_s", 60) * duration_scale
            duration_s = max(min(actual_s, max_s) if actual_s > 0 else max_s, 4.0)

            # Use scene_plan to vary visual presentation if available
            scene_plan = sec.get("scene_plan", [])
            if scene_plan:
                clean_plan, reason = validate_scene_plan(scene_plan)
                if reason:
                    logger.warning(
                        f"[defense] section '{sec['name']}' invalid scene_plan: {reason}"
                    )
                    scene_plan = [{
                        "scene_description": f"Fallback for {sec['name']}",
                        "broll_suggestion": "Generic footage",
                        "footage_keywords": [sec["name"], "documentary"],
                        "camera_movement": "static",
                        "on_screen_text": "",
                        "visual_elements": [],
                        "duration_s": sec.get("duration_target_s", 60) // 3,
                        "emotion": "neutral",
                    }]
                else:
                    scene_plan = clean_plan
            first_scene = scene_plan[0] if scene_plan else {}
            on_screen_text = first_scene.get("on_screen_text", "")
            emotion = first_scene.get("emotion", "neutral")

            title_text = sec["title"]
            title_dur = min(max(duration_s * 0.15, 2.0), duration_s * 0.3)
            section_dur = max(duration_s - title_dur, 1.0)

            # Title card — use on_screen_text from scene_plan if available
            title_path = dirs["temp"] / f"{sec_id:02d}_{name}_title.mp4"
            title_key = f"{sec_id:02d}_{name}_title"
            clip_order.append((i * 2, title_key))
            if self._should_render(pipeline_id, title_key, progress_entry):
                display_text = on_screen_text if on_screen_text else title_text
                tasks.append((title_key, {
                    "color": color, "output_path": str(title_path),
                    "duration": title_dur, "text": display_text,
                }))
            else:
                logger.debug(f"Skip existing: {title_key}")

            # Content clip
            content_path = dirs["temp"] / f"{sec_id:02d}_{name}_content.mp4"
            content_key = f"{sec_id:02d}_{name}_content"
            clip_order.append((i * 2 + 1, content_key))
            if self._should_render(pipeline_id, content_key, progress_entry):
                tasks.append((content_key, {
                    "color": color, "output_path": str(content_path),
                    "duration": max(section_dur, 2.0),
                }))
            else:
                logger.debug(f"Skip existing: {content_key}")

        # Render tasks in parallel
        if tasks:
            ok = self._render_parallel(tasks, pipeline_id, progress_entry)
            if not ok:
                return None

        # Build ordered clip list from filesystem (all should exist now)
        clips: list[Path] = []
        for _, clip_key in sorted(clip_order, key=lambda x: x[0]):
            # Reconstruct path from the clip_key
            p = dirs["temp"] / f"{clip_key}.mp4"
            if p.exists():
                clips.append(p)
            else:
                logger.warning(f"Clip missing after render: {clip_key}")

        if not clips:
            logger.error("No clips rendered")
            return None

        logger.info(f"Rendered {len(clips)} clips ({len(tasks)} freshly rendered, "
                    f"{len(clip_order) - len(tasks)} cached)")
        return clips

    def _should_render(self, pipeline_id: str, clip_key: str,
                       progress_entry: dict) -> bool:
        """Check if a clip needs rendering. Returns True if render needed."""
        if self.force:
            return True
        entry = progress_entry.get(clip_key, {})
        if entry.get("status") == "completed" and entry.get("path"):
            p = Path(entry["path"])
            if p.exists() and p.stat().st_size > 0:
                return False
        return True

    def _render_parallel(self, tasks: list[tuple[str, dict]], pipeline_id: str,
                          progress_entry: dict) -> bool:
        """Render multiple clips in parallel threads."""
        total = len(tasks)
        completed = 0
        errors = 0
        r_start = time.time()

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SECTIONS) as executor:
            fut_map = {}
            for clip_key, params in tasks:
                fut = executor.submit(self._render_single_clip, clip_key, params)
                fut_map[fut] = clip_key

            for fut in as_completed(fut_map):
                clip_key = fut_map[fut]
                try:
                    ok, path = fut.result()
                    completed += 1
                    if ok:
                        progress_entry[clip_key] = {"status": "completed", "path": path}
                        self._save_progress(pipeline_id, {"sections": progress_entry})
                    else:
                        errors += 1
                        progress_entry[clip_key] = {"status": "failed"}
                except Exception as e:
                    errors += 1
                    logger.error(f"Clip render error {clip_key}: {e}")
                    progress_entry[clip_key] = {"status": "failed", "error": str(e)}

                elapsed = time.time() - r_start
                pct = int((completed / total) * 100)
                est_total = elapsed / max(completed, 1) * total
                rem = max(est_total - elapsed, 0)
                logger.info(f"Editing  [{('#' * (pct // 5)).ljust(20)}] {pct}%  "
                           f"Rendering: {Path(path).name if 'path' in vars() and path else clip_key}.mp4  "
                           f"Elapsed: {int(elapsed // 60)}m {int(elapsed % 60)}s  "
                           f"Remaining: {int(rem // 60)}m {int(rem % 60)}s")

        if errors > 0:
            logger.warning(f"Section rendering: {errors}/{total} clips failed")
        return errors < total  # partial success is acceptable

    def _render_single_clip(self, clip_key: str, params: dict) -> tuple[bool, str]:
        """Render a single clip. Returns (ok, path)."""
        out_path = params["output_path"]
        kwargs = {k: v for k, v in params.items() if k != "output_path"}
        result = ffmpeg.section_video(**kwargs, output_path=out_path)
        if result:
            return True, str(result)
        return False, out_path

    # ── Stage 2: concat video ──

    def _concat_video(self, clips: list[Path], pipeline_id: str,
                       dirs: dict, progress: dict) -> Optional[Path]:
        progress_entry = progress.setdefault("concat_video", {})
        if progress_entry.get("status") == "completed" and not self.force:
            path = progress_entry.get("path", "")
            if path and Path(path).exists():
                logger.info("Skip concat_video (already completed)")
                return Path(path)

        raw_video = dirs["video"] / f"{pipeline_id}_raw.mp4"
        result = ffmpeg.concat_videos(clips, str(raw_video))
        if result:
            progress_entry["status"] = "completed"
            progress_entry["path"] = str(result)
            self._save_progress(pipeline_id, {"concat_video": progress_entry})
        return result

    # ── Stage 3: concat audio ──

    def _concat_audio(self, voice_segments: list[dict], dirs: dict) -> Optional[Path]:
        audio_paths = [Path(s["wav_path"]) for s in voice_segments if s.get("wav_path")]
        if not audio_paths:
            return None
        mixed_audio = dirs["audio"] / "voiceover_full.m4a"
        return ffmpeg.concat_audio(audio_paths, str(mixed_audio))

    # ── Stage 4: subtitles ──

    def _generate_subtitles(self, sections: list[dict], voice_segments: list[dict],
                             dirs: dict) -> Path:
        srt_content = self._build_srt(sections, voice_segments)
        srt_path = dirs["captions"] / "subtitles.srt"
        write_text(srt_path, srt_content)
        logger.info(f"Subtitles: {srt_path}")
        return srt_path

    # ── Stage 5: final merge ──

    def _final_merge(self, raw_video: Path, audio_file: Optional[Path],
                      srt_path: Path, pipeline_id: str,
                      dirs: dict, progress: dict) -> Optional[Path]:
        progress_entry = progress.setdefault("final_merge", {})
        if progress_entry.get("status") == "completed" and not self.force:
            path = progress_entry.get("path", "")
            if path and Path(path).exists():
                logger.info("Skip final_merge (already completed)")
                return Path(path)

        final = dirs["video"] / f"{pipeline_id}_final.mp4"
        if audio_file:
            result = ffmpeg.add_audio_and_subs(raw_video, audio_file, srt_path, str(final))
        else:
            result = ffmpeg.burn_subtitles(raw_video, srt_path, str(final))

        if result:
            progress_entry["status"] = "completed"
            progress_entry["path"] = str(result)
            self._save_progress(pipeline_id, {"final_merge": progress_entry})
        return result

    # ── Progress persistence ──

    def _progress_path(self, pipeline_id: str) -> Path:
        from mindmargin.core.storage import _safe_base
        base = _safe_base()
        return base / "editing_progress" / f"{pipeline_id}.json"

    def _load_progress(self, pipeline_id: str) -> dict:
        path = self._progress_path(pipeline_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                logger.info(f"Editing progress loaded: {path}")
                return data
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Corrupt editing progress: {e}")
        return {}

    def _save_progress(self, pipeline_id: str, updates: dict):
        path = self._progress_path(pipeline_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._load_progress(pipeline_id)
        existing.update(updates)
        path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

    # ── Profile ──

    def _profile_stage(self, name: str):
        self._current_stage = name
        self._stage_start = time.time()

    def _profile_stage_end(self, name: str, extra: object = None):
        elapsed = time.time() - self._stage_start
        entry: dict[str, object] = {"duration_s": round(elapsed, 2)}
        if extra is not None:
            entry["count"] = extra
        self.profile["stages"][name] = entry
        logger.info(f"Editing stage '{name}': {elapsed:.2f}s")

    def _write_profile(self, pipeline_id: str, dirs: dict, p_start: float):
        self.profile["total_duration_s"] = round(time.time() - p_start, 2)
        self.profile["encoder"] = ffmpeg.detect_best_encoder()
        self.profile["pipeline_id"] = pipeline_id
        self.profile["completed_at"] = datetime.utcnow().isoformat()
        profile_path = dirs["video"] / "editing_profile.json"
        write_text(profile_path, json.dumps(self.profile, indent=2))
        logger.info(f"Editing profile: {profile_path}")

    def _write_manifest(self, topic: str, pipeline_id: str, clips: list[Path],
                         final: Path, duration: float, audio_file: Optional[Path]) -> dict:
        manifest = {
            "topic": topic,
            "pipeline_id": pipeline_id,
            "clips": [str(c) for c in clips],
            "final_video": str(final),
            "duration_s": round(duration, 1),
            "has_audio": audio_file is not None,
            "has_subtitles": True,
            "resolution": f"{settings.video.width}x{settings.video.height}",
            "fps": settings.video.fps,
        }
        manifest_path = Path(final).parent / "edit_manifest.json"
        write_text(manifest_path, json.dumps(manifest, indent=2))
        return manifest

    def _error(self, msg: str, dirs: dict) -> dict:
        logger.error(msg)
        return {"agent": self.name, "status": "failed", "error": msg, "video_path": ""}

    # ── SRT builder ──

    def _build_srt(self, sections: list[dict], voice_segments: list[dict]) -> str:
        segments = []
        current_time = 0.0

        for i, sec in enumerate(sections):
            vs = voice_segments[i] if i < len(voice_segments) else {}
            sec_id = sec["section_id"]
            name = sec["name"]
            duration_s = sec.get("duration_target_s", 60)
            title_dur = max(duration_s * 0.15, 4.0)

            segments.append({
                "text": sec["title"],
                "start_s": current_time,
                "end_s": current_time + title_dur,
            })
            current_time += title_dur

            sentences = vs.get("sentences", [])
            if sentences:
                for sent in sentences:
                    sdur = sent.get("duration_s", 2.0)
                    segments.append({
                        "text": sent["text"],
                        "start_s": current_time,
                        "end_s": current_time + sdur,
                    })
                    current_time += sdur
            else:
                words = sec["text"].split()
                chunk_size = 12
                for i in range(0, len(words), chunk_size):
                    chunk = " ".join(words[i:i + chunk_size])
                    chunk_dur = max(len(chunk.split()) / 2.8, 2.0)
                    segments.append({
                        "text": chunk,
                        "start_s": current_time,
                        "end_s": current_time + chunk_dur,
                    })
                    current_time += chunk_dur

        return ffmpeg.generate_srt(segments)
