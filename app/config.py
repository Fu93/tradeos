"""Runtime configuration. Everything comes from environment variables.

Nothing in here is a secret by default; secrets (PayPal + LLM keys) are only
read from the environment and are never written to disk or rendered in the UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
# Default LLM provider behind the adapter: Groq's OpenAI-compatible endpoint.
# Any OpenAI-compatible /chat/completions endpoint works; override via env.
DEFAULT_LLM_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-20b"


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CostAssumptions:
    """Illustrative cost model (plan §6). All values are assumptions, not measurements."""

    human_minutes_per_case: Decimal = Decimal("8")
    human_hourly_rate_usd: Decimal = Decimal("20")
    ai_api_cost_per_case_usd: Decimal = Decimal("0.06")
    human_review_minutes: Decimal = Decimal("1")

    @classmethod
    def from_env(cls) -> "CostAssumptions":
        return cls(
            human_minutes_per_case=Decimal(_env("COST_HUMAN_MINUTES", "8")),
            human_hourly_rate_usd=Decimal(_env("COST_HOURLY_RATE_USD", "20")),
            ai_api_cost_per_case_usd=Decimal(_env("COST_AI_API_USD", "0.06")),
            human_review_minutes=Decimal(_env("COST_REVIEW_MINUTES", "1")),
        )


@dataclass(frozen=True)
class Settings:
    # PayPal (Sandbox by default)
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = SANDBOX_BASE_URL
    # Opt-in offline mode: fake PayPal IDs, loudly labelled in the UI. Never the default.
    paypal_mock: bool = False

    # LLM: any OpenAI-compatible endpoint (default: Groq). Without LLM_API_KEY the
    # deterministic keyword extractor is used instead, so the demo always runs.
    llm_api_key: str = ""
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL

    # App
    db_path: str = "tradeos.db"
    reset_on_start: bool = True
    public_base_url: str = "http://localhost:8000"

    # Demo order (plan §6: USD end to end)
    order_amount: str = "49.99"
    currency: str = "USD"
    return_window_days: int = 30
    case_b_days_since_purchase: int = 45

    # Free-text input protection (sandbox + LLM quota). Every run creates a real sandbox order.
    free_text_max_chars: int = 500
    rate_limit_per_minute: int = 5      # per client IP
    rate_limit_per_hour: int = 30       # per client IP
    rate_limit_global_per_hour: int = 200

    # Failure-mode demo: PayPal sandbox negative testing code forced on ONE refund attempt.
    refund_failure_mock_code: str = "REFUND_FAILED_INSUFFICIENT_FUNDS"

    # PayPal webhook (second, independent confirmation). Not a secret; set via env, never committed.
    paypal_webhook_id: str = ""

    costs: CostAssumptions = field(default_factory=CostAssumptions)

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)

    @classmethod
    def from_env(cls) -> "Settings":
        public = _env("PUBLIC_BASE_URL") or _env("RENDER_EXTERNAL_URL") or "http://localhost:8000"
        return cls(
            paypal_client_id=_env("PAYPAL_CLIENT_ID"),
            paypal_client_secret=_env("PAYPAL_CLIENT_SECRET"),
            paypal_base_url=(_env("PAYPAL_BASE_URL") or SANDBOX_BASE_URL).rstrip("/"),
            paypal_mock=_env_bool("PAYPAL_MOCK", False),
            llm_api_key=_env("LLM_API_KEY"),
            llm_base_url=(_env("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL).rstrip("/"),
            llm_model=_env("LLM_MODEL") or DEFAULT_LLM_MODEL,
            db_path=_env("TRADEOS_DB_PATH", "tradeos.db"),
            reset_on_start=_env_bool("TRADEOS_RESET_ON_START", True),
            public_base_url=public.rstrip("/"),
            return_window_days=int(_env("RETURN_WINDOW_DAYS", "30")),
            free_text_max_chars=int(_env("FREE_TEXT_MAX_CHARS", "500")),
            rate_limit_per_minute=int(_env("RATE_LIMIT_PER_MINUTE", "5")),
            rate_limit_per_hour=int(_env("RATE_LIMIT_PER_HOUR", "30")),
            rate_limit_global_per_hour=int(_env("RATE_LIMIT_GLOBAL_PER_HOUR", "200")),
            refund_failure_mock_code=_env("REFUND_FAILURE_MOCK_CODE") or "REFUND_FAILED_INSUFFICIENT_FUNDS",
            paypal_webhook_id=_env("PAYPAL_WEBHOOK_ID"),
            costs=CostAssumptions.from_env(),
        )
