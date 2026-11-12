"""通知。送信先の URL やパスワードは環境変数から読む。

- webhook: KABU_WEBHOOK_URL（Slack / Discord の Incoming Webhook）
- email:   KABU_SMTP_HOST, KABU_SMTP_PORT(587), KABU_SMTP_USER, KABU_SMTP_PASSWORD, KABU_MAIL_TO
"""

from __future__ import annotations

import json
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from kabu.config.models import NotifySettings
from kabu.decision import Judgement


def summary_text(judgements: list[Judgement], title: str) -> str:
    lines = [title]
    for j in judgements:
        h = max(j.estimates)
        e = j.estimates[h]
        lines.append(
            f"{j.verdict.value:4} {j.stock.code} {j.stock.name}  株価 {j.metrics.last_close:,.0f}  "
            f"{h}ヶ月 {e.total_mid:+.1%}（{e.total_low:+.1%}〜{e.total_high:+.1%}）  {j.reasons[0]}"
        )
        for w in j.warnings:
            lines.append(f"     ⚠ {w}")
    return "\n".join(lines)


def _verdict_signature(judgements: list[Judgement]) -> dict[str, str]:
    return {j.stock.code: j.verdict.value for j in judgements}


def _changed_since_last(judgements: list[Judgement], state_path: Path) -> bool:
    sig = _verdict_signature(judgements)
    prev = json.loads(state_path.read_text()) if state_path.exists() else None
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sig, ensure_ascii=False))
    return prev != sig


def send_webhook(text: str, fmt: str) -> None:
    import requests

    url = os.environ.get("KABU_WEBHOOK_URL")
    if not url:
        raise RuntimeError("環境変数 KABU_WEBHOOK_URL が未設定です")
    payload = {"content": text[:1900]} if fmt == "discord" else {"text": text}
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()


def send_email(subject: str, body: str) -> None:
    host = os.environ.get("KABU_SMTP_HOST")
    user = os.environ.get("KABU_SMTP_USER")
    password = os.environ.get("KABU_SMTP_PASSWORD")
    to = os.environ.get("KABU_MAIL_TO")
    port = int(os.environ.get("KABU_SMTP_PORT", "587"))
    if not all([host, user, password, to]):
        raise RuntimeError("環境変数 KABU_SMTP_HOST / KABU_SMTP_USER / KABU_SMTP_PASSWORD / KABU_MAIL_TO が必要です")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)


def send_notifications(
    judgements: list[Judgement],
    settings: NotifySettings,
    title: str,
    full_report: str,
    state_path: Path,
) -> list[str]:
    """設定されたチャネルに通知する。送った先の名前を返す。"""
    changed = _changed_since_last(judgements, state_path)
    if settings.only_on_change and not changed:
        return []
    text = summary_text(judgements, title)
    sent: list[str] = []
    for ch in settings.channels:
        if ch == "stdout":
            print(text)
        elif ch == "webhook":
            send_webhook(text, settings.webhook_format)
        elif ch == "email":
            send_email(title, full_report)
        sent.append(ch)
    return sent
