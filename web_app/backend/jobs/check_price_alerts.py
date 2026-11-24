"""Price drop alert checker job for Asarak (أسعارك).

Compares active rows in `public.price_alerts` against latest prices in
`gold.mart_product_verdicts`, sends Telegram or email (Resend, then SMTP)
notifications when a provider is configured, logs clean dry-run output when
secrets are absent, and marks delivered alerts with `triggered_at = NOW(),
is_active = FALSE`.

Usage:
    python web_app/backend/jobs/check_price_alerts.py
    python web_app/backend/jobs/check_price_alerts.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.database import ensure_price_alerts_table, get_write_engine  # noqa: E402
from app.notify import email_providers, send_email, send_telegram  # noqa: E402

logger = logging.getLogger("check_price_alerts")


ACTIVE_ALERTS_SQL = text(
    """
    SELECT
        id,
        product_key,
        product_title,
        store_name,
        target_price,
        channel,
        destination
    FROM public.price_alerts
    WHERE is_active = TRUE
      AND triggered_at IS NULL
    ORDER BY created_at ASC, id ASC
    LIMIT :limit
    """
)

LATEST_PRICE_SQL = text(
    """
    SELECT
        product_sk,
        canonical_product_key,
        product_title,
        store_name,
        current_price,
        product_url
    FROM gold.mart_product_verdicts
    WHERE in_stock = TRUE
      AND (product_sk = :product_key OR canonical_product_key = :product_key)
      AND (:store_name IS NULL OR store_name = :store_name)
    ORDER BY current_price ASC, product_sk ASC
    LIMIT 1
    """
)

MARK_TRIGGERED_SQL = text(
    """
    UPDATE public.price_alerts
    SET triggered_at = NOW(),
        is_active = FALSE
    WHERE id = :alert_id
    """
)


def _format_alert_message(alert: dict[str, Any], match: dict[str, Any]) -> tuple[str, str]:
    title = str(match.get("product_title") or alert.get("product_title") or alert["product_key"])
    store = str(match.get("store_name") or alert.get("store_name") or "Egypt store")
    current_price = float(match["current_price"])
    target_price = float(alert["target_price"])
    url = str(match.get("product_url") or "")

    subject = f"أسعارك (Asarak) — Price Drop Alert: {title[:70]} is now {current_price:,.2f} EGP"
    body = (
        f"أسعارك (Asarak) — Target Price Hit!\n\n"
        f"Product: {title}\n"
        f"Store: {store}\n"
        f"Current Price: {current_price:,.2f} EGP\n"
        f"Your Target: {target_price:,.2f} EGP\n"
        f"Link: {url}\n"
    )
    return subject, body


def send_telegram_alert(destination: str, body: str, *, dry_run: bool = False) -> bool:
    """Deliver one Telegram alert. False only for dry-run / unconfigured; failures raise."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if dry_run or not token:
        reason = "dry-run flag" if dry_run else "TELEGRAM_BOT_TOKEN not configured"
        logger.info("[DRY-RUN][telegram] (%s) Would send to %s: %s", reason, destination, body.splitlines()[0])
        return False

    result = send_telegram(destination, body, token=token)
    if not result.ok:
        raise RuntimeError(result.reason)
    return True


def send_email_alert(destination: str, subject: str, body: str, *, dry_run: bool = False) -> bool:
    """Deliver one email alert via Resend, then SMTP. False only for dry-run / unconfigured."""
    if dry_run:
        logger.info("[DRY-RUN][email] (dry-run flag) Would send to %s | Subject: %s", destination, subject)
        return False
    if not email_providers():
        logger.warning(
            "[SKIPPED][email] No email provider configured (RESEND_API_KEY or "
            "SMTP_HOST/SMTP_USER/SMTP_PASS) — alert to %s stays active",
            destination,
        )
        return False

    result = send_email(destination, subject, body)
    if not result.ok:
        raise RuntimeError(result.reason)
    return True


def check_alerts_with_conn(
    conn: Connection,
    *,
    dry_run: bool = False,
    limit: int = 500,
) -> dict[str, int]:
    ensure_price_alerts_table(conn)
    alerts = conn.execute(ACTIVE_ALERTS_SQL, {"limit": limit}).mappings().all()

    summary = {
        "checked": len(alerts),
        "matched": 0,
        "delivered": 0,
        "dry_run_skipped": 0,
        "unconfigured_skipped": 0,
        "errors": 0,
    }

    for alert_row in alerts:
        alert = dict(alert_row)
        match_row = (
            conn.execute(
                LATEST_PRICE_SQL,
                {
                    "product_key": alert["product_key"],
                    "store_name": alert["store_name"] or None,
                },
            )
            .mappings()
            .first()
        )
        if match_row is None:
            continue

        match = dict(match_row)
        if float(match["current_price"]) > float(alert["target_price"]):
            continue

        summary["matched"] += 1
        subject, body = _format_alert_message(alert, match)

        try:
            if alert["channel"] == "telegram":
                delivered = send_telegram_alert(alert["destination"], body, dry_run=dry_run)
            else:
                delivered = send_email_alert(alert["destination"], subject, body, dry_run=dry_run)

            if delivered:
                conn.execute(MARK_TRIGGERED_SQL, {"alert_id": alert["id"]})
                summary["delivered"] += 1
                logger.info(
                    "Delivered & marked triggered: alert_id=%s channel=%s price=%.2f <= target=%.2f",
                    alert["id"],
                    alert["channel"],
                    float(match["current_price"]),
                    float(alert["target_price"]),
                )
            elif dry_run:
                summary["dry_run_skipped"] += 1
            else:
                # A False return outside dry-run means the channel is not configured.
                summary["unconfigured_skipped"] += 1
        except Exception as exc:
            summary["errors"] += 1
            logger.warning(
                "Failed sending alert_id=%s (%s -> %s): %s",
                alert["id"],
                alert["channel"],
                alert["destination"],
                exc,
            )

    if summary["unconfigured_skipped"]:
        logger.warning(
            "%s matched alert(s) were NOT sent: no notification provider is configured "
            "(set RESEND_API_KEY or SMTP_*, or TELEGRAM_BOT_TOKEN). They stay active.",
            summary["unconfigured_skipped"],
        )

    return summary


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Check active Asarak price drop alerts.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate alerts and log matches without sending or updating triggered_at.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum active alerts to inspect in one run (default: 500).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    engine = get_write_engine()
    with engine.begin() as conn:
        summary = check_alerts_with_conn(conn, dry_run=args.dry_run, limit=args.limit)

    logger.info("Price alert check complete: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
