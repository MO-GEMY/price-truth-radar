"""Input hygiene for text submitted through public forms.

User content is only ever forwarded to the team inside a notification; it is
never interpreted as markup or as a protocol header. These helpers bound its
length and remove characters that could break email headers or visually spoof a
message: ASCII control characters (CR/LF header injection) and Unicode bidi
controls that reorder surrounding text.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Directional embedding / isolate controls (LRE, RLE, PDF, LRO, RLO, LRI, RLI,
# FSI, PDI) plus the Arabic letter mark. Weak marks (LRM/RLM) are left alone.
_BIDI_CONTROLS = frozenset(
    chr(codepoint)
    for codepoint in (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x061C)
)

# C0 controls except tab (0x09) and newline (0x0A), plus DEL.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_INTERNATIONAL_PHONE_RE = re.compile(r"^\+\d{8,15}$")
_MAX_URL_LENGTH = 2048


def _drop_spoofing_chars(value: str) -> str:
    value = _CONTROL_CHARS.sub("", value)
    return "".join(ch for ch in value if ch not in _BIDI_CONTROLS)


def one_line(value: str, *, max_len: int = 200) -> str:
    """Single-line text: control chars removed, whitespace collapsed, length bounded."""
    cleaned = _drop_spoofing_chars(value.replace("\r", " ").replace("\n", " "))
    return re.sub(r"\s+", " ", cleaned).strip()[:max_len]


def multiline(value: str, *, max_len: int = 4000) -> str:
    """Multi-line text: line endings normalized, control chars removed, length bounded."""
    text = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "  ")
    lines = [_drop_spoofing_chars(line).rstrip() for line in text.split("\n")]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()[:max_len]


def normalize_email(value: str) -> str | None:
    """Trimmed, lower-cased email or None when malformed (same rule as price alerts)."""
    email = one_line(value, max_len=254).lower()
    return email if _EMAIL_RE.match(email) else None


def normalize_whatsapp(value: str) -> str | None:
    """E.164-style number (`+201012345678`) or None when malformed.

    A local Egyptian mobile (`01012345678`) is read as `+20`; any other number
    must arrive with its country code.
    """
    digits = re.sub(r"[\s().\-]", "", value)
    if digits.startswith("00"):
        digits = f"+{digits[2:]}"
    elif digits.startswith("0"):
        digits = f"+20{digits[1:]}"
    if not digits.startswith("+"):
        digits = f"+{digits}"
    return digits if _INTERNATIONAL_PHONE_RE.match(digits) else None


def http_url(value: str) -> str | None:
    """Return `value` when it is a syntactically valid http(s) URL, else None.

    Syntax only — the URL is never requested, resolved, or scraped. Credentials,
    IP literals, and local/internal hosts are rejected as obvious junk.
    """
    candidate = value.strip()
    if not candidate or len(candidate) > _MAX_URL_LENGTH:
        return None
    if any(ch.isspace() for ch in candidate):
        return None
    try:
        parts = urlsplit(candidate)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or port == 0:
        return None
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return None
    if not host or "." not in host:
        return None
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if ascii_host.endswith((".local", ".localhost", ".internal")):
        return None
    if all(label.isdigit() for label in ascii_host.split(".")):
        return None  # IPv4 literal
    return candidate
