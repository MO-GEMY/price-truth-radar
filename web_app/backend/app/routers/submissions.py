"""Public inbound forms: contact messages and store suggestions.

Zero Neon by design — submissions are validated in memory and forwarded to the
team over the configured notification channel (Resend/SMTP email, or Telegram).
Nothing is stored, and a submitted store URL is never fetched, resolved, or
scraped: every request is handled by a human during manual review.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.antispam import (
    RateLimiter,
    client_ip,
    enforce_rate_limit,
    turnstile_site_key,
    verify_turnstile,
)
from app.notify import SendResult, email_providers, env_str, send_email, send_telegram
from app.sanitize import multiline, one_line
from app.schemas import (
    ContactCreateRequest,
    StoreSuggestCreateRequest,
    SubmissionAcceptedResponse,
    SubmissionsConfigResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["submissions"])

# Per-process budgets. The per-IP limit brakes casual abuse; the global cap bounds
# outbound mail volume (provider quota + sender reputation) even when IPs rotate.
_contact_ip = RateLimiter(
    limit_env="CONTACT_RATE_LIMIT",
    default_limit=5,
    window_env="CONTACT_RATE_WINDOW_SECONDS",
    default_window=600,
)
_contact_all = RateLimiter(
    limit_env="CONTACT_GLOBAL_RATE_LIMIT",
    default_limit=40,
    window_env="CONTACT_GLOBAL_RATE_WINDOW_SECONDS",
    default_window=3600,
)
_store_ip = RateLimiter(
    limit_env="ADD_STORE_RATE_LIMIT",
    default_limit=3,
    window_env="ADD_STORE_RATE_WINDOW_SECONDS",
    default_window=600,
)
_store_all = RateLimiter(
    limit_env="ADD_STORE_GLOBAL_RATE_LIMIT",
    default_limit=25,
    window_env="ADD_STORE_GLOBAL_RATE_WINDOW_SECONDS",
    default_window=3600,
)

CONTACT_CATEGORY_LABELS = {
    "price_error": "الإبلاغ عن سعر خطأ",
    "general": "استفسار عام",
    "partnership": "تعاون وإعلانات",
}
STORE_KIND_LABELS = {
    "suggest": "مستخدم يقترح متجر",
    "owner": "صاحب متجر أو شركة",
}
STORE_PLATFORM_LABELS = {
    "shopify": "Shopify",
    "woocommerce": "WooCommerce",
    "salla_zid": "سلة / زد",
    "custom": "مخصص / أخرى",
}

_ACCEPTED = SubmissionAcceptedResponse(
    message="Received — the team will review it and get back to you."
)
_RULE = "-" * 40


def _reject(status_code: int, detail: str, retry_after: int | None = None) -> HTTPException:
    """Error response a CDN must never cache (FastAPI drops the injected Response headers)."""
    headers = {"Cache-Control": "no-store"}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return HTTPException(status_code, detail, headers=headers)


def contact_inbox() -> str:
    return env_str("CONTACT_TO_EMAIL")


def store_inbox() -> str:
    return env_str("ADD_STORE_TO_EMAIL") or env_str("CONTACT_TO_EMAIL")


def team_channel_ready(inbox: str) -> bool:
    """True when at least one working path to the team is configured."""
    if inbox and email_providers():
        return True
    return bool(env_str("TELEGRAM_BOT_TOKEN") and env_str("TELEGRAM_NOTIFY_CHAT_ID"))


def notify_team(subject: str, body: str, *, inbox: str) -> SendResult:
    """Email the team first (Resend -> SMTP); fall back to Telegram if email fails."""
    attempts: list[SendResult] = []
    if inbox and email_providers():
        emailed = send_email(inbox, subject, body)
        if emailed.ok:
            return emailed
        attempts.append(emailed)

    chat_id = env_str("TELEGRAM_NOTIFY_CHAT_ID")
    if env_str("TELEGRAM_BOT_TOKEN") and chat_id:
        messaged = send_telegram(chat_id, f"{subject}\n\n{body}")
        if messaged.ok:
            return messaged
        attempts.append(messaged)

    return attempts[-1] if attempts else SendResult(False, "", "notification_channel_unconfigured")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _contact_notification(payload: ContactCreateRequest, sender_ip: str) -> tuple[str, str]:
    category_label = CONTACT_CATEGORY_LABELS[payload.category]
    subject = f"[Asarak] Contact · {category_label} · {payload.email}"
    body = (
        "New message from the asarak.com contact form.\n\n"
        f"Category:   {category_label} ({payload.category})\n"
        f"Name:       {one_line(payload.name, max_len=80) or '-'}\n"
        f"Email:      {payload.email}\n"
        f"Product:    {payload.product_url or '-'}\n"
        f"Received:   {_utc_stamp()}\n"
        f"Sender IP:  {one_line(sender_ip, max_len=64)}\n\n"
        f"{_RULE}\n"
        f"{multiline(payload.message, max_len=3000)}\n"
        f"{_RULE}\n"
        "Reply directly to the sender's email above.\n"
    )
    return subject, body


def _store_notification(payload: StoreSuggestCreateRequest, sender_ip: str) -> tuple[str, str]:
    kind_label = STORE_KIND_LABELS[payload.kind]
    platform_line = (
        f"{STORE_PLATFORM_LABELS[payload.platform]} ({payload.platform})" if payload.platform else "-"
    )
    contacts = " · ".join(c for c in (payload.contact_email, payload.contact_whatsapp) if c) or "-"
    subject = f"[Asarak] Store request · {one_line(payload.store_name, max_len=80)}"
    body = (
        'New request from the asarak.com "Add your store" form.\n\n'
        f"Type:       {kind_label} ({payload.kind})\n"
        f"Store:      {one_line(payload.store_name, max_len=120)}\n"
        f"URL:        {payload.store_url}\n"
        f"Platform:   {platform_line}\n"
        f"Contact:    {contacts}\n"
        f"Received:   {_utc_stamp()}\n"
        f"Sender IP:  {one_line(sender_ip, max_len=64)}\n\n"
        "Notes:\n"
        f"{_RULE}\n"
        f"{multiline(payload.notes, max_len=2000) or '-'}\n"
        f"{_RULE}\n"
        "Manual review only — this URL has not been fetched, scraped, or added to the catalog.\n"
    )
    return subject, body


def _accept(
    request: Request,
    payload: ContactCreateRequest | StoreSuggestCreateRequest,
    *,
    source: str,
    ip_limiter: RateLimiter,
    global_limiter: RateLimiter,
    inbox: str,
    build: Callable[[ContactCreateRequest | StoreSuggestCreateRequest, str], tuple[str, str]],
) -> SubmissionAcceptedResponse:
    sender_ip = client_ip(request)

    passed, reason = verify_turnstile(payload.turnstile_token, sender_ip)
    if not passed:
        logger.info("[submissions] %s: turnstile rejected (%s)", source, reason)
        raise _reject(status.HTTP_403_FORBIDDEN, "turnstile_failed")

    if payload.website:
        logger.info("[submissions] %s: honeypot tripped from %s — dropped", source, sender_ip)
        return _ACCEPTED  # indistinguishable from success, so bots learn nothing

    if not team_channel_ready(inbox):
        logger.warning("[submissions] %s received but no notification channel is configured", source)
        raise _reject(status.HTTP_503_SERVICE_UNAVAILABLE, "notification_channel_unconfigured")

    allowed, retry_after = enforce_rate_limit(ip_limiter, global_limiter, sender_ip)
    if not allowed:
        raise _reject(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", retry_after=retry_after)

    subject, body = build(payload, sender_ip)
    result = notify_team(subject, body, inbox=inbox)
    if not result.ok:
        logger.error("[submissions] %s could not be delivered: %s", source, result.reason)
        raise _reject(status.HTTP_503_SERVICE_UNAVAILABLE, "notification_send_failed")

    logger.info("[submissions] %s received via %s from %s", source, result.provider, sender_ip)
    return _ACCEPTED


@router.get("/api/submissions/config", response_model=SubmissionsConfigResponse)
@router.get(
    "/api/v1/submissions/config",
    response_model=SubmissionsConfigResponse,
    include_in_schema=True,
)
def get_submissions_config(response: Response) -> SubmissionsConfigResponse:
    """Whether the forms can deliver, plus the Turnstile site key when enabled."""
    response.headers["Cache-Control"] = "no-store"
    return SubmissionsConfigResponse(
        form_enabled=team_channel_ready(contact_inbox()),
        turnstile_site_key=turnstile_site_key(),
    )


@router.post(
    "/api/submissions/contact",
    response_model=SubmissionAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@router.post(
    "/api/v1/submissions/contact",
    response_model=SubmissionAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=True,
)
def submit_contact(
    payload: ContactCreateRequest,
    request: Request,
    response: Response,
) -> SubmissionAcceptedResponse:
    """Receive a contact message and forward it to the team. Stores nothing."""
    response.headers["Cache-Control"] = "no-store"
    return _accept(
        request,
        payload,
        source="contact",
        ip_limiter=_contact_ip,
        global_limiter=_contact_all,
        inbox=contact_inbox(),
        build=_contact_notification,
    )


@router.post(
    "/api/submissions/store-suggestion",
    response_model=SubmissionAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@router.post(
    "/api/v1/submissions/store-suggestion",
    response_model=SubmissionAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=True,
)
def submit_store_suggestion(
    payload: StoreSuggestCreateRequest,
    request: Request,
    response: Response,
) -> SubmissionAcceptedResponse:
    """Receive a store suggestion for manual review. Never scrapes the URL."""
    response.headers["Cache-Control"] = "no-store"
    return _accept(
        request,
        payload,
        source="store-suggestion",
        ip_limiter=_store_ip,
        global_limiter=_store_all,
        inbox=store_inbox(),
        build=_store_notification,
    )
