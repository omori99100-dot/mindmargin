import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Report:
    report_id: str = ""
    report_type: str = ""
    title: str = ""
    content: str = ""
    data: dict = field(default_factory=dict)
    created_at: str = ""
    workflow_run_id: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "report_type": self.report_type,
            "title": self.title,
            "content": self.content[:5000],
            "data": self.data,
            "created_at": self.created_at,
            "workflow_run_id": self.workflow_run_id,
            "metadata": self.metadata,
        }


class ReportGenerator:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._rep_dir = root / "github" / "reports"
        self._rep_dir.mkdir(parents=True, exist_ok=True)
        self._reports: list[Report] = []
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        reports_path = self._rep_dir / "reports.json"
        if reports_path.exists():
            try:
                data = json.loads(reports_path.read_text(encoding="utf-8"))
                self._reports = [Report(**r) for r in data]
            except Exception:
                pass

    def _save(self):
        reports_path = self._rep_dir / "reports.json"
        reports_path.write_text(
            json.dumps([r.to_dict() for r in self._reports[-200:]], indent=2),
            encoding="utf-8",
        )

    def _add_report(self, report_type: str, title: str, content: str,
                    data: dict = None, workflow_run_id: str = "") -> Report:
        import uuid
        report = Report(
            report_id=f"rep_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            report_type=report_type,
            title=title,
            content=content,
            data=data or {},
            created_at=datetime.now(timezone.utc).isoformat(),
            workflow_run_id=workflow_run_id,
        )
        with self._lock:
            self._reports.append(report)
            self._save()
        return report

    def generate_workflow_report(self, run_data: dict) -> Report:
        state = run_data.get("state", "unknown")
        name = run_data.get("workflow_name", "unknown")
        duration = run_data.get("duration_s", 0)
        jobs = run_data.get("jobs", {})
        failed = sum(1 for j in jobs.values() if j.get("state") == "failed")

        content = f"## Workflow Report: {name}\n\n"
        content += f"**State:** {state}\n"
        content += f"**Duration:** {duration:.1f}s\n"
        content += f"**Jobs:** {len(jobs)} total, {failed} failed\n\n"

        if failed > 0:
            content += "### Failed Jobs\n\n"
            for jid, j in jobs.items():
                if j.get("state") == "failed":
                    content += f"- **{j.get('name', jid)}**: {j.get('error', 'Unknown error')[:200]}\n"

        return self._add_report(
            "workflow", f"Workflow Report: {name}", content, run_data,
            run_data.get("run_id", ""),
        )

    def generate_failure_report(self, diagnosis: dict) -> Report:
        wf_name = diagnosis.get("workflow_name", "unknown")
        failure_type = diagnosis.get("overall_failure_type", "unknown")
        failed_jobs = diagnosis.get("failed_jobs", [])

        content = f"## Failure Report: {wf_name}\n\n"
        content += f"**Failure Type:** {failure_type}\n"
        content += f"**Failed Jobs:** {len(failed_jobs)}\n"
        content += f"**Recommendation:** {diagnosis.get('recommendation', 'None')}\n\n"

        for job in failed_jobs:
            content += f"### {job.get('job_name', job.get('job_id'))}\n"
            content += f"- Type: {job.get('failure_type', 'unknown')}\n"
            content += f"- Error: {job.get('error', 'N/A')[:300]}\n"
            content += f"- Retry: {job.get('retry_count', 0)}/{job.get('max_retries', 0)}\n\n"

        return self._add_report("failure", f"Failure Report: {wf_name}", content, diagnosis)

    def generate_daily_summary(self, runs: list[dict], metrics: dict) -> Report:
        total = len(runs)
        completed = sum(1 for r in runs if r.get("state") == "completed")
        failed = sum(1 for r in runs if r.get("state") == "failed")
        avg_duration = sum(r.get("duration_s", 0) for r in runs) / max(total, 1)

        content = f"## Daily GitHub Actions Summary\n\n"
        content += f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        content += f"**Total Runs:** {total}\n"
        content += f"**Completed:** {completed}\n"
        content += f"**Failed:** {failed}\n"
        content += f"**Success Rate:** {completed/max(total,1)*100:.1f}%\n"
        content += f"**Avg Duration:** {avg_duration:.1f}s\n\n"

        counters = metrics.get("counters", {})
        if counters:
            content += "### Metrics\n\n"
            for key, val in counters.items():
                content += f"- {key}: {val}\n"

        return self._add_report("daily_summary", "Daily Summary", content,
                                {"runs": runs, "metrics": metrics})

    def generate_weekly_report(self, runs: list[dict], metrics: dict) -> Report:
        total = len(runs)
        completed = sum(1 for r in runs if r.get("state") == "completed")
        failed = sum(1 for r in runs if r.get("state") == "failed")

        by_workflow = {}
        for r in runs:
            wf = r.get("workflow_name", "unknown")
            if wf not in by_workflow:
                by_workflow[wf] = {"total": 0, "completed": 0, "failed": 0}
            by_workflow[wf]["total"] += 1
            if r.get("state") == "completed":
                by_workflow[wf]["completed"] += 1
            elif r.get("state") == "failed":
                by_workflow[wf]["failed"] += 1

        content = f"## Weekly GitHub Actions Report\n\n"
        content += f"**Week of:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        content += f"**Total Runs:** {total}\n"
        content += f"**Success Rate:** {completed/max(total,1)*100:.1f}%\n\n"

        content += "### By Workflow\n\n"
        for wf, stats in by_workflow.items():
            content += f"- **{wf}**: {stats['total']} runs, {stats['completed']} OK, {stats['failed']} failed\n"

        return self._add_report("weekly_summary", "Weekly Report", content,
                                {"runs": runs, "metrics": metrics, "by_workflow": by_workflow})

    def get_report(self, report_id: str) -> Optional[Report]:
        with self._lock:
            for r in self._reports:
                if r.report_id == report_id:
                    return r
        return None

    def list_reports(self, report_type: str = "", limit: int = 50) -> list[dict]:
        with self._lock:
            reports = self._reports
        if report_type:
            reports = [r for r in reports if r.report_type == report_type]
        reports.sort(key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in reports[:limit]]

    def delete_report(self, report_id: str) -> bool:
        with self._lock:
            for i, r in enumerate(self._reports):
                if r.report_id == report_id:
                    self._reports.pop(i)
                    self._save()
                    return True
        return False
