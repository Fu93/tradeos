"""Self-verification of PayPal webhook signatures (PayPal's preferred method).

Per developer.paypal.com/api/rest/webhooks/rest/ ("Self verification method"):
  signed message = "<paypal-transmission-id>|<paypal-transmission-time>|<webhook id>|<crc32 of raw body, decimal>"
  signature      = base64 header paypal-transmission-sig, checked with the public key of the
                   certificate at paypal-cert-url (auth algo SHA256withRSA).
The raw body is used byte-for-byte (never re-serialised).

Safety: the certificate is fetched only over https from a *.paypal.com host under
/v1/notifications/certs/, cached in memory, and must be inside its validity window.
If the check cannot run (missing headers, unsupported algorithm, cert unreachable or not
allowed), SelfVerifyUnavailable is raised and the caller falls back to PayPal's
verify-webhook-signature API. A completed check that does not match returns "FAILURE".
"""
from __future__ import annotations

import base64
import binascii
import threading
import zlib
from typing import Any
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ALLOWED_HOST_SUFFIX = ".paypal.com"
CERT_PATH_PREFIX = "/v1/notifications/certs/"
MAX_CACHED_CERTS = 16
_cache: dict[str, x509.Certificate] = {}
_cache_lock = threading.Lock()


class SelfVerifyUnavailable(Exception):
    """The self-check could not run; use the postback API instead."""


def cert_url_allowed(url: str) -> bool:
    p = urlparse(url or "")
    host = (p.hostname or "").lower()
    return (p.scheme == "https" and p.port in (None, 443) and host.endswith(ALLOWED_HOST_SUFFIX)
            and p.path.startswith(CERT_PATH_PREFIX) and not p.username and not p.password)


def _fetch_cert(url: str, fetch, timeout: float) -> x509.Certificate:
    with _cache_lock:
        cached = _cache.get(url)
    if cached is not None:
        return cached
    try:
        pem = fetch(url, timeout)
        cert = x509.load_pem_x509_certificate(pem)
    except Exception as exc:  # network, HTTP or parse error
        raise SelfVerifyUnavailable(f"certificate unavailable: {type(exc).__name__}") from exc
    with _cache_lock:
        if len(_cache) >= MAX_CACHED_CERTS:
            _cache.pop(next(iter(_cache)))
        _cache[url] = cert
    return cert


def _http_fetch(url: str, timeout: float) -> bytes:
    resp = httpx.get(url, timeout=timeout, follow_redirects=False)
    resp.raise_for_status()
    return resp.content


def signed_message(transmission_id: str, transmission_time: str, webhook_id: str, raw_body: bytes) -> bytes:
    return f"{transmission_id}|{transmission_time}|{webhook_id}|{zlib.crc32(raw_body)}".encode()


def self_verify(headers: dict, raw_body: bytes, webhook_id: str, fetch=None, timeout: float = 5.0,
                now: datetime | None = None) -> str:
    h = {k.lower(): v for k, v in headers.items()}
    tid, ttime = h.get("paypal-transmission-id"), h.get("paypal-transmission-time")
    sig_b64, cert_url = h.get("paypal-transmission-sig"), h.get("paypal-cert-url")
    algo = h.get("paypal-auth-algo", "")
    if not (tid and ttime and sig_b64 and cert_url and webhook_id):
        raise SelfVerifyUnavailable("missing PayPal transmission headers")
    if algo and algo != "SHA256withRSA":
        raise SelfVerifyUnavailable(f"unsupported auth algo {algo}")
    if not cert_url_allowed(cert_url):
        return "FAILURE"  # a cert from anywhere but PayPal is never trusted (and never fetched)
    try:
        signature = base64.b64decode(sig_b64, validate=True)
    except (binascii.Error, ValueError):
        return "FAILURE"
    cert = _fetch_cert(cert_url, fetch or _http_fetch, timeout)
    now = now or datetime.now(timezone.utc)
    if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
        return "FAILURE"
    public_key = cert.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        return "FAILURE"  # PayPal signs with RSA; any other key type is not a PayPal certificate
    try:
        public_key.verify(signature, signed_message(tid, ttime, webhook_id, raw_body),
                          padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return "FAILURE"
    except Exception as exc:  # e.g. non-RSA key
        raise SelfVerifyUnavailable(f"cannot check signature: {type(exc).__name__}") from exc
    return "SUCCESS"


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --- untrusted payload shaping (OWASP: a valid signature proves the sender, not that the JSON is sane) ---
def _text(value: Any, limit: int) -> str | None:
    """Untrusted scalar -> short valid-UTF-8 string, else None. bool/float/dict/list/huge ints are rejected
    (an int is only accepted when it is small; the digits of a 10**400 int must never reach str())."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, int) and not isinstance(value, bool) and abs(value) < 10**18:
        text = str(value)
    else:
        return None
    return text[:limit].encode("utf-8", "replace").decode("utf-8") or None


def sanitize_payment_event(event: dict) -> dict:
    """Allow-list copy of a refund/capture webhook: only the fields TradeOS reads, each type-checked and
    length-bounded; everything else is dropped. Wrong-typed values become None/{} so the existing trust rules
    (verified, once, matching refund id) simply find no match instead of crashing (was: HTTP 500)."""
    res = event.get("resource")
    res = res if isinstance(res, dict) else {}
    out: dict[str, Any] = {k: _text(res.get(k), n) for k, n in
                           (("id", 255), ("status", 64), ("create_time", 64), ("update_time", 64),
                            ("note_to_payer", 500))}
    details = res.get("status_details")
    out["status_details"] = ({"reason": _text(details.get("reason"), 64)} if isinstance(details, dict) else None)
    amount = res.get("amount")
    out["amount"] = ({"value": _text(amount.get("value"), 32), "currency_code": _text(amount.get("currency_code"), 8)}
                     if isinstance(amount, dict) else None)
    links = res.get("links")
    out["links"] = [{"rel": _text(link.get("rel"), 32), "href": _text(link.get("href"), 512)}
                    for link in (links[:20] if isinstance(links, list) else []) if isinstance(link, dict)]
    return {"id": _text(event.get("id"), 120), "event_type": event.get("event_type"),
            "create_time": _text(event.get("create_time"), 64),
            "resource": {k: v for k, v in out.items() if v not in (None, [])}}
