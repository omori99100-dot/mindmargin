import json
import logging
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text, project_dir
from mindmargin.core.timing import Timer
from mindmargin.core.state import PipelineState, CREATED, RESEARCHING, SCRIPTING, \
    VOICE_GENERATION, EDITING, MERGING, COMPLETED, FAILED
from mindmargin.core.cache import AssetCache, hash_file, hash_text
from mindmargin.core.pipeline_logger import PipelineLogger
from mindmargin.core.metrics import PipelineMetrics
from mindmargin.logger import logger

from mindmargin.agents.research import ResearchAgent
from mindmargin.agents.script import ScriptAgent
from mindmargin.agents.voice import VoiceAgent
from mindmargin.agents.editing import EditingAgent

AGENTS = ["research", "script", "voice", "editing"]
AGENT_STATES = {
    "research": RESEARCHING,
    "script": SCRIPTING,
    "voice": VOICE_GENERATION,
    "editing": EDITING,
}
PER_STAGE_TIMING_CATEGORIES = {
    "research": "research_runtime_seconds",
    "script": "script_runtime_seconds",
    "voice": "tts_runtime_seconds",
    "editing": "render_runtime_seconds",
}


class PipelineError(Exception):
    pass


class Pipeline:
    """Production pipeline with state machine, cache, structured logging, and metrics."""

    def __init__(self, topic: str, pipeline_id: Optional[str] = None,
                 duration_scale: float = 1.0, mode: str = "documentary",
                 use_templates: bool = False,
                 editing_timeout: Optional[int] = None,
                 force_editing: bool = False):
        self.topic = topic
        self.pipeline_id = pipeline_id or f"pipe_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.duration_scale = duration_scale
        self.mode = mode
        self.use_templates = use_templates
        self.editing_timeout = editing_timeout
        self.force_editing = force_editing
        self.status = "initialized"
        self.state: dict[str, dict] = {}
        self.errors: list[dict] = []
        self.timer = Timer()
        self._checkpoint_dir = Path(settings.storage.output_root) / "checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Production-grade subsystems
        self._pstate = PipelineState(self.pipeline_id, topic)
        self._plog = PipelineLogger(self.pipeline_id) if settings.production.enable_structured_logs else None
        self._cache = AssetCache(self.pipeline_id) if settings.production.enable_cache_hash else None
        self._metrics = PipelineMetrics(self.pipeline_id, topic)

        if pipeline_id:
            loaded = self._load_checkpoint("_pipeline_state")
            if loaded:
                self._pstate._data.update(loaded)
                logger.info(f"Resumed pipeline state: {self._pstate.state}")

    def run(self) -> dict:
        logger.info(("=" * 50))
        logger.info(f"Pipeline {self.pipeline_id} | topic: '{self.topic}'")
        logger.info(("=" * 50))
        self.status = "running"
        self.timer.start("pipeline")
        self._pstate.mark_started()
        self._log("pipeline_started", "pipeline")

        if self._pstate.is_terminal:
            logger.info(f"Pipeline {self.pipeline_id} already {self._pstate.state}, skipping")
            return self._summary()

        ensure_dirs(self.topic, self.pipeline_id)

        agents = {
            "research": ResearchAgent(),
            "script": ScriptAgent(mode=self.mode, use_templates=self.use_templates),
            "voice": VoiceAgent(),
            "editing": EditingAgent(editing_timeout=self.editing_timeout, force=self.force_editing),
        }

        # Pass provider manager to research agent for LLM-enhanced research
        try:
            from mindmargin.integrations.manager import create_default_manager
            pm = create_default_manager()
            agents["research"]._pm = pm
        except Exception:
            pass

        for name in AGENTS:
            self._pstate.state = AGENT_STATES.get(name, name.upper())
            self._log("stage_started", name)

            agent = agents.get(name)
            if not agent:
                continue

            ckpt = self._load_checkpoint(name)
            if ckpt is not None:
                logger.info(f"[checkpoint] {name} -> skipping (already complete)")
                self.state[name] = ckpt
                self._log("stage_skipped", name, metadata={"reason": "checkpoint"})
                continue

            logger.info(("-" * 40))
            logger.info(f"Agent: {name}")
            logger.info(("-" * 40))

            # Cache check for voice and editing
            if name == "voice" and self._cache:
                script = self.state.get("script", {}).get("script", {})
                script_hash = hash_dict(script)
                if self._cache.check("voice_script", script_hash):
                    logger.info("[cache] voice script unchanged, skipping voice generation")
                    self._log("cache_hit", "voice", metadata={"key": "voice_script"})
                    self.state[name] = {"status": "skipped", "voice": {"segments": []}}
                    continue

            try:
                result = self._run_with_retry(agent, name)
                self.state[name] = result
                self._save_checkpoint(name, result)
                self._pstate.state = AGENT_STATES.get(name, name.upper())

                if result.get("status") == "failed":
                    raise PipelineError(f"{name} failed: {result.get('error', 'unknown')}")

                # Update cache after successful stage
                if name == "script" and self._cache:
                    script_data = result.get("script", {})
                    script_hash = hash_dict(script_data)
                    self._cache.update("voice_script", script_hash)

                self.timer.lap(name)
                self._record_stage_timing(name)
                self._log("stage_completed", name, duration=self.timer._laps[-1]["elapsed_s"] - (self.timer._laps[-2]["elapsed_s"] if len(self.timer._laps) > 1 else 0))
                logger.info(f"[ok] {name} completed  ({result.get('video_path', result.get('status', 'ok'))})")

            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"[FAIL] {name}: {e}")
                logger.debug(tb)
                self.errors.append({
                    "agent": name,
                    "error": str(e),
                    "traceback": tb,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                self.status = "failed"
                self._pstate.mark_failed(str(e))
                self._log("stage_failed", name, metadata={"error": str(e)})
                self.timer.lap(f"{name}_failed")
                self.timer.stop("failed")

                # Record metrics
                self._metrics.record_stage(name, self.timer._laps[-1].get("elapsed_s", 0))
                if self._cache:
                    self._metrics.record_cache(self._cache._hits, self._cache._misses)
                self._metrics.record_final_status("failed")
                self._metrics.save()
                return self._summary()

            # Phase 5D: start thumbnail generation in background after script completes
            if name == "script":
                self._start_thumbnail_thread()

        # Final merge stage
        self._pstate.state = MERGING
        self._log("stage_started", "merging")

        self.timer.stop("completed")
        self.status = "completed"
        self._pstate.state = COMPLETED
        self._log("pipeline_completed", "pipeline", duration=self.timer.total_s)

        # Metrics and health report
        self._finalize_metrics()

        logger.info(("=" * 50))
        logger.info(f"Pipeline {self.pipeline_id} completed")
        logger.info(f"Timing: {self.timer.summary()}")
        logger.info(("=" * 50))
        return self._summary()

    def _run_with_retry(self, agent, name: str) -> dict:
        max_retries = 2
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                if name == "research":
                    return agent.run(self.topic, self.pipeline_id)
                elif name == "script":
                    research = self.state.get("research", {}).get("research", {})
                    return agent.run(self.topic, self.pipeline_id, research)
                elif name == "voice":
                    script = self.state.get("script", {}).get("script", {})
                    sections = script.get("sections", [])
                    return agent.run(self.topic, self.pipeline_id, sections)
                elif name == "editing":
                    script = self.state.get("script", {}).get("script", {})
                    sections = script.get("sections", [])
                    voice = self.state.get("voice", {}).get("voice", {})
                    voice_segments = voice.get("segments", [])
                    return agent.run(self.topic, self.pipeline_id, sections, voice_segments,
                                     duration_scale=self.duration_scale)
            except Exception as e:
                last_error = e
                logger.warning(f"[retry] {name} attempt {attempt}/{max_retries}: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(2)

        raise last_error or RuntimeError(f"{name} failed after {max_retries} retries")

    def _record_stage_timing(self, stage: str):
        try:
            from mindmargin.analytics.monitoring import record_event
            category = PER_STAGE_TIMING_CATEGORIES.get(stage, "pipeline_runtime_seconds")
            for lap in self.timer._laps:
                if lap["label"] == stage:
                    record_event(category, self.pipeline_id, lap["elapsed_s"],
                                 metadata={"topic": self.topic, "stage": stage})
                    break
            if stage == AGENTS[-1]:
                record_event("pipeline_runtime_seconds", self.pipeline_id,
                             round(self.timer.total_s, 2),
                             metadata={"topic": self.topic})
        except Exception:
            pass

    def _start_thumbnail_thread(self):
        try:
            script_data = self.state.get("script", {}).get("script", {})
            if not script_data:
                return
            t = threading.Thread(
                target=self._generate_thumbnails_bg,
                args=(script_data,),
                daemon=True,
            )
            t.start()
            logger.info("Background thumbnail generation started (parallel with voice+editing)")
        except Exception as e:
            logger.warning(f"Background thumbnail thread failed to start: {e}")

    def _generate_thumbnails_bg(self, script_data: dict):
        try:
            from mindmargin.agents.thumbnail import ThumbnailAgent
            agent = ThumbnailAgent()
            result = agent.run(self.topic, self.pipeline_id, script_data)
            thumbnail_paths = [
                v["path"] for v in result.get("thumbnails", {}).get("variants", [])
            ]
            logger.info(f"Background thumbnails: {len(thumbnail_paths)} variants ready")
        except Exception as e:
            logger.warning(f"Background thumbnail generation failed: {e}")

    def _checkpoint_path(self, agent_name: str) -> Path:
        slug = "".join(c if c.isalnum() else "_" for c in self.topic)[:32]
        return self._checkpoint_dir / f"{self.pipeline_id}_{slug}_{agent_name}.json"

    def _save_checkpoint(self, agent_name: str, data: dict):
        path = self._checkpoint_path(agent_name)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        if agent_name == "_pipeline_state":
            return
        self._pstate.set_metadata(f"checkpoint_{agent_name}", str(path))

    def _load_checkpoint(self, agent_name: str) -> Optional[dict]:
        path = self._checkpoint_path(agent_name)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _log(self, event: str, stage: str, duration: Optional[float] = None,
             metadata: Optional[dict] = None):
        if self._plog:
            self._plog.log(event, stage=stage, status="info" if "fail" not in event else "failed",
                          duration=duration, metadata=metadata)

    def _finalize_metrics(self):
        for lap in self.timer._laps[1:]:
            label = lap["label"].replace("_failed", "")
            self._metrics.record_stage(label, lap["elapsed_s"])
        if self._cache:
            self._metrics.record_cache(self._cache._hits, self._cache._misses)
            self._metrics.data["cache"]["fingerprints"] = self._cache.fingerprints
        self._metrics.record_final_status(self.status)
        out_dir = project_dir(self.topic, self.pipeline_id)
        self._metrics.save(out_dir)

    def _summary(self) -> dict:
        out_dir = project_dir(self.topic, self.pipeline_id)
        video_path = ""
        if "editing" in self.state:
            video_path = self.state["editing"].get("video_path", "")

        return {
            "pipeline_id": self.pipeline_id,
            "topic": self.topic,
            "mode": self.mode,
            "status": self.status,
            "completed_agents": [k for k in AGENTS if k in self.state],
            "errors": self.errors,
            "output_dir": str(out_dir),
            "video_path": video_path,
            "video_duration_s": self.state.get("editing", {}).get("duration_s", 0),
            "timing_s": round(self.timer.total_s, 1),
            "timing_detail": self.timer.summary(),
        }


def hash_dict(d: dict) -> str:
    return hash_text(json.dumps(d, sort_keys=True, default=str))
