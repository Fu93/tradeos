"""Live AI agent runs in the background, so a page can show each step as the model takes it.

A run takes 10 to 90 seconds (several model calls, Sandbox orders, the policy's PayPal reads). Holding one HTTP
request open for that long shows nothing until the end, and a proxy may cut it. Instead the POST starts the run in a
worker thread and redirects to /agent-runs/<id>, which renders what has happened so far and polls for the rest.

The registry is in memory and small on purpose: it only exists to watch a run that is in progress. The run itself is
recorded where it belongs, on the order's hash chain, when it ends. After a restart a run's page says it is gone, and
the order (if one was placed) still carries the whole transcript.

One run at a time for the whole app: the model provider's free tier allows about one run a minute, and two runs at
once would starve each other and the intent extractor.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .llm_agent import AgentRun, Goal

MAX_KEPT = 20  # finished runs kept for their pages; the oldest finished run is dropped first


@dataclass
class RunState:
    id: str
    goal: str
    title: str
    model: str
    started: float
    status: str = "running"          # running -> done | failed
    phase: str = "starting"          # starting, thinking, step, done
    model_calls: int = 0
    steps: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    final_report: str = ""
    tokens: int = 0
    seconds: float = 0.0
    case_id: str | None = None
    error: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {"id": self.id, "goal": self.goal, "title": self.title, "model": self.model, "status": self.status,
                "phase": self.phase, "model_calls": self.model_calls, "steps": [dict(s) for s in self.steps],
                "stop_reason": self.stop_reason, "final_report": self.final_report, "tokens": self.tokens,
                "seconds": round(self.seconds, 1), "case_id": self.case_id, "error": self.error}


class AgentRunRegistry:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._runs: dict[str, RunState] = {}
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._clock = clock

    def running(self) -> str | None:
        """The id of the run in progress, if any."""
        with self._lock:
            return next((r.id for r in self._runs.values() if r.status == "running"), None)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._runs.get(run_id)
            return state.snapshot() if state else None

    def start(self, goal: Goal, model: str, execute: Callable[[Callable[[AgentRun, str], None]], AgentRun],
              finish: Callable[[AgentRun], str | None]) -> str | None:
        """Start a run in a worker thread; None if one is already running.

        execute(on_progress) runs the agent and returns its AgentRun. finish(run) records it (on the chain) and
        returns the order id, or None when the model placed no order. Neither may block the caller."""
        with self._lock:
            if any(r.status == "running" for r in self._runs.values()):
                return None
            run_id = secrets.token_urlsafe(9)
            self._runs[run_id] = RunState(run_id, goal.key, goal.title, model, self._clock())
            self._evict()
        thread = threading.Thread(target=self._work, args=(run_id, execute, finish), daemon=True,
                                  name=f"agent-run-{run_id}")
        self._threads[run_id] = thread
        thread.start()
        return run_id

    def join(self, run_id: str, timeout: float | None = None) -> None:
        """Wait for a run's thread (tests, and a clean shutdown)."""
        thread = self._threads.get(run_id)
        if thread is not None:
            thread.join(timeout)

    def _progress(self, run_id: str, run: AgentRun, phase: str) -> None:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return
            state.phase, state.model_calls, state.tokens = phase, run.model_calls, run.tokens
            state.steps = [dict(s) for s in run.steps]

    def _work(self, run_id: str, execute, finish) -> None:
        try:
            run = execute(lambda r, phase: self._progress(run_id, r, phase))
            case_id = finish(run)
        except Exception as exc:  # the page must say the run failed, not spin forever
            with self._lock:
                state = self._runs[run_id]
                state.status, state.phase, state.error = "failed", "done", type(exc).__name__
                state.seconds = self._clock() - state.started
            return
        with self._lock:
            state = self._runs[run_id]
            state.status, state.phase, state.case_id = "done", "done", case_id
            state.steps = [dict(s) for s in run.steps]
            state.stop_reason, state.final_report = run.stop_reason, run.final_report
            state.tokens, state.model_calls, state.seconds = run.tokens, run.model_calls, run.seconds

    def _evict(self) -> None:
        finished = [r for r in self._runs.values() if r.status != "running"]
        while len(self._runs) > MAX_KEPT and finished:
            oldest = min(finished, key=lambda r: r.started)
            finished.remove(oldest)
            self._runs.pop(oldest.id, None)
            self._threads.pop(oldest.id, None)
