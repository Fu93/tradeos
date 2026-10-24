"""FastAPI app: one server-rendered dashboard + a few form endpoints."""

from __future__ import annotations

import logging
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates

import anyio

from .agent_gateway import mount_mcp
from .agent_scenes import agent_panel, agent_provenance, run_scenes
from .config import Settings
from .disputes import DISPUTE_EVENTS
from .db import CaseFinalized, Database, utcnow
from .economics import case_economics
from .intent import IntentExtractor, build_extractor
from .lineitems import MoneyError, to_str as money_str
from .mixed import MIXED_STATUSES
from .notes import build_note_writer
from .paypal_client import PayPalError
from .webhook_verify import SelfVerifyUnavailable, sanitize_payment_event, self_verify
from .queue_demo import queue_view
from .presets import BY_KEY, PRESETS, preset_label
from .policy import DISPUTE_RECOMMENDATION_LABEL
from .ratelimit import Cooldown, MinInterval, RateLimiter, client_key
from .security import install_security
from .views import (ai_panel, backend_controls, evidence_a, evidence_b, failure_modes, fmt_ts, pipeline,
                    preset_for, result_card, section_title, timeline_view, evidence_log, evidence_summary, paypal_proves)
from .workflow import (AWAITING_BUYER, PENDING_APPROVAL, REFUND_ERROR, REFUND_FAILED, REFUND_UNKNOWN, RUNNABLE, MOCK_ONLY, CaseNotFound, RefundNotAllowed, SafetyNoteInvalid,
                       Workflow, clean_message)

MIXED_ATTENTION_STATUSES = tuple(x for x in MIXED_STATUSES if x != "MIXED_DONE")

BASE = Path(__file__).parent
EXCHANGE_COPY = ("Only a return leads to a refund. A size exchange goes to the supplier as a replacement request "
                 "(MOCK supplier reply in this demo) and never calls the Refund API; if the supplier is out of stock, "
                 "a person decides whether to offer a refund.")


SIGNATURE_HEADERS = ("paypal-transmission-id", "paypal-transmission-time", "paypal-transmission-sig",
                     "paypal-cert-url", "paypal-auth-algo")
log = logging.getLogger("tradeos")

WEBHOOK_EVENTS = {"PAYMENT.CAPTURE.REFUNDED", "PAYMENT.REFUND.PENDING", "PAYMENT.REFUND.FAILED",
                  "PAYMENT.CAPTURE.REVERSED", "PAYMENT.CAPTURE.DECLINED"}
# Real PayPal refund events are ~2 KB. Anything bigger is not a PayPal delivery; reject it before
# any verification call or DB write so a spammer cannot grow webhook_events / the audit chain.
WEBHOOK_MAX_BODY = 64 * 1024


def create_app(settings: Settings | None = None, paypal=None, extractor: IntentExtractor | None = None,
               today=None, note_writer=None) -> FastAPI:
    if settings is None:
        load_dotenv()
        settings = Settings.from_env()
    db = Database(settings.db_path)
    kwargs = {"today": today} if today else {}
    extractor = extractor or build_extractor(settings)
    wf = Workflow(db, settings, extractor, paypal=paypal,
                  note_writer=note_writer or build_note_writer(settings, extractor), **kwargs)
    limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_hour,
                          settings.rate_limit_global_per_hour)
    # Separate, higher budget for the money actions: a demo walkthrough (approve, retry, refresh)
    # must not be throttled by the 5/min order-creation limit, but refund attempts and reconcile
    # refreshes still stay bounded per address.
    money_limiter = RateLimiter(settings.money_rate_limit_per_minute, settings.money_rate_limit_per_hour,
                                settings.money_rate_limit_global_per_hour)

    # Render (no persistent disk) wipes the filesystem: reset + seed the demo on every start.
    db.init(reset=settings.reset_on_start)
    if not db.list_cases():
        wf.seed_demo()
    # A kept database with refunds still PENDING / outcome UNKNOWN (incl. archived cases): resolve them
    # against PayPal in the background (bounded GETs; recovery re-sends only the same PayPal-Request-Id).
    wf.resume_unresolved_refunds()

    reset_cooldown = Cooldown(settings.reset_cooldown_per_ip_s, settings.reset_cooldown_global_s)
    # Disputes reads hit PayPal (sync = 1 list + up to 10 GETs): on top of the per-IP limiter, one sync per 20 s and
    # one refresh per dispute per 10 s for the whole app, so rotating addresses cannot multiply the PayPal traffic.
    sync_gate = MinInterval(settings.disputes_sync_interval_s)
    refresh_gate = MinInterval(settings.disputes_refresh_interval_s)

    def ip(request: Request) -> str:
        return client_key(request, settings.trusted_proxy_hops, settings.trust_cf_connecting_ip)

    @asynccontextmanager
    async def lifespan(the_app: FastAPI):
        # The MCP endpoint (agent gateway) needs its session manager running for the life of the server.
        server = the_app.state.mcp_server
        if server is None:
            yield
            return
        async with server.session_manager.run():
            yield

    app = FastAPI(title="TradeOS", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.workflow = wf
    # Agent gateway at /mcp: an AI agent can request a return, never approve one (app/agent_gateway.py). Order-
    # creating tools share the dashboard's run budget (same limiter, keyed per address).
    app.state.mcp_server = mount_mcp(app, wf, settings, limiter, ip) if settings.mcp_enabled else None
    # What agents are offered, read from the server itself (shown on the dashboard, never hand-maintained). Read on
    # the first dashboard render, in a worker thread, not here: create_app() also runs at import time, and an ASGI
    # server may import the app inside its running event loop, where anyio.run() would raise.
    tool_names: list[str] = []

    def mcp_tools() -> list[str]:
        if app.state.mcp_server is not None and not tool_names:
            tool_names.extend(t.name for t in anyio.run(app.state.mcp_server.list_tools))
        return tool_names
    # One-click agent scenes create three Sandbox orders and three LLM runs, so on top of the run limiter a
    # click is allowed once a minute per address and once every 20 s for the whole demo.
    agent_cooldown = Cooldown(60, 20, action="Run agent scenes",
                              done_by_other="Someone else just ran the agent scenes")
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=BASE / "templates")
    templates.env.filters["ts"] = fmt_ts
    install_security(app, templates, csrf_exempt=("/webhooks/paypal",))

    @app.get("/api/docs", include_in_schema=False, response_class=HTMLResponse)
    def api_docs() -> HTMLResponse:
        # Swagger UI is vendored under /static/swagger (no CDN) and started by an external script, so the strict
        # Content-Security-Policy (script-src 'self') stays exactly as it is.
        return HTMLResponse(
            '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1"><title>API · TradeOS</title>'
            '<link rel="stylesheet" href="/static/swagger/swagger-ui.css"></head><body>'
            '<p class="api-back"><a href="/">← Back to the TradeOS dashboard</a> · '
            '<a href="/openapi.json">openapi.json</a></p><div id="swagger-ui"></div>'
            '<noscript>The interactive API docs need JavaScript. The raw schema is at '
            '<a href="/openapi.json">/openapi.json</a>.</noscript>'
            '<script src="/static/swagger/swagger-ui-bundle.js"></script>'
            '<script src="/static/swagger/swagger-init.js"></script></body></html>')

    def render_dashboard(request: Request, selected: str | None = None, flash: str | None = None,
                         status_code: int = 200, draft: str = "", draft_late: bool = False) -> HTMLResponse:
        cases = db.list_cases()
        current = db.get_case(selected) if selected else None
        if current is None and cases:
            current = next((c for c in cases if c["status"] != "NEW"), cases[0])
        if current and current.get("archived_at") and not flash:
            flash = (f"Case {current['id']} was archived by a demo reset at {current['archived_at']} — kept with its "
                     "audit trail (it no longer appears in the case list).")
        pending = [c for c in cases if c["status"] in (PENDING_APPROVAL, AWAITING_BUYER, REFUND_ERROR,
                                                       REFUND_UNKNOWN, REFUND_FAILED, "ERROR",
                                                       "NEEDS_HUMAN", "NEEDS_HUMAN_SAFETY_REVIEW", *MIXED_ATTENTION_STATUSES)
                   and (not current or c["id"] != current["id"])]
        if current:
            wf.auto_reconcile(current["id"], background=settings.reconcile_in_background)
        latest_a, latest_b = db.latest_case("A"), db.latest_case("B")
        proves = paypal_proves(db, current, bool(settings.paypal_webhook_id)) if current else None
        # Mixed page: poll for the signed webhook only while a COMPLETED batch refund still lacks one (never loops:
        # once the case carries webhook_status the attribute is gone).
        mixed_await = bool(current and proves and settings.paypal_webhook_id and not current.get("webhook_status")
                           and any(b["ok"] is True and b["webhook"]["state"] == "waiting" for b in proves["batches"]))
        ctx = {
            "mixed_await_webhook": mixed_await,
            "pipeline": pipeline(db, current),
            "result": result_card(db, current, bool(settings.paypal_webhook_id)),
            "section_title": section_title(current),
            "ai": ai_panel(current),
            "controls": backend_controls(db, current),
            "failure_modes": failure_modes(db, mock=wf.paypal_mode == "mock"),
            "presets": PRESETS,
            "current_preset": preset_for(current),
            "draft": draft,
            "draft_late": draft_late,
            "max_chars": settings.free_text_max_chars,
            "webhook_configured": bool(settings.paypal_webhook_id),
            "settings": settings,
            "paypal_mode": wf.paypal_mode,
            "extractor": getattr(wf.extractor, "name", type(wf.extractor).__name__),
            "cases": cases,
            "current": current,
            "mixed": wf.mixed.view(current["id"]) if current and current["scenario"] == "M" else None,
            "timeline": timeline_view(db.timeline(current["id"])) if current else [],
            "audit_chain": db.verify_chain(current["id"]) if current else None,
            "evidence_summary": evidence_summary(db, current, bool(settings.paypal_webhook_id)) if current else [],
            "proves": proves,
            "evidence": evidence_log(db, current["id"]) if current else [],
            "pending": pending,
            "economics": case_economics(settings.order_amount, settings.costs),
            "evidence_a": evidence_a(db, latest_a),
            "evidence_b": evidence_b(db, latest_b),
            "latest_a": latest_a,
            "latest_b": latest_b,
            "exchange_copy": EXCHANGE_COPY,
            "agent": agent_provenance(wf, current),
            "agents": agent_panel(db, mcp_tools(), settings.agent_demo_orders) if app.state.mcp_server else None,
            "flash": flash,
        }
        return templates.TemplateResponse(request, "dashboard.html", ctx, status_code=status_code)

    def back(case_id: str) -> RedirectResponse:
        return RedirectResponse(f"/?case={case_id}", status_code=303)

    def limited(request: Request) -> HTMLResponse | None:
        reason = limiter.check(ip(request))
        if reason:
            return render_dashboard(request, flash=reason, status_code=429)
        return None

    def disputes_limited(request: Request) -> HTMLResponse | None:
        # Same limiter, but a refusal stays on the Disputes page (it used to render the dashboard).
        reason = limiter.check(ip(request))
        return render_disputes(request, flash=reason, status_code=429) if reason else None

    def money_limited(request: Request, case_id: str | None = None) -> HTMLResponse | None:
        reason = money_limiter.check(ip(request))
        if reason:
            return render_dashboard(request, case_id, flash=reason, status_code=429)
        return None

    # -------------------------------------------------------------------------------------------

    @app.head("/", include_in_schema=False, response_class=HTMLResponse)
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, case: str | None = None):
        return render_dashboard(request, case)

    @app.head("/queue", include_in_schema=False, response_class=HTMLResponse)
    @app.get("/queue", response_class=HTMLResponse)
    def queue_page(request: Request):
        """Seeded multilingual demo queue (DEMO DATA). Read-only view: no DB rows, no PayPal calls, no actions."""
        return templates.TemplateResponse(request, "queue.html", {
            "settings": settings, "paypal_mode": wf.paypal_mode,
            "extractor": getattr(wf.extractor, "name", type(wf.extractor).__name__),
            "webhook_configured": bool(settings.paypal_webhook_id), "q": queue_view(wf.today())})

    @app.get("/healthz")
    def healthz():
        return {"ok": True,
                # The commit this deployment serves (Render injects RENDER_GIT_COMMIT): the
                # deploy-verify workflow waits for this to equal the pushed sha before running
                # scripts/sandbox_verify.py against the instance. Empty when unset (local runs).
                "version": os.environ.get("RENDER_GIT_COMMIT", ""),
                "paypal_mode": wf.paypal_mode, "llm_configured": settings.llm_configured,
                "webhook_configured": bool(settings.paypal_webhook_id), "cases": len(db.list_cases()),
                # Autonomy, so a verification run can tell which configuration it is talking to
                # (scripts/sandbox_verify.py) instead of scraping the page. Neither value is a secret.
                "auto_enabled": settings.auto_enabled,
                "auto_exchange_enabled": settings.auto_exchange_enabled,
                "auto_refund_max_amount": str(settings.auto_refund_max_amount),
                # Render (no disk) stores SQLite under /tmp; a restart or redeploy wipes it.
                # Surfaced so a judge (or deploy-verify) can see the demo is ephemeral without scraping.
                "persistence": "ephemeral" if settings.db_path.startswith("/tmp") else "durable"}

    @app.post("/demo/run/{scenario}")
    def run_demo(request: Request, scenario: str):
        if scenario not in RUNNABLE or (scenario in MOCK_ONLY and wf.paypal_mode != "mock"):
            raise HTTPException(404)
        if (refused := limited(request)) is not None:
            return refused
        try:
            case_id = wf.run_scenario(scenario)
        except MoneyError as exc:  # e.g. the seeded mixed order in a zero-decimal currency
            return render_dashboard(request, flash=f"Cannot create this demo case: {exc}", status_code=422)
        return back(case_id)

    @app.post("/demo/agent-scenes")
    def run_agent_scenes(request: Request):
        """Judge path for the agent gateway: a scripted MCP client plays three scenes through the real tools."""
        if app.state.mcp_server is None or not settings.agent_demo_orders:
            raise HTTPException(404)
        if (reason := agent_cooldown.check(ip(request))) is not None:
            return render_dashboard(request, flash=f"Agent scenes not run: {reason}", status_code=429)
        if (refused := limited(request)) is not None:
            return refused
        outcomes = run_scenes(app.state.mcp_server, db)
        failed = [o for o in outcomes if o.get("error")]
        honest = next((o["order_id"] for o in outcomes if o["scene"] == "honest" and o.get("order_id")), None)
        if failed or honest is None:
            return render_dashboard(request, flash="Agent scenes: " + "; ".join(
                f"{o['scene']}: {o['error']}" for o in failed), status_code=502)
        return RedirectResponse(f"/?case={honest}#agents", status_code=303)

    @app.post("/cases/free")
    def run_free_text(request: Request, message: str = Form(""), late: str = Form(""), preset: str = Form("")):
        """The judge's own message (or a one-click preset) through the same loop."""
        is_late = late.lower() in ("1", "on", "true", "yes")
        label = "Free text"
        if preset:
            if preset not in BY_KEY:
                raise HTTPException(404, "Unknown preset")
            p = BY_KEY[preset]
            if not message.strip():
                message, is_late = p["message"], p["late"]
            if message.strip() == p["message"]:
                label = preset_label(preset)
        message = message.strip()
        if not message or not clean_message(message, settings.free_text_max_chars):
            # clean_message strips non-printables: "\x00" survives .strip() but cleans to "" — that used
            # to escape this check and blow up run_free_text with an unhandled ValueError (a public 500).
            return render_dashboard(request, flash="Type a customer message (any language) or pick a preset.",
                                    status_code=422)
        if len(message) > settings.free_text_max_chars:
            return render_dashboard(request, flash=f"Message too long: {len(message)} characters "
                                                   f"(limit {settings.free_text_max_chars}).",
                                    status_code=422, draft=message[:settings.free_text_max_chars], draft_late=is_late)
        if (refused := limited(request)) is not None:
            return refused
        case_id = wf.run_free_text(message, late=is_late, label=label)
        return back(case_id)

    @app.post("/demo/reset")
    def reset_demo(request: Request):
        """Shared demo: confirm step in the page (JS confirm), per-IP + global cooldown."""
        if (reason := reset_cooldown.check(ip(request))) is not None:
            return render_dashboard(request, flash=f"Not reset: {reason}", status_code=429)
        # Never underneath a refund: refused while any refund call is in flight or a case lock is held.
        if not wf.begin_reset():
            return render_dashboard(request, flash="Not reset: a refund is being processed right now — "
                                    "try again in a few seconds.", status_code=409)
        try:
            db.init(reset=True)  # ARCHIVES the cases (chained); tables, audit chain and PayPal log are kept
            wf.reset_runtime_state()
            wf.seed_demo()
        finally:
            wf.end_reset()
        return RedirectResponse("/", status_code=303)

    def guarded(request: Request, case_id: str, action) -> HTMLResponse | RedirectResponse:
        try:
            action(case_id)
        except CaseNotFound:
            raise HTTPException(404, "Case not found")
        except RefundNotAllowed as exc:
            return render_dashboard(request, case_id, flash=f"Refused: {exc}", status_code=409)
        except CaseFinalized as exc:
            # A duplicate run or retry arrived after the case was completed / rejected / declined;
            # db.update_case refused the overwrite. Show it as the refusal it is, not a 500.
            return render_dashboard(request, case_id, flash=f"Refused: {exc}", status_code=409)
        except PayPalError:
            pass  # recorded on the case and shown in the UI
        return back(case_id)

    @app.post("/cases/{case_id}/approve")
    def approve(request: Request, case_id: str):
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        return guarded(request, case_id, wf.approve)

    @app.post("/cases/{case_id}/decline")
    def decline(request: Request, case_id: str):
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        return guarded(request, case_id, wf.decline)

    @app.post("/cases/{case_id}/safety-reviewed")
    def safety_reviewed(request: Request, case_id: str, note: str = Form("")):
        """Safety Gate follow-up: a person records a note + decision. No money, no refund flow."""
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        try:
            wf.mark_safety_reviewed(case_id, note)
        except SafetyNoteInvalid as exc:
            return render_dashboard(request, case_id, flash=f"Not recorded: {exc}", status_code=422)
        except CaseNotFound:
            raise HTTPException(404, "Case not found")
        except (RefundNotAllowed, CaseFinalized) as exc:
            return render_dashboard(request, case_id, flash=f"Refused: {exc}", status_code=409)
        return back(case_id)

    @app.post("/cases/{case_id}/refund")
    def refund(request: Request, case_id: str):
        """Retry endpoint. Same hard guard as approve: policy ELIGIBLE + human APPROVED."""
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        case = db.get_case(case_id)
        if case and case.get("refund_status") in ("COMPLETED", "PENDING"):
            return render_dashboard(request, case_id, status_code=409,
                                    flash=f"Nothing to retry: refund {case['refund_id']} is already "
                                          f"{case['refund_status']} at PayPal. No new refund request was sent.")
        if wf.refund_check_pending(case_id):
            return render_dashboard(request, case_id, status_code=409,
                                    flash="Checking with PayPal whether the last refund request went through — "
                                          "retry in a few seconds (it will reuse the same PayPal-Request-Id).")
        if case and case["status"] == REFUND_FAILED:
            return guarded(request, case_id, wf.retry_failed_refund)
        return guarded(request, case_id, wf.execute_refund)

    # ---- mixed orders: per-batch approval (items + exact total), never a whole-case approve ----------------
    def mixed_guarded(request: Request, case_id: str, action) -> HTMLResponse | RedirectResponse:
        c = db.get_case(case_id)
        if c is None or c["scenario"] != "M":
            raise HTTPException(404, "Case not found")
        try:
            action()
        except RefundNotAllowed as exc:
            return render_dashboard(request, case_id, flash=f"Refused: {exc}", status_code=409)
        except (CaseFinalized, ValueError) as exc:
            return render_dashboard(request, case_id, flash=f"Refused: {exc}", status_code=409)
        except PayPalError:
            pass  # recorded on the batch and shown in the UI
        return back(case_id)

    @app.post("/cases/{case_id}/batches/{batch_id}/approve")
    def approve_batch(request: Request, case_id: str, batch_id: str, expected_total: str = Form(""),
                      expected_hash: str = Form("")):
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        return mixed_guarded(request, case_id, lambda: wf.mixed.approve_batch(
            case_id, batch_id, expected_total or None, expected_hash or None))

    @app.post("/cases/{case_id}/batches/{batch_id}/decline")
    def decline_batch(request: Request, case_id: str, batch_id: str):
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        return mixed_guarded(request, case_id, lambda: wf.mixed.decline_batch(case_id, batch_id))

    @app.post("/cases/{case_id}/batches/{batch_id}/retry")
    def retry_batch(request: Request, case_id: str, batch_id: str):
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        return mixed_guarded(request, case_id, lambda: wf.mixed.retry_batch(case_id, batch_id))

    @app.post("/cases/{case_id}/lines/{line_no}/resolve")
    def resolve_line(request: Request, case_id: str, line_no: int, action: str = Form(""), reason: str = Form("UNKNOWN")):
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        return mixed_guarded(request, case_id, lambda: wf.mixed.resolve_line(case_id, line_no, action, reason))

    @app.post("/cases/{case_id}/mixed/propose")
    def repropose(request: Request, case_id: str):
        if (refused := money_limited(request, case_id)) is not None:
            return refused
        return mixed_guarded(request, case_id, lambda: wf.mixed.repropose(case_id))

    @app.post("/cases/{case_id}/retry-policy")
    def retry_policy(request: Request, case_id: str):
        """Payment captured but PayPal could not be read for the policy check: run the check again."""
        if (refused := limited(request)) is not None:
            return refused
        return guarded(request, case_id, wf.retry_policy_check)

    @app.post("/demo/mock-webhook/{case_id}")
    def mock_signed_webhook(request: Request, case_id: str):
        """MOCK mode only: PayPal 'settles' the pending mock refund and sends a signed
        PAYMENT.CAPTURE.REFUNDED, verified by the mock verifier through the normal webhook path."""
        if wf.paypal_mode != "mock":
            raise HTTPException(404)
        case = db.get_case(case_id)
        if not case or not case.get("refund_id"):
            raise HTTPException(404)
        pp = wf.paypal()
        inner = getattr(pp, "_mock_wraps", None) or pp
        refund = inner.complete_refund(case["refund_id"]) or {"id": case["refund_id"], "status": "COMPLETED"}
        n = len(db.webhook_events(case_id)) + 1
        event = {"id": f"WH-MOCK-{case_id}-{n}", "event_type": "PAYMENT.CAPTURE.REFUNDED",
                 "resource": {"id": refund["id"], "status": "COMPLETED", "amount": refund.get("amount")}}
        raw = json.dumps(event).encode()
        verification = pp.verify_webhook_signature({"paypal-transmission-sig": "valid-mock-signature"}, raw, "WEBHOOK_ID")
        wf.record_webhook(event, verification)
        return back(case_id)

    @app.post("/cases/{case_id}/approve-twice")
    def approve_twice(request: Request, case_id: str):
        """Failure-mode demo (scenario D only): simulates a double-clicked Approve."""
        if (refused := money_limited(request, case_id)) is not None:
            return refused  # approve-twice calls approve(); leaving it open would bypass the guard above
        case = db.get_case(case_id)
        if not case:
            raise HTTPException(404, "Case not found")
        if case["scenario"] != "D":
            raise HTTPException(404, "Only available on the double-click test case")
        return guarded(request, case_id, wf.approve_twice)

    def verify_webhook(headers: dict, raw: bytes) -> tuple[str, str]:
        """Self-check first (PayPal's preferred method); PayPal's verify-webhook-signature API as
        the fallback when the self-check cannot run. A self-check that runs and fails is final."""
        if not settings.paypal_webhook_id:
            return "NO_WEBHOOK_ID", "none"
        try:
            return self_verify(headers, raw, settings.paypal_webhook_id), "self"
        except SelfVerifyUnavailable:
            pass
        try:
            return wf.paypal().verify_webhook_signature(headers, raw, settings.paypal_webhook_id), "postback"
        except PayPalError:
            return "ERROR", "postback"

    @app.post("/webhooks/paypal")
    async def paypal_webhook(request: Request):
        """Second, independent confirmation: PayPal pushes PAYMENT.CAPTURE.REFUNDED; we verify the
        signature with PayPal's verify-webhook-signature API before trusting it."""
        raw = await request.body()
        if len(raw) > WEBHOOK_MAX_BODY:
            return JSONResponse({"ok": False, "handled": False, "error": "payload too large"}, status_code=400)
        try:
            event = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "Invalid JSON")
        if (not isinstance(event, dict) or not isinstance(event.get("event_type"), str)
                or event["event_type"] not in WEBHOOK_EVENTS | set(DISPUTE_EVENTS)):
            return JSONResponse({"ok": True, "handled": False})
        if event["event_type"] not in DISPUTE_EVENTS:
            event = sanitize_payment_event(event)  # allow-list + type-check (disputes do the same in parse_dispute)
        headers = dict(request.headers)
        missing = [h for h in SIGNATURE_HEADERS if not headers.get(h)]
        if missing and wf.paypal_mode != "mock":
            # PayPal always sends these, so this request did not come from PayPal: reject before any
            # verification call or DB write; log only. 400 (not 200): PayPal never retries something it
            # didn't send, and a caller gets a clear answer.
            log.warning("webhook rejected: missing PayPal signature headers %s (event %s)", missing,
                        str(event.get("id"))[:60])
            return JSONResponse({"ok": False, "handled": False, "error": "missing PayPal signature headers"},
                                status_code=400)

        def handle() -> tuple[str, str, str | None]:
            # Runs in the threadpool: the verification call and DB work never block the event loop.
            verification, method = verify_webhook(headers, raw)
            ttime = {k.lower(): v for k, v in headers.items()}.get("paypal-transmission-time")
            if event.get("event_type") in DISPUTE_EVENTS:  # read-only mirror; same verification, same trust rules
                return verification, method, wf.disputes.record_webhook(event, verification, method, ttime)
            return verification, method, wf.record_webhook(event, verification, method, ttime)

        try:
            verification, method, case_id = await run_in_threadpool(handle)
        except Exception:
            # Not acknowledged: PayPal retries the delivery (the event id was released, see record_webhook).
            return JSONResponse({"ok": False, "handled": False, "retry": True}, status_code=500)
        return JSONResponse({"ok": True, "handled": True, "verified": verification == "SUCCESS",
                             "case": case_id, "method": method})

    def render_disputes(request: Request, flash: str | None = None, status_code: int = 200) -> HTMLResponse:
        return templates.TemplateResponse(request, "disputes.html", {
            "settings": settings, "paypal_mode": wf.paypal_mode,
            "extractor": getattr(wf.extractor, "name", type(wf.extractor).__name__),
            "webhook_configured": bool(settings.paypal_webhook_id),
            "disputes": wf.disputes.view(), "access": wf.disputes.access(), "flash": flash,
            "label": DISPUTE_RECOMMENDATION_LABEL}, status_code=status_code)

    @app.head("/disputes", include_in_schema=False, response_class=HTMLResponse)
    @app.get("/disputes", response_class=HTMLResponse)
    def disputes_page(request: Request):
        return render_disputes(request)

    @app.post("/disputes/sync")
    def disputes_sync(request: Request):
        """Read-only: GET the dispute list (and each dispute) from PayPal and store it. No write calls exist."""
        if (refused := disputes_limited(request)) is not None:
            return refused
        if (reason := sync_gate.check("sync")) is not None:
            return render_disputes(request, flash=reason, status_code=429)
        result = wf.disputes.sync()
        return render_disputes(request, flash=result["message"], status_code=200 if result["ok"] else 409)

    @app.post("/disputes/{dispute_id}/refresh")
    def disputes_refresh(request: Request, dispute_id: str):
        if (refused := disputes_limited(request)) is not None:
            return refused
        if wf.db.get_dispute(dispute_id) is None:
            raise HTTPException(404, "Dispute not found")
        if (reason := refresh_gate.check(dispute_id)) is not None:
            return render_disputes(request, flash=reason, status_code=429)
        result = wf.disputes.fetch(dispute_id)
        return render_disputes(request, flash=result["message"], status_code=200 if result["ok"] else 409)

    @app.post("/cases/{case_id}/refresh-refund")
    def refresh_refund(request: Request, case_id: str):
        if (refused := money_limited(request)) is not None:
            return refused  # each click is two PayPal GETs: keep it bounded like the money actions
        return guarded(request, case_id, wf.refresh_refund)

    @app.get("/cases/{case_id}/paypal-return")
    def paypal_return(request: Request, case_id: str):
        """PayPal redirects the buyer here with a GET. GET never changes state (no capture, no CSRF
        exposure): it only shows the case with a 'Capture payment' button that POSTs below."""
        if not db.get_case(case_id):
            raise HTTPException(404, "Case not found")
        return render_dashboard(request, case_id, flash="Back from PayPal — press 'Capture payment' to continue.")

    @app.post("/cases/{case_id}/paypal-return")
    def paypal_return_capture(request: Request, case_id: str):
        if (refused := money_limited(request, case_id)) is not None:
            return refused  # capture moves money, so it is behind the same token as approve/refund
        return guarded(request, case_id, wf.complete_buyer_approval)

    @app.get("/cases/{case_id}/audit/verify")
    def audit_verify(case_id: str):
        """Recompute the case's hash chain. Read-only. See README 'Hash-chained audit trail' for limits."""
        if not db.get_case(case_id):
            raise HTTPException(404)
        result, chained = db.verify_and_fold(case_id)
        # approval_source belongs here: the point of chaining it is that a verifier outside this process
        # can confirm WHO approved a refund (a person, or the merchant's own policy), not just that
        # somebody did. Leaving it out made the guarantee only visible inside the app.
        result["chained_state"] = {k: chained.get(k) for k in ("status", "decision", "human_decision",
                                                               "approval_source", "refund_status", "refund_id")}
        return JSONResponse(result)

    def build_evidence_report(case_id: str) -> dict:
        """Read-only, self-contained evidence bundle for one case: what a third party needs to re-check
        the audit hash chain offline and to look the PayPal ids up in their own Sandbox account."""
        case = db.get_case(case_id)
        if not case:
            raise HTTPException(404)
        result, _state = db.verify_and_fold(case_id)
        entries = []
        for e in db.chain_entries(case_id):
            entries.append({"seq": e["seq"], "type": e["type"], "ts": e["ts"], "prev_hash": e["prev_hash"],
                            "entry_hash": e["entry_hash"], "payload": json.loads(e["payload_json"])})
        calls = [{k: c.get(k) for k in ("ts", "operation", "ok", "result", "debug_id", "request_id")}
                 for c in db.paypal_calls(case_id)]
        ids = {k: case.get(k) for k in ("order_id", "capture_id", "refund_id") if case.get(k)}
        # Mixed orders refund per batch: the refund ids live on the batches, not on the case row.
        batches = [{"batch_no": b["batch_no"], "status": b["status"],
                    "amount": money_str(b["amount_minor"], b["currency"]), "currency": b["currency"],
                    "refund_id": b.get("refund_id"), "refund_status": b.get("refund_status"),
                    "paypal_amount": b.get("paypal_amount"), "debug_id": b.get("debug_id"),
                    "request_id": b.get("request_id")} for b in db.list_batches(case_id)]
        refund_api_called = any(c["operation"] == "refund_capture" for c in calls) or bool(
            ids.get("refund_id") or any(b["refund_id"] for b in batches))
        return {
            "report": "TradeOS case evidence", "generated_at": utcnow(), "case_id": case_id,
            "environment": {"paypal_mode": wf.paypal_mode, "note": "PayPal Sandbox only — no real money"
                            if wf.paypal_mode != "live" else "live"},
            "summary": {k: case.get(k) for k in ("status", "decision", "human_decision", "approval_source",
                                                 "refund_status")},
            "paypal_ids": ids, "refund_batches": batches, "refund_api_called": refund_api_called,
            "verification": result, "chain_head": entries[-1]["entry_hash"] if entries else None,
            "chain_entries": entries, "paypal_calls": calls,
            "how_to_verify": ("entry_hash = sha256(canonical_json({case_id, seq, type, ts, payload, prev_hash})); "
                              "canonical_json = sorted keys, separators (',', ':'), UTF-8, ensure_ascii=False; "
                              "entry 1 has prev_hash = 64 zeros. Record chain_head somewhere outside this server: "
                              "tamper-evident, not tamper-proof."),
        }

    @app.get("/cases/{case_id}/evidence.json")
    def evidence_json(case_id: str):
        """Downloadable evidence bundle (JSON). Read-only; moves no money and calls no PayPal API."""
        return JSONResponse(build_evidence_report(case_id), headers={
            "Content-Disposition": f'attachment; filename="tradeos-evidence-{case_id}.json"'})

    @app.get("/cases/{case_id}/evidence", response_class=HTMLResponse)
    def evidence_page(request: Request, case_id: str):
        """Printable evidence report (use the browser's Save as PDF). Read-only."""
        return templates.TemplateResponse(request, "evidence_report.html", {
            "settings": settings, "paypal_mode": wf.paypal_mode,
            "extractor": getattr(wf.extractor, "name", type(wf.extractor).__name__),
            "webhook_configured": bool(settings.paypal_webhook_id), "r": build_evidence_report(case_id),
            "json": json})

    @app.get("/audit/heads")
    def audit_heads():
        """The chain head of every case, for retention OUTSIDE this database (the deploy-verify
        workflow saves one list per deployment as a workflow artifact). Two head lists recorded at
        different times are what make a truncated or rewritten chain detectable — README
        'Hash-chained audit trail': tamper-evident, not tamper-proof."""
        return JSONResponse({"generated_at": utcnow(), "heads": db.chain_heads()})

    @app.get("/api/cases/{case_id}")
    def case_json(case_id: str):
        case = db.get_case(case_id)
        if not case:
            raise HTTPException(404)
        for k in [k for k in case if k.endswith("_json")]:
            case.pop(k, None)
        out = {"case": case, "timeline": db.timeline(case_id), "paypal_calls": db.paypal_calls(case_id)}
        if case.get("scenario") == "M":
            out["mixed"] = wf.mixed.api(case_id)
        return JSONResponse(out)

    return app


app = create_app()
