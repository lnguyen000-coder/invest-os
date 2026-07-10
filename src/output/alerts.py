"""Alert delivery. Telegram (free, instant push) or email. One digest per
run, sent ONLY if at least one alert condition fired. No 'all quiet' spam.
"""
from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from typing import Any

import requests

from src.config import env


@dataclass
class Alert:
    symbol: str
    reasons: list[str]
    headline: str
    plain_english: str
    conviction: float | None = None
    fair_value: float | None = None
    price: float | None = None


class AlertSink:
    def __init__(self, settings):
        self.settings = settings
        self.queue: list[Alert] = []

    def add(self, alert: Alert) -> None:
        self.queue.append(alert)

    def flush(self) -> bool:
        """Send the digest. Returns True if something was sent."""
        if not self.queue:
            return False
        body = self._render()
        channel = self.settings.get("alerts", "channel", default="telegram")
        sent = False
        if channel == "telegram":
            sent = self._send_telegram(body)
        elif channel == "email":
            sent = self._send_email(body)
        if not sent:
            # Never lose an alert: print to the Action log as last resort.
            print("=== ALERT DIGEST (delivery unavailable) ===")
            print(body)
        self.queue.clear()
        return True

    def _render(self) -> str:
        lines = ["📊 Research OS — material changes\n"]
        for a in self.queue:
            lines.append(f"── {a.symbol} ──")
            lines.append(a.headline)
            for r in a.reasons:
                lines.append(f"  • {r}")
            if a.price and a.fair_value:
                upside = (a.fair_value / a.price - 1) * 100
                lines.append(f"  Price ${a.price:,.2f} vs fair "
                             f"${a.fair_value:,.2f} ({upside:+.0f}%)")
            if a.conviction is not None:
                lines.append(f"  Conviction: {a.conviction:.0f}/100")
            if a.plain_english:
                lines.append(f"  {a.plain_english}")
            lines.append("")
        lines.append("Full analysis in research/<TICKER>/research.md "
                      "and the dashboard.")
        return "\n".join(lines)

    def _send_telegram(self, body: str) -> bool:
        token = env("TELEGRAM_BOT_TOKEN")
        chat_id = env("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return False
        # Telegram caps messages at 4096 chars; chunk if needed.
        ok = True
        for i in range(0, len(body), 3900):
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": body[i:i + 3900]},
                    timeout=20,
                )
                ok = ok and r.status_code == 200
            except requests.RequestException:
                ok = False
        return ok

    def _send_email(self, body: str) -> bool:
        user = env("SMTP_USER")
        password = env("SMTP_PASSWORD")
        host = self.settings.get("email", "smtp_host", default="smtp.gmail.com")
        port = int(self.settings.get("email", "smtp_port", default=587))
        from_addr = self.settings.get("email", "from_addr") or user
        to_addr = self.settings.get("email", "to_addr") or user
        if not user or not password or not to_addr:
            return False
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = "Research OS — material changes on your watchlist"
        msg["From"] = from_addr
        msg["To"] = to_addr
        try:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls()
                s.login(user, password)
                s.sendmail(from_addr, [to_addr], msg.as_string())
            return True
        except (smtplib.SMTPException, OSError):
            return False
