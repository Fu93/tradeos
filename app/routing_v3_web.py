"""Dashboard + HTTP glue for routing taxonomy v3 (EXPERIMENT). Additive; nothing is ever sent.

  POST /routing-v3/triage               triage a complaint with v3 (MOCK orders)
  POST /routing-v3/{cid}/reply          SIMULATED customer reply to a clarifying question (panel only)
  POST /routing-v3/{cid}/confirm-task   human confirms a SUGGESTED supplier task -> internal draft (NOT sent)
  POST /routing-v3/{cid}/dismiss-task   human declines the suggestion -> human review
  GET  /api/routing-v3/{cid}            case + decision + log as JSON
"""
from __future__ import annotations

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .routing_data import MOCK_LABEL
from .routing_v3 import MAX_CLARIFY_ROUNDS, RULE_VERSION_V3, ContextV3
from .routing_v3_service import STATUS_TEXT, RoutingV3Service
from .routing_web import customers, order_options

CHIP = {"DIRECT_WORKFLOW": "ok", "SUGGESTED_TASK": "mock", "TASK_DRAFT_READY": "mock", "AWAITING_CUSTOMER": "warn",
        "HUMAN_REVIEW": "warn"}

PRESETS_V3 = [
    {"chip": "EN · supplier warranty", "customer": "quinn@example.test",
     "message": "Order TO-60202: the kettle has started leaking from the base. Could you repair or replace it?"},
    {"chip": "ES · exchange", "customer": "ana@example.test",
     "message": "Hola, pedido TO-10421: las zapatillas me quedan pequeñas. ¿Puedo cambiar la talla 42 por la 43?"},
    {"chip": "Clarify · wrong order no.", "customer": "ana@example.test",
     "message": "My order T0-10421 — the trainers are too small, please swap 42 for 43."},
    {"chip": "Clarify · goal choice", "customer": "quinn@example.test",
     "message": "TO-60202 kettle leaks. I'd like a repair, or maybe just my money back, not sure."},
    {"chip": "Safety", "customer": "quinn@example.test",
     "message": "TO-60202: the kettle base smelled burnt and sparked. Please replace it."},
    {"chip": "Question (no task)", "customer": "wen@example.test",
     "message": "Do you have the kettle lid KL-170-LID in stock?"},
]


def panel_v3(svc: RoutingV3Service, cid: str | None) -> dict:
    sel = svc.store.get(cid) if cid else None
    recent = svc.store.recent(8)
    if sel is None and cid is None and recent:
        sel = recent[0]
    view = None
    if sel:
        dec = sel.get("decision") or {}
        rounds = sel.get("rounds") or []
        view = {"case": sel, "decision": dec, "rounds": rounds, "events": svc.store.events(sel["id"]),
                "status_text": STATUS_TEXT.get(sel["status"], sel["status"]), "chip": CHIP.get(sel["status"], "neutral"),
                "evidence": evidence_rows(sel), "task": sel.get("task"),
                "awaiting": sel["status"] == "AWAITING_CUSTOMER" and rounds and rounds[-1].get("reply") is None}
    return {"view": view, "recent": recent, "presets": PRESETS_V3, "customers": customers(), "orders": order_options(),
            "rule_version": RULE_VERSION_V3, "mock_label": MOCK_LABEL, "chips": CHIP, "k": svc.k,
            "extractor": getattr(svc.extractor, "name", "unavailable"), "max_rounds": MAX_CLARIFY_ROUNDS}


def evidence_rows(case: dict) -> list[dict]:
    from .routing_v3 import quote_ok
    ex, msg = case.get("extraction") or {}, case.get("message") or ""
    rows = []
    if ex.get("speech_act"):
        rows.append({"field": "speech act", "label": ex["speech_act"], "quote": ex.get("speech_act_evidence"),
                     "ok": quote_ok(ex.get("speech_act_evidence"), msg)})
    for i, it in enumerate(ex.get("items") or []):
        rows.append({"field": f"item {i + 1} issue", "label": it.get("issue_type"), "quote": it.get("issue_evidence"),
                     "ok": quote_ok(it.get("issue_evidence"), msg)})
        for g in it.get("goals") or []:
            rows.append({"field": f"item {i + 1} goal ({it.get('goal_relation')})", "label": g.get("goal"),
                         "quote": g.get("evidence"), "ok": quote_ok(g.get("evidence"), msg)})
    if ex.get("safety_level") and ex["safety_level"] != "NONE":
        rows.append({"field": "safety (model)", "label": ex["safety_level"], "quote": ex.get("safety_evidence"),
                     "ok": quote_ok(ex.get("safety_evidence"), msg)})
    return rows


def register_v3(app: FastAPI, svc: RoutingV3Service, limited) -> None:
    def back(cid: str) -> RedirectResponse:
        return RedirectResponse(f"/?v3case={cid}#routing-v3", status_code=303)

    @app.post("/routing-v3/triage")
    def v3_triage(request: Request, message: str = Form(""), customer: str = Form(""), linked_order: str = Form("")):
        message = " ".join(message.split())[:800]
        if not message:
            raise HTTPException(422, "Type a complaint.")
        if (refused := limited(request)) is not None:
            return refused
        return back(svc.triage(message, ContextV3(customer or None, linked_order or None)))

    @app.post("/routing-v3/{cid}/reply")
    def v3_reply(request: Request, cid: str, reply: str = Form("")):
        reply = " ".join(reply.split())[:500]
        if not reply:
            raise HTTPException(422, "Type the simulated customer reply.")
        if (refused := limited(request)) is not None:
            return refused
        try:
            svc.simulate_reply(cid, reply)
        except KeyError:
            raise HTTPException(404, "Case not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return back(cid)

    @app.post("/routing-v3/{cid}/confirm-task")
    def v3_confirm(cid: str):
        try:
            svc.confirm_task(cid)
        except KeyError:
            raise HTTPException(404, "Case not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return back(cid)

    @app.post("/routing-v3/{cid}/dismiss-task")
    def v3_dismiss(cid: str):
        try:
            svc.dismiss_task(cid)
        except KeyError:
            raise HTTPException(404, "Case not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return back(cid)

    @app.get("/api/routing-v3/{cid}")
    def v3_json(cid: str):
        case = svc.store.get(cid)
        if not case:
            raise HTTPException(404)
        return JSONResponse({"case": case, "log": svc.store.events(cid), "rule_version": RULE_VERSION_V3,
                             "data_label": MOCK_LABEL, "experimental": True,
                             "note": "Nothing is sent: clarifying questions and replies are simulated; supplier tasks are "
                                     "suggestions that a human confirms into internal drafts."})
