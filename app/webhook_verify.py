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
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

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
    try:
        cert.public_key().verify(signature, signed_message(tid, ttime, webhook_id, raw_body),
                                 padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return "FAILURE"
    except Exception as exc:  # e.g. non-RSA key
        raise SelfVerifyUnavailable(f"cannot check signature: {type(exc).__name__}") from exc
    return "SUCCESS"


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
