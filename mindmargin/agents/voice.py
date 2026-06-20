import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text
from mindmargin.integrations.piper import generate_wav
from mindmargin.utils.ffmpeg import probe_duration

logger = logging.getLogger(__name__)

TONE_MAP = {
    "hook":               {"speed": 1.05, "length_scale": 0.95, "noise_scale": 0.60, "noise_w": 0.7},
    "rise":               {"speed": 1.00, "length_scale": 1.00, "noise_scale": 0.67, "noise_w": 0.8},
    "first_crack":        {"speed": 0.98, "length_scale": 1.05, "noise_scale": 0.70, "noise_w": 0.8},
    "overconfidence_loop":{"speed": 0.95, "length_scale": 1.10, "noise_scale": 0.75, "noise_w": 0.8},
    "escalation":         {"speed": 0.97, "length_scale": 1.08, "noise_scale": 0.72, "noise_w": 0.8},
    "collapse":           {"speed": 0.93, "length_scale": 1.15, "noise_scale": 0.80, "noise_w": 0.9},
    "twist":              {"speed": 0.90, "length_scale": 1.20, "noise_scale": 0.85, "noise_w": 0.9},
    "lesson":             {"speed": 0.98, "length_scale": 1.02, "noise_scale": 0.70, "noise_w": 0.8},
    "close":              {"speed": 0.95, "length_scale": 1.05, "noise_scale": 0.75, "noise_w": 0.8},
}


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip()]


class VoiceAgent:
    """Per-section Piper TTS with parallel WAV generation and sentence-level timing."""

    def __init__(self):
        self.name = "voice"

    def run(self, topic: str, pipeline_id: str, sections: list[dict]) -> dict:
        logger.info(f"VoiceAgent: generating voiceover for '{topic}' ({len(sections)} sections)")

        dirs = ensure_dirs(topic, pipeline_id)

        # Phase 5B: parallel WAV generation using ThreadPoolExecutor
        max_workers = min(len(sections), os.cpu_count() or 4)
        logger.info(f"VoiceAgent: parallel WAV generation with {max_workers} workers")
        wav_results: dict[int, tuple[dict, Path, dict]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for sec in sections:
                name = sec["name"]
                text = sec["text"]
                tone = TONE_MAP.get(name, TONE_MAP["hook"])
                sec_id = sec["section_id"]
                wc = len(text.split())
                wav_path = dirs["audio"] / f"{sec_id:02d}_{name}.wav"
                estimated_s = max(wc / 2.8, 10)

                future = executor.submit(
                    generate_wav,
                    text=text,
                    output_path=str(wav_path),
                    length_scale=tone["length_scale"],
                    noise_scale=tone["noise_scale"],
                    noise_w=tone["noise_w"],
                    duration_s=estimated_s,
                )
                futures[future] = (sec_id, name, text, wc, estimated_s, wav_path, tone)

            for future in as_completed(futures):
                sec_id, name, text, wc, estimated_s, wav_path, tone = futures[future]
                try:
                    result = future.result()
                    actual_s = probe_duration(wav_path) if result and wav_path.exists() else estimated_s
                    wav_results[sec_id] = (text, wc, estimated_s, actual_s, wav_path, tone)
                except Exception as e:
                    logger.error(f"VoiceAgent: section {sec_id} ({name}) failed: {e}")
                    wav_results[sec_id] = (text, wc, estimated_s, estimated_s, wav_path, TONE_MAP["hook"])

        # Build segments in original section order
        segments = []
        for sec in sections:
            sec_id = sec["section_id"]
            name = sec["name"]
            text, wc, estimated_s, actual_s, wav_path, tone = wav_results.get(
                sec_id,
                (sec["text"], len(sec["text"].split()), 10, 10, None, TONE_MAP["hook"]),
            )

            actual_s = float(actual_s) if actual_s else estimated_s

            sentences = _split_sentences(text)
            sent_info = []
            cum = 0.0
            for sent in sentences:
                swc = len(sent.split())
                sdur = (actual_s * swc / max(wc, 1)) if swc > 0 else 1.0
                sent_info.append({
                    "text": sent,
                    "words": swc,
                    "start_s": round(cum, 2),
                    "end_s": round(cum + sdur, 2),
                    "duration_s": round(sdur, 2),
                })
                cum += sdur

            segments.append({
                "section_id": sec_id,
                "name": name,
                "word_count": wc,
                "estimated_duration_s": estimated_s,
                "actual_duration_s": round(actual_s, 2),
                "wav_path": str(wav_path) if wav_path else "",
                "tone_params": tone,
                "sentences": sent_info,
            })

        manifest = {
            "topic": topic,
            "segments": segments,
            "total_segments": len(segments),
            "total_duration_s": round(sum(s["actual_duration_s"] for s in segments), 2),
        }
        write_text(dirs["audio"] / "voice_manifest.json", json.dumps(manifest, indent=2))

        return {
            "agent": self.name,
            "status": "completed",
            "voice": manifest,
        }
