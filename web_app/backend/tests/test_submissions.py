"""Tests for the zero-DB public forms: sanitizers, notifier chain, anti-spam, endpoints.

Every network call is mocked; no test sends real email or Telegram messages.
"""

from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import httpx  # noqa: E402

from app import antispam, notify  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import submissions  # noqa: E402
from app.sanitize import (  # noqa: E402
    http_url,
    multiline,
    normalize_email,
    normalize_whatsapp,
    one_line,
)

# Every knob the forms read. Tests blank them all so a developer's real secrets
# in the shell can never leak into a test run.
_NOTIFY_KEYS = (
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
    "CONTACT_TO_EMAIL",
    "ADD_STORE_TO_EMAIL",
    "TURNSTILE_SITE_KEY",
    "TURNSTILE_SECRET_KEY",
)

RESEND_READY = {"RESEND_API_KEY": "re_test_key", "CONTACT_TO_EMAIL": "team@asarak.com"}

CONTACT = {
    "category": "general",
    "name": "سارة",
    "email": "Sara@Example.com",
    "message": "هل التطبيق متاح على iOS؟ شكراً لكم.",
}
STORE_OWNER = {
    "kind": "owner",
    "store_name": "متجر النيل",
    "store_url": "https://example-store.com/ar",
    "platform": "salla_zid",
    "contact_email": "owner@example-store.com",
    "contact_whatsapp": "010 1234 5678",
    "notes": "متجر إلكترونيات يعمل من القاهرة.",
}


@contextmanager
def notify_env(**overrides: str) -> Iterator[None]:
    values = {key: "" for key in _NOTIFY_KEYS}
    values.update(overrides)
    with patch.dict(os.environ, values, clear=False):
        yield


def _http(status_code: int, payload: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = payload if payload is not None else {}
    return resp


def _resend_ok() -> MagicMock:
    return _http(200, {"id": "email_123"})


def _reset_limiters() -> None:
    for limiter in (
        submissions._contact_ip,
        submissions._contact_all,
        submissions._store_ip,
        submissions._store_all,
    ):
        limiter.reset()


class TestSanitize(unittest.TestCase):
    def test_one_line_collapses_breaks_and_strips_spoofing_chars(self) -> None:
        bidi = "\u202Ereversed\u202C"
        self.assertEqual(one_line("  Ali\r\nBadr\u202E\x00  Gamal  "), "Ali Badr Gamal")
        self.assertEqual(one_line(bidi), "reversed")
        self.assertEqual(one_line("x" * 500, max_len=10), "x" * 10)

    def test_multiline_keeps_paragraph_breaks_only(self) -> None:
        dirty = "Line 1\r\nLine 2\r\n\n\n\nLine 3\x07\b"
        self.assertEqual(multiline(dirty), "Line 1\nLine 2\n\nLine 3")
        self.assertEqual(multiline("x" * 10, max_len=4), "xxxx")
        self.assertEqual(multiline("\u2066hidden\u2069 text"), "hidden text")

    def test_normalize_email(self) -> None:
        self.assertEqual(normalize_email("  Person@Example.COM "), "person@example.com")
        self.assertIsNone(normalize_email("not-an-email"))
        self.assertIsNone(normalize_email("a@b"))
        self.assertIsNone(normalize_email("a@b.com\r\nBcc: victim@x.com"))

    def test_normalize_whatsapp(self) -> None:
        self.assertEqual(normalize_whatsapp("010 1234 5678"), "+201012345678")
        self.assertEqual(normalize_whatsapp("+20 101-234-5678"), "+201012345678")
        self.assertEqual(normalize_whatsapp("00201012345678"), "+201012345678")
        self.assertEqual(normalize_whatsapp("+1 415 555 2671"), "+14155552671")
        self.assertIsNone(normalize_whatsapp("abc"))
        self.assertIsNone(normalize_whatsapp("+20"))

    def test_http_url_is_syntax_only(self) -> None:
        self.assertEqual(http_url(" https://Example-Store.com/ar/shop "), "https://Example-Store.com/ar/shop")
        self.assertEqual(http_url("http://2b.com.eg:8080/p?x=1#f"), "http://2b.com.eg:8080/p?x=1#f")
        for invalid in (
            "javascript:alert(1)",
            "ftp://store.com",
            "https://user:pw@store.com",
            "https://asarak.com@evil.example/",
            "http://localhost/admin",
            "http://127.0.0.1/",
            "http://192.168.1.5/",
            "http://printer.local/",
            "https://no-dot/",
            "https://",
            "not a url",
            "https://exa mple.com",
            "https://[::1]/",
            "https://" + "a" * 2048 + ".com",
            "",
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(http_url(invalid))


class TestNotify(unittest.TestCase):
    def test_env_int_treats_blank_and_garbage_as_default(self) -> None:
        with patch.dict(os.environ, {"SMTP_PORT": ""}):
            self.assertEqual(notify.env_int("SMTP_PORT", 587, lo=1, hi=65535), 587)
        with patch.dict(os.environ, {"SMTP_PORT": "not-a-number"}):
            self.assertEqual(notify.env_int("SMTP_PORT", 587, lo=1, hi=65535), 587)
        with patch.dict(os.environ, {"SMTP_PORT": "99999"}):
            self.assertEqual(notify.env_int("SMTP_PORT", 587, lo=1, hi=65535), 65535)

    def test_email_providers_priority(self) -> None:
        with notify_env():
            self.assertEqual(notify.email_providers(), ())
        with notify_env(RESEND_API_KEY="k"):
            self.assertEqual(notify.email_providers(), ("resend",))
        with notify_env(SMTP_HOST="smtp.x", SMTP_USER="u", SMTP_PASS="p"):
            self.assertEqual(notify.email_providers(), ("smtp",))
        with notify_env(RESEND_API_KEY="k", SMTP_HOST="smtp.x", SMTP_USER="u", SMTP_PASS="p"):
            self.assertEqual(notify.email_providers(), ("resend", "smtp"))
        with notify_env(SMTP_HOST="smtp.x", SMTP_USER="u", SMTP_PASS="   "):
            self.assertEqual(notify.email_providers(), ())  # incomplete SMTP is not a provider

    def test_send_email_without_provider_never_touches_network(self) -> None:
        with notify_env(), patch("app.notify.httpx.post") as post, patch("app.notify.smtplib.SMTP") as smtp:
            result = notify.send_email("a@b.com", "s", "b")
        self.assertFalse(result.ok)
        self.assertIn("no email provider", result.reason)
        post.assert_not_called()
        smtp.assert_not_called()

    def test_send_email_via_resend(self) -> None:
        with notify_env(**RESEND_READY, RESEND_FROM_EMAIL="notify@asarak.com"), patch(
            "app.notify.httpx.post", return_value=_resend_ok()
        ) as post:
            result = notify.send_email("shopper@example.com", "مرحبا", "body")
        self.assertEqual(result, notify.SendResult(True, "resend"))
        self.assertEqual(post.call_args.args[0], "https://api.resend.com/emails")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer re_test_key")
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"from": "Asarak <notify@asarak.com>", "to": ["shopper@example.com"], "subject": "مرحبا", "text": "body"},
        )

    def test_resend_failure_falls_back_to_smtp_with_blank_port(self) -> None:
        """Regression: a blank SMTP_PORT (missing GitHub secret) used to raise ValueError."""
        smtp_env = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "", "SMTP_USER": "u", "SMTP_PASS": "p"}
        with notify_env(RESEND_API_KEY="k", **smtp_env), patch(
            "app.notify.httpx.post", return_value=_http(500, {"message": "upstream down"})
        ), patch("app.notify.smtplib.SMTP") as smtp_cls:
            result = notify.send_email("a@b.com", "subject", "body")
        self.assertEqual(result, notify.SendResult(True, "smtp"))
        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=notify.SMTP_TIMEOUT_SECONDS)
        server = smtp_cls.return_value.__enter__.return_value
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("u", "p")
        sent = server.send_message.call_args.args[0]
        self.assertEqual(sent["To"], "a@b.com")
        self.assertEqual(sent["Subject"], "subject")

    def test_all_email_providers_fail_without_leaking_the_key(self) -> None:
        with notify_env(RESEND_API_KEY="re_secret_value"), patch(
            "app.notify.httpx.post", return_value=_http(401, {"message": "API key is invalid"})
        ):
            result = notify.send_email("a@b.com", "s", "b")
        self.assertEqual(result, notify.SendResult(False, "resend", "resend: HTTP 401: API key is invalid"))
        self.assertNotIn("re_secret_value", result.reason)

    def test_send_telegram(self) -> None:
        with notify_env(), patch("app.notify.httpx.post") as post:
            self.assertFalse(notify.send_telegram("123", "hi").ok)
        post.assert_not_called()

        with notify_env(TELEGRAM_BOT_TOKEN="123:ABC"), patch("app.notify.httpx.post", return_value=_http(200)) as post:
            self.assertEqual(notify.send_telegram("123", "hi"), notify.SendResult(True, "telegram"))
        self.assertEqual(post.call_args.args[0], "https://api.telegram.org/bot123:ABC/sendMessage")
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "123")

        rejected = _http(400, {"ok": False, "description": "Bad Request: chat not found"})
        with notify_env(TELEGRAM_BOT_TOKEN="123:ABC"), patch("app.notify.httpx.post", return_value=rejected):
            result = notify.send_telegram("@someone", "hi")
        self.assertFalse(result.ok)
        self.assertIn("chat not found", result.reason)
        self.assertNotIn("123:ABC", result.reason)  # the URL carries the token; never surface it

        with notify_env(TELEGRAM_BOT_TOKEN="123:ABC"), patch(
            "app.notify.httpx.post", side_effect=httpx.ConnectError("boom")
        ):
            result = notify.send_telegram("123", "hi")
        self.assertEqual(result, notify.SendResult(False, "telegram", "telegram: ConnectError"))


class TestAntiSpam(unittest.TestCase):
    def test_rate_limiter_window(self) -> None:
        limiter = antispam.RateLimiter(
            limit_env="_T_LIMIT", default_limit=2, window_env="_T_WINDOW", default_window=60
        )
        clock = {"now": 1000.0}
        with patch("app.antispam.time.monotonic", side_effect=lambda: clock["now"]):
            self.assertEqual(limiter.allow("k"), (True, 0))
            self.assertEqual(limiter.allow("k"), (True, 0))
            allowed, retry_after = limiter.allow("k")
            self.assertFalse(allowed)
            self.assertEqual(retry_after, 60)
            self.assertEqual(limiter.allow("other"), (True, 0))  # per key
            clock["now"] += 61
            self.assertEqual(limiter.allow("k"), (True, 0))  # window expired

    def test_rate_limiter_bounds_its_key_set(self) -> None:
        limiter = antispam.RateLimiter(
            limit_env="_T_LIMIT", default_limit=5, window_env="_T_WINDOW", default_window=60, max_keys=3
        )
        for key in ("a", "b", "c", "d"):
            limiter.allow(key)
        self.assertEqual(len(limiter._hits), 3)
        self.assertNotIn("a", limiter._hits)
        limiter.reset()
        self.assertEqual(len(limiter._hits), 0)

    def test_enforce_rate_limit_hashes_the_ip(self) -> None:
        ip_limiter = antispam.RateLimiter(limit_env="_T_LIMIT", default_limit=5, window_env="_T_WINDOW", default_window=60)
        all_limiter = antispam.RateLimiter(limit_env="_T_LIMIT", default_limit=5, window_env="_T_WINDOW", default_window=60)
        self.assertEqual(antispam.enforce_rate_limit(ip_limiter, all_limiter, "203.0.113.9"), (True, 0))
        stored = next(iter(ip_limiter._hits))
        self.assertTrue(stored.startswith("ip:"))
        self.assertNotIn("203.0.113.9", stored)

    def _request(self, headers: dict[str, str] | None = None) -> MagicMock:
        headers = headers or {}
        request = MagicMock()
        request.headers.get.side_effect = lambda name, default="": headers.get(name, default)
        request.client.host = "10.0.0.1"
        return request

    def test_client_ip_prefers_cloudflare_then_last_forwarded_hop(self) -> None:
        self.assertEqual(antispam.client_ip(self._request({"cf-connecting-ip": "198.51.100.1"})), "198.51.100.1")
        spoofed_then_real = {"x-forwarded-for": "1.1.1.1, 203.0.113.7"}
        self.assertEqual(antispam.client_ip(self._request(spoofed_then_real)), "203.0.113.7")
        self.assertEqual(antispam.client_ip(self._request({"x-forwarded-for": " , "})), "10.0.0.1")
        request = MagicMock()
        request.headers.get.return_value = ""
        request.client = None
        self.assertEqual(antispam.client_ip(request), "unknown")

    def test_turnstile_off_passes_without_network(self) -> None:
        with notify_env(), patch("app.antispam.httpx.post") as post:
            self.assertEqual(antispam.verify_turnstile("", "203.0.113.9"), (True, "disabled"))
        post.assert_not_called()

    def test_turnstile_on_fails_closed(self) -> None:
        on = {"TURNSTILE_SECRET_KEY": "sec", "TURNSTILE_SITE_KEY": "site-key"}
        with notify_env(**on), patch("app.antispam.httpx.post") as post:
            passed, reason = antispam.verify_turnstile("", "203.0.113.9")
        self.assertFalse(passed)
        self.assertEqual(reason, "missing token")
        post.assert_not_called()

        with notify_env(**on), patch("app.antispam.httpx.post", return_value=_http(200, {"success": True})):
            self.assertEqual(antispam.verify_turnstile("tok", "203.0.113.9"), (True, "ok"))

        rejected = _http(200, {"success": False, "error-codes": ["invalid-input-response"]})
        with notify_env(**on), patch("app.antispam.httpx.post", return_value=rejected):
            self.assertEqual(
                antispam.verify_turnstile("tok", "203.0.113.9"),
                (False, "rejected: invalid-input-response"),
            )

        with notify_env(**on), patch("app.antispam.httpx.post", return_value=_http(500)):
            self.assertEqual(antispam.verify_turnstile("tok", "203.0.113.9"), (False, "siteverify HTTP 500"))
        with notify_env(**on), patch("app.antispam.httpx.post", side_effect=httpx.ConnectError("down")):
            self.assertEqual(antispam.verify_turnstile("tok", "203.0.113.9"), (False, "siteverify unreachable"))


class TestSubmissionsApi(unittest.TestCase):
    def setUp(self) -> None:
        _reset_limiters()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        _reset_limiters()

    def test_config_reports_disabled_and_is_never_cached(self) -> None:
        with notify_env(), patch("app.notify.httpx.post") as post:
            resp = self.client.get("/api/submissions/config")
            alias = self.client.get("/api/v1/submissions/config")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"form_enabled": False, "turnstile_site_key": ""})
        self.assertEqual(resp.headers["cache-control"], "no-store")
        self.assertEqual(alias.json(), resp.json())
        post.assert_not_called()

    def test_config_enabled_by_resend_inbox_or_telegram_chat(self) -> None:
        with notify_env(**RESEND_READY):
            self.assertTrue(self.client.get("/api/submissions/config").json()["form_enabled"])
        with notify_env(**RESEND_READY, TURNSTILE_SITE_KEY="site-key", TURNSTILE_SECRET_KEY="sec"):
            self.assertEqual(
                self.client.get("/api/submissions/config").json(),
                {"form_enabled": True, "turnstile_site_key": "site-key"},
            )
        with notify_env(TELEGRAM_BOT_TOKEN="t", TELEGRAM_NOTIFY_CHAT_ID="-100123"):
            self.assertTrue(self.client.get("/api/submissions/config").json()["form_enabled"])
        with notify_env(RESEND_API_KEY="k"):  # provider but no inbox
            self.assertFalse(self.client.get("/api/submissions/config").json()["form_enabled"])

    def test_contact_accepted_and_forwarded(self) -> None:
        with notify_env(**RESEND_READY), patch("app.notify.httpx.post", return_value=_resend_ok()) as post:
            resp = self.client.post("/api/submissions/contact", json=CONTACT)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["status"], "received")
        self.assertEqual(resp.headers["cache-control"], "no-store")
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["to"], ["team@asarak.com"])
        self.assertEqual(sent["subject"], "[Asarak] Contact · استفسار عام · sara@example.com")
        self.assertIn("Category:   استفسار عام (general)", sent["text"])
        self.assertIn(CONTACT["message"], sent["text"])
        self.assertIn("Sender IP:  testclient", sent["text"])

        with notify_env(**RESEND_READY), patch("app.notify.httpx.post", return_value=_resend_ok()) as post:
            self.assertEqual(self.client.post("/api/v1/submissions/contact", json=CONTACT).status_code, 202)
        self.assertEqual(post.call_args.kwargs["json"]["to"], ["team@asarak.com"])

    def test_contact_without_channel_is_503_and_uncacheable(self) -> None:
        with notify_env(), patch("app.notify.httpx.post") as post:
            resp = self.client.post("/api/submissions/contact", json=CONTACT)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["detail"], "notification_channel_unconfigured")
        self.assertEqual(resp.headers["cache-control"], "no-store")
        post.assert_not_called()

    def test_provider_outage_is_503(self) -> None:
        with notify_env(**RESEND_READY), patch("app.notify.httpx.post", return_value=_http(500)):
            resp = self.client.post("/api/submissions/contact", json=CONTACT)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["detail"], "notification_send_failed")

    def test_honeypot_answers_like_success_but_sends_nothing(self) -> None:
        bot = {**CONTACT, "website": "http://spam.example"}
        with notify_env(**RESEND_READY), patch("app.notify.httpx.post") as post:
            resp = self.client.post("/api/submissions/contact", json=bot)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["status"], "received")
        post.assert_not_called()

    def test_rate_limit_per_ip_then_global_budget(self) -> None:
        headers = {"cf-connecting-ip": "203.0.113.9"}
        with notify_env(**RESEND_READY), patch("app.notify.httpx.post", return_value=_resend_ok()):
            for _ in range(5):
                self.assertEqual(self.client.post("/api/submissions/contact", json=CONTACT, headers=headers).status_code, 202)
            blocked = self.client.post("/api/submissions/contact", json=CONTACT, headers=headers)
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked.json()["detail"], "rate_limited")
            self.assertEqual(blocked.headers["cache-control"], "no-store")
            self.assertLessEqual(int(blocked.headers["retry-after"]), 600)
            self.assertEqual(
                self.client.post(
                    "/api/submissions/contact", json=CONTACT, headers={"cf-connecting-ip": "203.0.113.10"}
                ).status_code,
                202,  # another visitor is unaffected
            )

        _reset_limiters()
        with notify_env(**RESEND_READY, CONTACT_GLOBAL_RATE_LIMIT="2"), patch(
            "app.notify.httpx.post", return_value=_resend_ok()
        ):
            codes = [
                self.client.post(
                    "/api/submissions/contact", json=CONTACT, headers={"cf-connecting-ip": f"198.51.100.{i}"}
                ).status_code
                for i in range(4)
            ]
        self.assertEqual(codes, [202, 202, 429, 429])  # rotating IPs cannot exceed the outbound budget

    def test_turnstile_required_when_configured(self) -> None:
        on = {**RESEND_READY, "TURNSTILE_SECRET_KEY": "sec"}
        with notify_env(**on), patch("app.notify.httpx.post") as post:
            resp = self.client.post("/api/submissions/contact", json=CONTACT)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "turnstile_failed")
        post.assert_not_called()

        with notify_env(**on), patch(
            "app.notify.httpx.post", side_effect=[_http(200, {"success": True}), _resend_ok()]
        ) as post:
            resp = self.client.post("/api/submissions/contact", json={**CONTACT, "turnstile_token": "tok"})
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(post.call_count, 2)
        verify, email = (call.kwargs for call in post.call_args_list)
        self.assertEqual(verify["data"]["response"], "tok")
        self.assertEqual(email["json"]["to"], ["team@asarak.com"])

    def test_contact_validation(self) -> None:
        cases = {
            "bad email": {**CONTACT, "email": "nope"},
            "short message": {**CONTACT, "message": "قصيرة"},
            "unknown category": {**CONTACT, "category": "other"},
            "price error without url": {**CONTACT, "category": "price_error"},
            "price error with junk url": {**CONTACT, "category": "price_error", "product_url": "javascript:alert(1)"},
        }
        with notify_env(**RESEND_READY), patch("app.notify.httpx.post", return_value=_resend_ok()) as post:
            for label, payload in cases.items():
                with self.subTest(case=label):
                    self.assertEqual(self.client.post("/api/submissions/contact", json=payload).status_code, 422)
            ok = self.client.post(
                "/api/submissions/contact",
                json={**CONTACT, "category": "price_error", "product_url": "https://asarak.com/products/abc"},
            )
        self.assertEqual(ok.status_code, 202)
        post.assert_called_once()
        self.assertIn("Product:    https://asarak.com/products/abc", post.call_args.kwargs["json"]["text"])

    def test_contact_delivered_through_telegram_only(self) -> None:
        with notify_env(TELEGRAM_BOT_TOKEN="t", TELEGRAM_NOTIFY_CHAT_ID="-100123"), patch(
            "app.notify.httpx.post", return_value=_http(200)
        ) as post:
            resp = self.client.post("/api/submissions/contact", json=CONTACT)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], "https://api.telegram.org/bott/sendMessage")
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "-100123")

    def test_telegram_is_the_fallback_when_email_fails(self) -> None:
        with notify_env(**RESEND_READY, TELEGRAM_BOT_TOKEN="t", TELEGRAM_NOTIFY_CHAT_ID="-100123"), patch(
            "app.notify.httpx.post", side_effect=[_http(500), _http(200)]
        ) as post:
            resp = self.client.post("/api/submissions/contact", json=CONTACT)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(post.call_count, 2)
        self.assertIn("api.telegram.org", post.call_args.args[0])

    def test_store_suggestion_and_owner_request(self) -> None:
        suggest = {"kind": "suggest", "store_name": "متجر القاهرة", "store_url": "https://cairo-shop.com"}
        sent: list[Any] = []
        with notify_env(**RESEND_READY), patch(
            "app.notify.httpx.post", return_value=_resend_ok()
        ) as post, patch("socket.getaddrinfo", side_effect=AssertionError("network access")), patch(
            "socket.create_connection", side_effect=AssertionError("network access")
        ):
            resp = self.client.post("/api/submissions/store-suggestion", json=suggest)
            self.assertEqual(resp.status_code, 202)
            resp = self.client.post("/api/v1/submissions/store-suggestion", json=STORE_OWNER)
            self.assertEqual(resp.status_code, 202)
            sent = [call.kwargs["json"] for call in post.call_args_list]
        # Only the mail provider was ever contacted: the submitted URLs were never fetched.
        self.assertTrue(all(call.args[0] == "https://api.resend.com/emails" for call in post.call_args_list))

        self.assertIn("Type:       مستخدم يقترح متجر (suggest)", sent[0]["text"])
        self.assertIn("URL:        https://cairo-shop.com", sent[0]["text"])
        self.assertIn("Platform:   -", sent[0]["text"])
        self.assertEqual(sent[1]["subject"], "[Asarak] Store request · متجر النيل")
        self.assertIn("Platform:   سلة / زد (salla_zid)", sent[1]["text"])
        self.assertIn("Contact:    owner@example-store.com · +201012345678", sent[1]["text"])
        self.assertIn("Manual review only", sent[1]["text"])

    def test_store_owner_requirements(self) -> None:
        cases = {
            "missing platform": {**STORE_OWNER, "platform": None},
            "no contact": {k: v for k, v in STORE_OWNER.items() if not k.startswith("contact_")},
            "bad email": {**STORE_OWNER, "contact_email": "nope", "contact_whatsapp": ""},
            "bad whatsapp": {**STORE_OWNER, "contact_email": "", "contact_whatsapp": "abc"},
            "bad url": {**STORE_OWNER, "store_url": "http://localhost/shop"},
            "missing url": {k: v for k, v in STORE_OWNER.items() if k != "store_url"},
            "short name": {**STORE_OWNER, "store_name": "م"},
        }
        with notify_env(**RESEND_READY), patch("app.notify.httpx.post") as post:
            for label, payload in cases.items():
                with self.subTest(case=label):
                    self.assertEqual(
                        self.client.post("/api/submissions/store-suggestion", json=payload).status_code, 422
                    )
        post.assert_not_called()

    def test_store_inbox_can_differ_from_contact_inbox(self) -> None:
        with notify_env(**RESEND_READY, ADD_STORE_TO_EMAIL="stores@asarak.com"), patch(
            "app.notify.httpx.post", return_value=_resend_ok()
        ) as post:
            self.client.post("/api/submissions/contact", json=CONTACT)
            self.client.post("/api/submissions/store-suggestion", json=STORE_OWNER)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["to"], ["team@asarak.com"])
        self.assertEqual(post.call_args_list[1].kwargs["json"]["to"], ["stores@asarak.com"])


if __name__ == "__main__":
    unittest.main()
