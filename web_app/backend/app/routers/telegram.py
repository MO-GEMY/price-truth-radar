"""Stateless Telegram bot webhook (`POST /api/v1/telegram/webhook`).

Zero Neon DB reads or writes:
  - Verifies `X-Telegram-Bot-Api-Secret-Token` against `TELEGRAM_WEBHOOK_SECRET` (401 on mismatch).
  - When a user sends `/start` (e.g. `/start` or `/start alerts`), replies with their
    numeric `<code>{chat_id}</code>` (`parse_mode="HTML"`) and concise Arabic instructions
    to paste it into `asarak.com` for price-drop alerts.
  - Returns `200 {"ok": true}` on all other update types.
"""

from __future__ import annotations

import hmac
import html
import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.notify import env_str, send_telegram

logger = logging.getLogger(__name__)
router = APIRouter(tags=["telegram"])


def _build_start_reply_html(chat_id: str) -> str:
    safe_id = html.escape(chat_id)
    return (
        "أهلاً بك في بوت تنبيهات <b>أسعارك</b> (asarak.com) 👋\n\n"
        f"رقم المحادثة الخاص بك (Chat ID):\n<code>{safe_id}</code>\n\n"
        "اضغط على الرقم بالأعلى لنسخه، ثم الصقه في خانة تنبيهات تليجرام على "
        "<a href=\"https://asarak.com\">asarak.com</a> ليصلك تنبيه فوري عند نزول السعر."
    )


@router.post("/api/v1/telegram/webhook")
@router.post("/api/telegram/webhook", include_in_schema=True)
async def telegram_webhook(
    request: Request,
    response: Response,
    x_telegram_bot_api_secret_token: Optional[str] = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"

    expected_secret = env_str("TELEGRAM_WEBHOOK_SECRET")
    provided_secret = (x_telegram_bot_api_secret_token or "").strip()
    if (
        not expected_secret
        or not provided_secret
        or not hmac.compare_digest(provided_secret, expected_secret)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram webhook secret token.",
            headers={"Cache-Control": "no-store"},
        )

    try:
        payload: Any = await request.json()
    except Exception:
        return {"ok": True}

    if not isinstance(payload, dict):
        return {"ok": True}

    message = payload.get("message")
    if not isinstance(message, dict):
        return {"ok": True}

    raw_text = message.get("text")
    chat = message.get("chat")
    if not isinstance(raw_text, str) or not isinstance(chat, dict):
        return {"ok": True}

    text = raw_text.strip()
    chat_id = chat.get("id")
    if chat_id is None or not text.startswith("/start"):
        return {"ok": True}

    chat_id_str = str(chat_id).strip()
    if not chat_id_str:
        return {"ok": True}

    result = send_telegram(
        chat_id_str,
        _build_start_reply_html(chat_id_str),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    if not result.ok:
        logger.warning("[telegram-webhook] Failed replying to /start: %s", result.reason)

    return {"ok": True}
