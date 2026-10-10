"""Security headers, CSRF (Origin/Referer) check and friendly HTML error pages."""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Templates use only /static/app.js and /static/style.css (no inline scripts, styles or handlers).
# form-action allows PayPal for the buyer-approval fallback redirect.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
       "form-action 'self' https://www.sandbox.paypal.com https://www.paypal.com")
HEADERS = {
    "Content-Security-Policy": CSP,
    "Strict-Transport-Security": "max-age=31536000",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_of(url: str) -> str | None:
    p = urlsplit(url)
    return p.netloc.lower() if p.scheme in ("http", "https") and p.netloc else None


def same_origin(request: Request) -> bool:
    """Browsers send Origin on every cross-site (and same-site) form POST; an attacker page can't
    forge it. Requests with neither Origin nor Referer are not from a browser form (curl, scripts,
    tests) and so are not a CSRF vector; they are allowed. 'Origin: null' is rejected."""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").lower()
    origin = request.headers.get("origin")
    if origin is not None:
        return _origin_of(origin) == host
    referer = request.headers.get("referer")
    if referer is not None:
        return _origin_of(referer) == host
    return True


def install_security(app, templates, csrf_exempt: tuple[str, ...] = ()) -> None:
    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method in UNSAFE and request.url.path not in csrf_exempt and not same_origin(request):
            resp = HTMLResponse(page("Request blocked", "This action must be started from the TradeOS page "
                                     "itself (cross-site request refused)."), status_code=403)
        else:
            resp = await call_next(request)
        for k, v in HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        wants_html = "text/html" in request.headers.get("accept", "") and not request.url.path.startswith("/api/")
        if not wants_html:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        title = "Page not found" if exc.status_code == 404 else f"Error {exc.status_code}"
        msg = ("That page or case doesn't exist (the shared demo may have been reset)."
               if exc.status_code == 404 else str(exc.detail))
        return HTMLResponse(page(title, msg), status_code=exc.status_code)


def page(title: str, message: str) -> str:
    from html import escape
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{escape(title)} · TradeOS</title>'
            f'<link rel="stylesheet" href="/static/style.css"></head><body><main class="error-page">'
            f'<h1>{escape(title)}</h1><p>{escape(message)}</p><p><a class="btn" href="/">Back to the TradeOS dashboard</a>'
            f'</p></main></body></html>')
