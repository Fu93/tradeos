"""FastAPI app: one server-rendered dashboard + a few form endpoints."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings
from .db import Database
from .economics import case_economics
from .intent import IntentExtractor, build_extractor
from .paypal_client import PayPalError
from .views import evidence_a, evidence_b, fmt_ts
from .workflow import AWAITING_BUYER, PENDING_APPROVAL, REFUND_ERROR, CaseNotFound, RefundNotAllowed, Workflow

BASE = Path(__file__).parent
EXCHANGE_COPY = ("For the hackathon MVP, the financial side of an exchange is simplified to a refund of the "
                 "original PayPal transaction. Replacement fulfilment is represented by the supplier confirmation.")


def create_app(settings: Settings | None = None, paypal=None, extractor: IntentExtractor | None = None,
               today=None) -> FastAPI:
    if settings is None:
        load_dotenv()
        settings = Settings.from_env()
    db = Database(settings.db_path)
    kwargs = {"today": today} if today else {}
    wf = Workflow(db, settings, extractor or build_extractor(settings), paypal=paypal, **kwargs)

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
                         status_code: int = 200) -> HTMLResponse:
        cases = db.list_cases()
        current = db.get_case(selected) if selected else None
        if current is None and cases:
            current = next((c for c in cases if c["status"] != "NEW"), cases[0])
        pending = [c for c in cases if c["status"] in (PENDING_APPROVAL, AWAITING_BUYER, REFUND_ERROR)]
        latest_a, latest_b = db.latest_case("A"), db.latest_case("B")
        ctx = {
            "settings": settings,
            "paypal_mode": wf.paypal_mode,
            "extractor": getattr(wf.extractor, "name", type(wf.extractor).__name__),
            "cases": cases,
            "current": current,
            "timeline": db.timeline(current["id"]) if current else [],
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
        return RedirectResponse(f"/?case={case_id}#timeline", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, case: str | None = None):
        return render_dashboard(request, case)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "paypal_mode": wf.paypal_mode}

    @app.post("/demo/run/{scenario}")
    def run_demo(scenario: str):
        if scenario not in ("A", "B"):
            raise HTTPException(404)
        case_id = wf.run_scenario(scenario)
        return back(case_id)

    @app.post("/demo/reset")
    def reset_demo():
        db.init(reset=True)
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
        for k in ("intent_json", "policy_json", "refund_json"):
            case.pop(k, None)
        return JSONResponse({"case": case, "timeline": db.timeline(case_id),
                             "paypal_calls": db.paypal_calls(case_id)})

    return app


app = create_app()
