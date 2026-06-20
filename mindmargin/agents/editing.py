import json
import logging
from pathlib import Path

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text
from mindmargin.utils import ffmpeg

logger = logging.getLogger(__name__)

SECTION_COLORS = {
    "hook":                "#1B2838",
    "rise":                "#2E4A2E",
    "first_crack":         "#4A2E2E",
    "overconfidence_loop": "#3A2E4A",
    "escalation":          "#4A3A2E",
    "collapse":            "#2E1A1A",
    "twist":               "#1A2E3A",
    "lesson":              "#2E3A2E",
    "close":               "#1B2838",
}


class EditingAgent:
    """FFmpeg-based video assembly. Produces MP4 even without external assets."""

    def __init__(self):
        self.name = "editing"

    def run(self, topic: str, pipeline_id: str, sections: list[dict],
            voice_segments: list[dict], duration_scale: float = 1.0) -> dict:
        logger.info(f"EditingAgent: assembling video for '{topic}' ({len(sections)} sections)")

        dirs = ensure_dirs(topic, pipeline_id)
        clips: list[Path] = []

        for i, sec in enumerate(sections):
            sec_id = sec["section_id"]
            name = sec["name"]
            color = SECTION_COLORS.get(name, "#1B2838")
            vs = voice_segments[i] if i < len(voice_segments) else {}
            actual_s = vs.get("actual_duration_s", 0) or 0
            max_s = sec.get("duration_target_s", 60) * duration_scale
            duration_s = max(min(actual_s, max_s) if actual_s > 0 else max_s, 4.0)

            title_text = sec["title"]
            title_dur = min(max(duration_s * 0.15, 2.0), duration_s * 0.3)
            section_dur = max(duration_s - title_dur, 1.0)

            # Title card with section name
            title_path = dirs["temp"] / f"{sec_id:02d}_{name}_title.mp4"
            title_clip = ffmpeg.section_video(
                color=color, output_path=str(title_path),
                duration=title_dur, text=title_text,
            )
            if title_clip:
                clips.append(title_clip)

            # Content section (colored background, no text overlay to avoid font issues)
            content_path = dirs["temp"] / f"{sec_id:02d}_{name}_content.mp4"
            content_clip = ffmpeg.section_video(
                color=color, output_path=str(content_path),
                duration=max(section_dur, 2.0),
            )
            if content_clip:
                clips.append(content_clip)

        logger.info(f"Generated {len(clips)} video clips")

        # Concat all clips into raw video
        raw_video = dirs["video"] / f"{pipeline_id}_raw.mp4"
        assembled = ffmpeg.concat_videos(clips, str(raw_video))

        if not assembled:
            logger.error("Video concat failed — no video produced")
            return {
                "agent": self.name, "status": "failed",
                "video_path": "", "manifest": {},
            }

        # Concat audio
        audio_paths = [Path(s["wav_path"]) for s in voice_segments if s.get("wav_path")]
        audio_file = None
        if audio_paths:
            mixed_audio = dirs["audio"] / "voiceover_full.m4a"
            audio_file = ffmpeg.concat_audio(audio_paths, str(mixed_audio))

        # Generate and burn subtitles
        srt_content = self._build_srt(sections, voice_segments)
        srt_path = dirs["captions"] / "subtitles.srt"
        write_text(srt_path, srt_content)

        # Combine audio + subtitle burn in single pass
        if audio_file:
            combined = dirs["video"] / f"{pipeline_id}_final.mp4"
            result = ffmpeg.add_audio_and_subs(assembled, audio_file, srt_path, str(combined))
            if result:
                assembled = result
        else:
            final = dirs["video"] / f"{pipeline_id}_final.mp4"
            result = ffmpeg.burn_subtitles(assembled, srt_path, str(final))
            if result:
                assembled = result

        # Probe final duration
        duration = ffmpeg.probe_duration(assembled)
        logger.info(f"Final video: {assembled} ({duration:.1f}s)")

        manifest = {
            "topic": topic,
            "pipeline_id": pipeline_id,
            "clips": [str(c) for c in clips],
            "final_video": str(assembled),
            "duration_s": round(duration, 1),
            "has_audio": audio_file is not None,
            "has_subtitles": True,
            "resolution": f"{settings.video.width}x{settings.video.height}",
            "fps": settings.video.fps,
        }
        write_text(dirs["video"] / "edit_manifest.json", json.dumps(manifest, indent=2))

        return {
            "agent": self.name,
            "status": "completed",
            "video_path": str(assembled),
            "duration_s": round(duration, 1),
            "manifest": manifest,
        }

    def _build_srt(self, sections: list[dict], voice_segments: list[dict]) -> str:
        segments = []
        current_time = 0.0

        for i, sec in enumerate(sections):
            vs = voice_segments[i] if i < len(voice_segments) else {}
            sec_id = sec["section_id"]
            name = sec["name"]
            duration_s = sec.get("duration_target_s", 60)
            title_dur = max(duration_s * 0.15, 4.0)

            # Title card subtitle
            segments.append({
                "text": sec["title"],
                "start_s": current_time,
                "end_s": current_time + title_dur,
            })
            current_time += title_dur

            # Sentence-level subtitles from voice manifest
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
