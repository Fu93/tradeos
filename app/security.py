"""Same-origin / CSRF protection for state-changing form endpoints.

The dashboard is a server-rendered demo without user accounts, so the attack
surface is a cross-site form POST (CSRF). The guard:

* only accepts requests whose ``Origin`` (or, when absent, ``Referer``) matches
  the configured ``public_base_url`` host;
* browser GET navigations (no Origin header) are allowed;
* non-browser clients (curl, tests, scripts) that send no Origin/Referer at all
  are allowed -- they cannot be part of a browser-based CSRF attack.

This is deliberately dependency-free and fail-closed for real browsers.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def _host(url: str) -> str:
    parts = urlsplit(url)
    return (parts.netloc or parts.path).lower()


def same_origin_or_trusted(request, public_base_url: str) -> bool:
    """Return True when the request may perform a state-changing action."""
    origin = request.headers.get("origin") or ""
    referer = request.headers.get("referer") or ""
    if not origin and not referer:
        return True  # not a browser form submission (curl / test client / script)
    expected = {_host(public_base_url), _host(str(request.base_url))}
    source = origin or referer
    return _host(source) in expected
