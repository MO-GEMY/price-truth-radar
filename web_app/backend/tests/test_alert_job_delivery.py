"""Delivery-path tests for the price-drop alert checker job and the test-send CLI.

Every provider is mocked: nothing here sends email or Telegram messages, and no
database is touched (the connection is a double).
"""

from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from jobs import check_price_alerts, send_test_notification as cli  # noqa: E402

_PROVIDER_KEYS = (
    "RESEND_API_KEY",
    "RESEND_FROM_EMAIL",
    "RESEND_FROM_NAME",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASS",
    "SMTP_FROM",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_NOTIFY_CHAT_ID",
)

SMTP_READY = {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "user", "SMTP_PASS": "pass"}


@contextmanager
def provider_env(**overrides: str) -> Iterator[None]:
    values = {key: "" for key in _PROVIDER_KEYS}
    values.update(overrides)
    with patch.dict(os.environ, values, clear=False):
        yield


def _http(status_code: int, payload: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = payload if payload is not None else {}
    return resp


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "_Rows":
        return self

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Connection double: one active alert and one in-stock listing below target."""

    def __init__(self, channel: str = "email") -> None:
        self.alert = {
            "id": 7,
            "product_key": "iphone_16",
            "product_title": "iPhone 16",
            "store_name": None,
            "target_price": 46000.0,
            "channel": channel,
            "destination": "shopper@example.com" if channel == "email" else "@shopper",
        }
        self.match = {
            "product_sk": "sk_ip16",
            "canonical_product_key": "iphone_16",
            "product_title": "iPhone 16 128GB",
            "store_name": "btech",
            "current_price": 44999.0,
            "product_url": "https://btech.com/iphone-16",
        }
        self.marked: list[Any] = []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _Rows:
        sql = str(stmt)
        p = params or {}
        if "CREATE TABLE" in sql:
            return _Rows([])
        if "UPDATE public.price_alerts" in sql:
            self.marked.append(p["alert_id"])
            return _Rows([])
        if "FROM public.price_alerts" in sql:
            return _Rows([self.alert])
        if "FROM gold.mart_product_verdicts" in sql:
            return _Rows([self.match])
        raise AssertionError(f"Unexpected SQL: {sql}")


class TestAlertJobEmailDelivery(unittest.TestCase):
    def test_unconfigured_email_alert_is_counted_and_left_active(self) -> None:
        conn = _FakeConn()
        with provider_env(), patch("app.notify.httpx.post") as post, patch("app.notify.smtplib.SMTP") as smtp:
            summary = check_price_alerts.check_alerts_with_conn(conn)
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["delivered"], 0)
        self.assertEqual(summary["dry_run_skipped"], 0)
        self.assertEqual(summary["unconfigured_skipped"], 1)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(conn.marked, [])
        post.assert_not_called()
        smtp.assert_not_called()

    def test_dry_run_never_sends(self) -> None:
        conn = _FakeConn()
        with provider_env(RESEND_API_KEY="k"), patch("app.notify.httpx.post") as post, patch(
            "app.notify.smtplib.SMTP"
        ) as smtp:
            summary = check_price_alerts.check_alerts_with_conn(conn, dry_run=True)
        self.assertEqual(summary["dry_run_skipped"], 1)
        self.assertEqual(summary["unconfigured_skipped"], 0)
        self.assertEqual(summary["delivered"], 0)
        self.assertEqual(conn.marked, [])
        post.assert_not_called()
        smtp.assert_not_called()

    def test_resend_delivers_and_deactivates(self) -> None:
        conn = _FakeConn()
        with provider_env(RESEND_API_KEY="k", RESEND_FROM_EMAIL="alerts@asarak.com"), patch(
            "app.notify.httpx.post", return_value=_http(200, {"id": "email_1"})
        ) as post, patch("app.notify.smtplib.SMTP") as smtp:
            summary = check_price_alerts.check_alerts_with_conn(conn)
        self.assertEqual(summary["delivered"], 1)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(conn.marked, [7])
        self.assertEqual(post.call_args.args[0], "https://api.resend.com/emails")
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["from"], "Asarak <alerts@asarak.com>")
        self.assertEqual(sent["to"], ["shopper@example.com"])
        self.assertTrue(sent["subject"].startswith("أسعارك (Asarak) — Price Drop Alert: iPhone 16 128GB"))
        self.assertIn("44,999.00 EGP", sent["text"])
        smtp.assert_not_called()

    def test_resend_failure_falls_back_to_smtp_with_blank_port(self) -> None:
        """Regression: an empty SMTP_PORT secret used to raise before anything was sent."""
        conn = _FakeConn()
        with provider_env(RESEND_API_KEY="k", SMTP_PORT="", **SMTP_READY), patch(
            "app.notify.httpx.post", return_value=_http(502)
        ), patch("app.notify.smtplib.SMTP") as smtp:
            summary = check_price_alerts.check_alerts_with_conn(conn)
        self.assertEqual(summary["delivered"], 1)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(conn.marked, [7])
        smtp.assert_called_once_with("smtp.example.com", 587, timeout=15.0)
        smtp.return_value.__enter__.return_value.send_message.assert_called_once()

    def test_smtp_only_setup_is_unchanged(self) -> None:
        conn = _FakeConn()
        with provider_env(SMTP_PORT="465", SMTP_FROM="alerts@asarak.com", **SMTP_READY), patch(
            "app.notify.httpx.post"
        ) as post, patch("app.notify.smtplib.SMTP") as smtp:
            summary = check_price_alerts.check_alerts_with_conn(conn)
        self.assertEqual(summary["delivered"], 1)
        self.assertEqual(conn.marked, [7])
        post.assert_not_called()
        smtp.assert_called_once_with("smtp.example.com", 465, timeout=15.0)
        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with("user", "pass")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["From"], "alerts@asarak.com")
        self.assertEqual(message["To"], "shopper@example.com")

    def test_provider_failure_keeps_alert_active_for_retry(self) -> None:
        conn = _FakeConn()
        with provider_env(RESEND_API_KEY="k"), patch(
            "app.notify.httpx.post", return_value=_http(401, {"message": "API key is invalid"})
        ):
            summary = check_price_alerts.check_alerts_with_conn(conn)
        self.assertEqual(summary["delivered"], 0)
        self.assertEqual(summary["unconfigured_skipped"], 0)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(conn.marked, [])

    def test_telegram_rejection_is_an_error_and_never_logs_the_token(self) -> None:
        conn = _FakeConn("telegram")
        rejected = _http(400, {"ok": False, "description": "Bad Request: chat not found"})
        with provider_env(TELEGRAM_BOT_TOKEN="123:ABC-SECRET"), patch("app.notify.httpx.post", return_value=rejected):
            with self.assertLogs("check_price_alerts", level="WARNING") as logs:
                summary = check_price_alerts.check_alerts_with_conn(conn)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["delivered"], 0)
        self.assertEqual(conn.marked, [])
        output = "\n".join(logs.output)
        self.assertIn("chat not found", output)
        self.assertNotIn("123:ABC-SECRET", output)


class TestSendTestNotificationCli(unittest.TestCase):
    def test_reports_nothing_configured(self) -> None:
        with provider_env(), patch("app.notify.httpx.post") as post:
            self.assertEqual(cli.main(["--to", "me@example.com"]), cli.EXIT_NOT_CONFIGURED)
        post.assert_not_called()

    def test_dry_run_sends_nothing(self) -> None:
        with provider_env(RESEND_API_KEY="k"), patch("app.notify.httpx.post") as post:
            self.assertEqual(cli.main(["--to", "me@example.com", "--dry-run"]), cli.EXIT_OK)
        post.assert_not_called()

    def test_sends_one_email_to_the_given_inbox(self) -> None:
        with provider_env(RESEND_API_KEY="k"), patch(
            "app.notify.httpx.post", return_value=_http(200, {"id": "x"})
        ) as post:
            self.assertEqual(cli.main(["--to", "Me@Example.com"]), cli.EXIT_OK)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["to"], ["me@example.com"])

    def test_send_failure_is_reported(self) -> None:
        with provider_env(RESEND_API_KEY="k"), patch("app.notify.httpx.post", return_value=_http(500)):
            self.assertEqual(cli.main(["--to", "me@example.com"]), cli.EXIT_SEND_FAILED)

    def test_rejects_invalid_recipient_before_sending(self) -> None:
        with provider_env(RESEND_API_KEY="k"), patch("app.notify.httpx.post") as post:
            self.assertEqual(cli.main(["--to", "me@example.com\r\nBcc: x@y.com"]), cli.EXIT_NOT_CONFIGURED)
        post.assert_not_called()

    def test_telegram_test(self) -> None:
        with provider_env(TELEGRAM_BOT_TOKEN="t"), patch("app.notify.httpx.post", return_value=_http(200)) as post:
            self.assertEqual(cli.main(["--telegram", "--chat-id", "123"]), cli.EXIT_OK)
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "123")
        with provider_env(TELEGRAM_BOT_TOKEN="t"), patch("app.notify.httpx.post") as post:
            self.assertEqual(cli.main(["--telegram"]), cli.EXIT_NOT_CONFIGURED)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
