"""Send one real test notification through the configured provider — no database.

Verifies email / Telegram credentials exactly as the alert checker uses them,
without creating or touching any ``public.price_alerts`` row.

Usage:
    python web_app/backend/jobs/send_test_notification.py --to you@example.com
    python web_app/backend/jobs/send_test_notification.py --to you@example.com --dry-run
    python web_app/backend/jobs/send_test_notification.py --telegram --chat-id 123456789
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.notify import email_providers, env_str, send_email, send_telegram  # noqa: E402
from app.sanitize import normalize_email  # noqa: E402

_TEST_SUBJECT = "[Asarak] Test notification — ignore"
_TEST_BODY = (
    "This is a test message from Asarak (أسعارك).\n\n"
    "If you received it, the configured notification provider is working. "
    "No database rows were created or changed."
)

EXIT_OK = 0
EXIT_SEND_FAILED = 1
EXIT_NOT_CONFIGURED = 2


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Send one test notification through the configured provider.")
    parser.add_argument("--to", dest="to_email", help="Inbox that receives the test email.")
    parser.add_argument("--telegram", action="store_true", help="Use the Telegram bot instead of email.")
    parser.add_argument("--chat-id", help="Telegram chat ID (defaults to TELEGRAM_NOTIFY_CHAT_ID).")
    parser.add_argument("--dry-run", action="store_true", help="Only report the configuration; send nothing.")
    args = parser.parse_args(argv)

    providers = email_providers()
    telegram_ready = bool(env_str("TELEGRAM_BOT_TOKEN"))
    print(f"Email providers configured: {', '.join(providers) if providers else 'NONE'}")
    print(f"Telegram bot configured:    {'yes' if telegram_ready else 'NO'}")

    if not providers and not telegram_ready:
        print(
            "Nothing is configured. Set RESEND_API_KEY (or SMTP_HOST + SMTP_USER + SMTP_PASS), "
            "or TELEGRAM_BOT_TOKEN, then retry."
        )
        return EXIT_NOT_CONFIGURED
    if args.dry_run:
        print("Dry run: nothing was sent.")
        return EXIT_OK

    if args.telegram:
        chat_id = (args.chat_id or env_str("TELEGRAM_NOTIFY_CHAT_ID")).strip()
        if not chat_id:
            print("Pass --chat-id (or set TELEGRAM_NOTIFY_CHAT_ID) for a Telegram test.")
            return EXIT_NOT_CONFIGURED
        result = send_telegram(chat_id, f"{_TEST_SUBJECT}\n\n{_TEST_BODY}")
    else:
        recipient = normalize_email(args.to_email or "")
        if recipient is None:
            print("Pass a valid --to <email> for an email test.")
            return EXIT_NOT_CONFIGURED
        result = send_email(recipient, _TEST_SUBJECT, _TEST_BODY)

    if result.ok:
        print(f"SENT via {result.provider}.")
        return EXIT_OK
    print(f"FAILED — {result.reason}")
    return EXIT_SEND_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
