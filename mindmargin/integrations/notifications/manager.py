import json
import logging
import smtplib
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


@dataclass
class NotificationRecord:
    channel: str = ""
    recipient: str = ""
    subject: str = ""
    message: str = ""
    status: str = "pending"
    sent_at: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "recipient": self.recipient,
            "subject": self.subject,
            "message": self.message[:200],
            "status": self.status,
            "sent_at": self.sent_at,
            "error": self.error,
        }


class NotificationManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._notif_dir = root / "integrations" / "notifications"
        self._notif_dir.mkdir(parents=True, exist_ok=True)
        self._history_path = self._notif_dir / "history.json"
        self._records: list[NotificationRecord] = self._load_history()

    def _load_history(self) -> list[NotificationRecord]:
        if self._history_path.exists():
            try:
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                return [NotificationRecord(**r) for r in data]
            except Exception:
                pass
        return []

    def _save_history(self):
        records = [r.to_dict() for r in self._records[-500:]]
        self._history_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    def notify(self, channel: str, subject: str, message: str,
               recipient: str = "", priority: str = "normal") -> dict:
        record = NotificationRecord(
            channel=channel,
            recipient=recipient,
            subject=subject,
            message=message,
            status="sending",
            sent_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            handler = {
                "telegram": self._send_telegram,
                "discord": self._send_discord,
                "slack": self._send_slack,
                "email": self._send_email,
                "webhook": self._send_webhook,
            }.get(channel)

            if not handler:
                record.status = "failed"
                record.error = f"Unknown channel: {channel}"
            else:
                result = handler(subject, message, recipient)
                record.status = "sent" if result.get("ok") else "failed"
                record.error = result.get("error", "")
        except Exception as e:
            record.status = "failed"
            record.error = str(e)
            logger.error("Notification failed on %s: %s", channel, e)

        self._records.append(record)
        self._save_history()
        return record.to_dict()

    def notify_workflow_completed(self, workflow_name: str, detail: str = ""):
        return self._broadcast("Workflow Completed", f"{workflow_name}: {detail}")

    def notify_workflow_failed(self, workflow_name: str, error: str = ""):
        return self._broadcast("Workflow FAILED", f"{workflow_name}: {error}", priority="high")

    def notify_video_published(self, title: str, url: str):
        return self._broadcast("Video Published", f"{title}\n{url}")

    def notify_experiment_finished(self, experiment_id: str, result: str):
        return self._broadcast("Experiment Finished", f"{experiment_id}: {result}")

    def notify_critical_alert(self, alert: str):
        return self._broadcast("CRITICAL ALERT", alert, priority="high")

    def notify_provider_failure(self, provider: str, error: str):
        return self._broadcast("Provider Failure", f"{provider}: {error}", priority="high")

    def notify_executive_decision(self, action: str, reason: str):
        return self._broadcast("Executive Decision", f"Action: {action}\nReason: {reason}")

    def _broadcast(self, subject: str, message: str, priority: str = "normal") -> list[dict]:
        results = []
        channels = self._get_active_channels()
        for channel in channels:
            result = self.notify(channel, subject, message, priority=priority)
            results.append(result)
        return results

    def _get_active_channels(self) -> list[str]:
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        channels = []
        if sm.is_configured("TELEGRAM_BOT_TOKEN"):
            channels.append("telegram")
        if sm.is_configured("DISCORD_WEBHOOK_URL"):
            channels.append("discord")
        if sm.is_configured("SLACK_WEBHOOK_URL"):
            channels.append("slack")
        if sm.is_configured("NOTIFY_EMAIL"):
            channels.append("email")
        if sm.is_configured("WEBHOOK_SECRET"):
            channels.append("webhook")
        return channels

    def _send_telegram(self, subject: str, message: str, chat_id: str = "") -> dict:
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        token = sm.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
        cid = chat_id or sm.get("TELEGRAM_CHAT_ID") or ""
        if not cid:
            return {"ok": False, "error": "TELEGRAM_CHAT_ID not configured"}
        text = f"*{subject}*\n{message}"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": cid, "text": text, "parse_mode": "Markdown"}).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                return {"ok": resp.status == 200}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _send_discord(self, subject: str, message: str, webhook_url: str = "") -> dict:
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        url = webhook_url or sm.get("DISCORD_WEBHOOK_URL") or ""
        if not url:
            return {"ok": False, "error": "DISCORD_WEBHOOK_URL not configured"}
        payload = json.dumps({"content": f"**{subject}**\n{message}"}).encode()
        try:
            req = urllib.request.Request(url, data=payload, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return {"ok": resp.status in (200, 204)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _send_slack(self, subject: str, message: str, webhook_url: str = "") -> dict:
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        url = webhook_url or sm.get("SLACK_WEBHOOK_URL") or ""
        if not url:
            return {"ok": False, "error": "SLACK_WEBHOOK_URL not configured"}
        payload = json.dumps({"text": f"*{subject}*\n{message}"}).encode()
        try:
            req = urllib.request.Request(url, data=payload, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return {"ok": resp.status == 200}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _send_email(self, subject: str, message: str, to_addr: str = "") -> dict:
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        from_addr = sm.get("NOTIFY_EMAIL") or ""
        password = sm.get("NOTIFY_EMAIL_PASSWORD") or ""
        to = to_addr or from_addr
        if not from_addr or not to:
            return {"ok": False, "error": "Email not configured"}
        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                if password:
                    server.login(from_addr, password)
                server.send_message(msg)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _send_webhook(self, subject: str, message: str, webhook_url: str = "") -> dict:
        from mindmargin.integrations.secrets.manager import SecretManager
        sm = SecretManager()
        url = webhook_url or ""
        if not url:
            return {"ok": False, "error": "Webhook URL not configured"}
        payload = json.dumps({
            "subject": subject, "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }).encode()
        try:
            req = urllib.request.Request(url, data=payload, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return {"ok": resp.status in (200, 201, 204)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_history(self, limit: int = 50) -> list[dict]:
        return [r.to_dict() for r in self._records[-limit:]]

    def get_status(self) -> dict:
        channels = self._get_active_channels()
        total = len(self._records)
        sent = sum(1 for r in self._records if r.status == "sent")
        failed = sum(1 for r in self._records if r.status == "failed")
        return {
            "active_channels": channels,
            "total_notifications": total,
            "sent": sent,
            "failed": failed,
            "success_rate": round(sent / max(total, 1) * 100, 1),
        }
