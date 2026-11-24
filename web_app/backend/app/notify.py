"""Outbound notifications for Asarak (أسعارك): email + Telegram, zero DB writes.

Shared by the public contact / add-store endpoints (``app.routers.submissions``)
and the price-drop alert checker job (``jobs.check_price_alerts``).

Email provider chain — the first *configured* provider that succeeds wins:
  1. Resend HTTP API -> ``RESEND_API_KEY`` (+ ``RESEND_FROM_EMAIL``, ``RESEND_FROM_NAME``)
  2. SMTP over STARTTLS -> ``SMTP_HOST`` + ``SMTP_USER`` + ``SMTP_PASS``
     (+ ``SMTP_PORT``=587, ``SMTP_FROM``)

Telegram -> ``TELEGRAM_BOT_TOKEN``.

Nothing here reads or writes Neon. Env vars are read at call time, and a blank
value counts as unset (GitHub Actions passes a missing secret as ``""``).
"""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
TELEGRAM_API_BASE = "https://api.telegram.org"
HTTP_TIMEOUT_SECONDS = 12.0
SMTP_TIMEOUT_SECONDS = 15.0
SMTP_DEFAULT_PORT = 587
DEFAULT_FROM_EMAIL = "alerts@asarak.com"
TELEGRAM_MAX_CHARS = 4096


@dataclass(frozen=True)
class SendResult:
    """Outcome of a send. ``provider`` is the last provider tried."""

    ok: bool
    provider: str = ""
    reason: str = ""


def env_str(name: str) -> str:
    """Trimmed env var; blank counts as unset."""
    return os.getenv(name, "").strip()


def env_int(name: str, default: int, *, lo: int, hi: int) -> int:
    """Integer env var clamped to [lo, hi]; blank or malformed falls back to default."""
    try:
        value = int(os.getenv(name, "") or default)
    except ValueError:
        return default
    return min(hi, max(lo, value))


def _mask(address: str) -> str:
    local, _, domain = address.partition("@")
    if not domain:
        return f"{address[:1]}•••"
    return f"{local[:1]}•••@{domain}"


def email_providers() -> tuple[str, ...]:
    """Configured email providers in priority order, e.g. ``("resend", "smtp")``."""
    providers: list[str] = []
    if env_str("RESEND_API_KEY"):
        providers.append("resend")
    if env_str("SMTP_HOST") and env_str("SMTP_USER") and env_str("SMTP_PASS"):
        providers.append("smtp")
    return tuple(providers)


def _error_message(resp: httpx.Response, *, fallback: str) -> str:
    """Provider error text without the request URL (Telegram's URL embeds the bot token)."""
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    message = ""
    if isinstance(payload, dict):
        message = str(payload.get("message") or payload.get("description") or "")
    return f"HTTP {resp.status_code}: {message or fallback}"[:300]


def _send_via_resend(to: str, subject: str, body: str) -> None:
    sender = env_str("RESEND_FROM_EMAIL") or DEFAULT_FROM_EMAIL
    sender_name = env_str("RESEND_FROM_NAME") or "Asarak"
    resp = httpx.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {env_str('RESEND_API_KEY')}"},
        json={
            "from": f"{sender_name} <{sender}>",
            "to": [to],
            "subject": subject,
            "text": body,
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if resp.status_code >= 400:
        raise RuntimeError(_error_message(resp, fallback="Resend rejected the email"))


def _send_via_smtp(to: str, subject: str, body: str) -> None:
    host = env_str("SMTP_HOST")
    user = env_str("SMTP_USER")
    password = env_str("SMTP_PASS")
    port = env_int("SMTP_PORT", SMTP_DEFAULT_PORT, lo=1, hi=65535)
    sender = env_str("SMTP_FROM") or user or DEFAULT_FROM_EMAIL

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


def send_email(to: str, subject: str, body: str) -> SendResult:
    """Send one plain-text email through Resend, then SMTP if Resend fails.

    Never raises: provider outages come back as ``SendResult(ok=False)`` with the
    failing provider and a sanitized reason.
    """
    providers = email_providers()
    if not providers:
        return SendResult(
            False, "", "no email provider configured (RESEND_API_KEY or SMTP_HOST/SMTP_USER/SMTP_PASS)"
        )

    outcome = SendResult(False, "", "no email provider succeeded")
    for provider in providers:
        try:
            if provider == "resend":
                _send_via_resend(to, subject, body)
            else:
                _send_via_smtp(to, subject, body)
        except Exception as exc:
            logger.warning("[notify][%s] send to %s failed: %s", provider, _mask(to), exc)
            outcome = SendResult(False, provider, f"{provider}: {exc}")
        else:
            return SendResult(True, provider)
    return outcome


def send_telegram(
    chat_id: str,
    text: str,
    *,
    token: str | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = False,
) -> SendResult:
    """Post one Bot API message. Never raises; the bot token never reaches the reason."""
    bot_token = env_str("TELEGRAM_BOT_TOKEN") if token is None else token.strip()
    if not bot_token:
        return SendResult(False, "telegram", "TELEGRAM_BOT_TOKEN not configured")
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": text[:TELEGRAM_MAX_CHARS],
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = httpx.post(
            f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
            json=payload,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if resp.status_code >= 400:
            return SendResult(False, "telegram", f"telegram: {_error_message(resp, fallback='sendMessage rejected')}")
    except httpx.HTTPError as exc:
        return SendResult(False, "telegram", f"telegram: {exc.__class__.__name__}")
    return SendResult(True, "telegram")
