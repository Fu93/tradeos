"""FastAPI app: one server-rendered dashboard + a few form endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates

from .config import Settings
from .db import Database
from .economics import case_economics
from .intent import IntentExtractor, build_extractor
from .notes import build_note_writer
from .paypal_client import PayPalError
from .presets import BY_KEY, PRESETS, preset_label
from .ratelimit import RateLimiter, client_key
from .views import (ai_panel, backend_controls, evidence_a, evidence_b, failure_modes, fmt_ts, pipeline,
                    preset_for, result_card, timeline_view, evidence_log, evidence_summary)
from .workflow import (AWAITING_BUYER, PENDING_APPROVAL, REFUND_ERROR, RUNNABLE, CaseNotFound, RefundNotAllowed,
                       Workflow)

BASE = Path(__file__).parent
EXCHANGE_COPY = ("For the hackathon MVP, the financial side of an exchange is simplified to a refund of the "
                 "original PayPal transaction. Replacement fulfilment is represented by the supplier confirmation.")


WEBHOOK_EVENTS = {"PAYMENT.CAPTURE.REFUNDED"}


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

    # Render's free tier wipes the filesystem: reset + seed the demo on every start.
    db.init(reset=settings.reset_on_start)
    if not db.list_cases():
        wf.seed_demo()

    app = FastAPI(title="TradeOS", docs_url="/api/docs", redoc_url=None)
    app.state.workflow = wf
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=BASE / "templates")
    templates.env.filters["ts"] = fmt_ts

    def render_dashboard(request: Request, selected: str | None = None, flash: str | None = None,
                         status_code: int = 200, draft: str = "", draft_late: bool = False) -> HTMLResponse:
        cases = db.list_cases()
        current = db.get_case(selected) if selected else None
        if current is None and cases:
            current = next((c for c in cases if c["status"] != "NEW"), cases[0])
        pending = [c for c in cases if c["status"] in (PENDING_APPROVAL, AWAITING_BUYER, REFUND_ERROR)
                   and (not current or c["id"] != current["id"])]
        latest_a, latest_b = db.latest_case("A"), db.latest_case("B")
        ctx = {
            "pipeline": pipeline(db, current),
            "result": result_card(db, current, bool(settings.paypal_webhook_id)),
            "ai": ai_panel(current),
            "controls": backend_controls(db, current),
            "failure_modes": failure_modes(db),
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
            "timeline": timeline_view(db.timeline(current["id"])) if current else [],
            "evidence_summary": evidence_summary(db, current, bool(settings.paypal_webhook_id)) if current else [],
            "evidence": evidence_log(db, current["id"]) if current else [],
            "pending": pending,
            "economics": case_economics(settings.order_amount, settings.costs),
            "evidence_a": evidence_a(db, latest_a),
            "evidence_b": evidence_b(db, latest_b),
            "latest_a": latest_a,
            "latest_b": latest_b,
            "exchange_copy": EXCHANGE_COPY,
            "flash": flash,
        }
        return templates.TemplateResponse(request, "dashboard.html", ctx, status_code=status_code)

    def back(case_id: str) -> RedirectResponse:
        return RedirectResponse(f"/?case={case_id}", status_code=303)

    def limited(request: Request) -> HTMLResponse | None:
        reason = limiter.check(client_key(request))
        if reason:
            return render_dashboard(request, flash=reason, status_code=429)
        return None

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, case: str | None = None):
        return render_dashboard(request, case)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "paypal_mode": wf.paypal_mode, "llm_configured": settings.llm_configured,
                "webhook_configured": bool(settings.paypal_webhook_id), "cases": len(db.list_cases())}

    @app.post("/demo/run/{scenario}")
    def run_demo(request: Request, scenario: str):
        if scenario not in RUNNABLE:
            raise HTTPException(404)
        if (refused := limited(request)) is not None:
            return refused
        case_id = wf.run_scenario(scenario)
        return back(case_id)

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
        if not message:
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
    def reset_demo():
        db.init(reset=True)  # drops cases, audit, PayPal call log and webhook_events
        wf.reset_runtime_state()
        wf.seed_demo()
        return RedirectResponse("/", status_code=303)

    def guarded(request: Request, case_id: str, action) -> HTMLResponse | RedirectResponse:
        try:
            action(case_id)
        except CaseNotFound:
            raise HTTPException(404, "Case not found")
        except RefundNotAllowed as exc:
            return render_dashboard(request, case_id, flash=f"Refused: {exc}", status_code=409)
        except PayPalError:
            pass  # recorded on the case and shown in the UI
        return back(case_id)

    @app.post("/cases/{case_id}/approve")
    def approve(request: Request, case_id: str):
        return guarded(request, case_id, wf.approve)

    @app.post("/cases/{case_id}/decline")
    def decline(request: Request, case_id: str):
        return guarded(request, case_id, wf.decline)

    @app.post("/cases/{case_id}/refund")
    def refund(request: Request, case_id: str):
        """Retry endpoint. Same hard guard as approve: policy ELIGIBLE + human APPROVED."""
        return guarded(request, case_id, wf.execute_refund)

    @app.post("/cases/{case_id}/approve-twice")
    def approve_twice(request: Request, case_id: str):
        """Failure-mode demo (scenario D only): simulates a double-clicked Approve."""
        case = db.get_case(case_id)
        if not case:
            raise HTTPException(404, "Case not found")
        if case["scenario"] != "D":
            raise HTTPException(404, "Only available on the double-click test case")
        return guarded(request, case_id, wf.approve_twice)

    @app.post("/webhooks/paypal")
    async def paypal_webhook(request: Request):
        """Second, independent confirmation: PayPal pushes PAYMENT.CAPTURE.REFUNDED; we verify the
        signature with PayPal's verify-webhook-signature API before trusting it."""
        raw = await request.body()
        try:
            event = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(event, dict) or event.get("event_type") not in WEBHOOK_EVENTS:
            return JSONResponse({"ok": True, "handled": False})
        headers = dict(request.headers)

        def handle() -> str | None:
            # Runs in the threadpool: the verification call and DB work never block the event loop.
            if not settings.paypal_webhook_id:
                verification = "NO_WEBHOOK_ID"
            else:
                try:
                    verification = wf.paypal().verify_webhook_signature(headers, raw, settings.paypal_webhook_id)
                except PayPalError:
                    verification = "ERROR"
            return verification, wf.record_webhook(event, verification)

        try:
            verification, case_id = await run_in_threadpool(handle)
        except Exception:
            # Not acknowledged: PayPal retries the delivery (the event id was released, see record_webhook).
            return JSONResponse({"ok": False, "handled": False, "retry": True}, status_code=500)
        return JSONResponse({"ok": True, "handled": True, "verified": verification == "SUCCESS",
                             "case": case_id})

    @app.post("/cases/{case_id}/refresh-refund")
    def refresh_refund(request: Request, case_id: str):
        return guarded(request, case_id, wf.refresh_refund)

    @app.get("/cases/{case_id}/paypal-return")
    def paypal_return(request: Request, case_id: str):
        return guarded(request, case_id, wf.complete_buyer_approval)

    @app.get("/api/cases/{case_id}")
    def case_json(case_id: str):
        case = db.get_case(case_id)
        if not case:
            raise HTTPException(404)
        for k in [k for k in case if k.endswith("_json")]:
            case.pop(k, None)
        return JSONResponse({"case": case, "timeline": db.timeline(case_id),
                             "paypal_calls": db.paypal_calls(case_id)})

    return app


app = create_app()
