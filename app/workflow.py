"""The one TradeOS loop (plan §3):

request -> AI intent -> deterministic policy -> supplier -> human approval -> PayPal refund (or block).
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from .config import Settings
from .db import Database, next_seq
from .intent import AssistFields, IntentExtractor
from .notes import TemplateNoteWriter
from .paypal_client import PayPalClient, PayPalError, find_link, first_capture
from .paypal_mock import MockPayPalClient
from .intent import looks_like_injection
from .policy import PolicyInput, PolicyResult, evaluate
from .supplier import OUT_OF_STOCK, draft_supplier_message, mock_supplier_reply

# ... (full file content omitted in this thought for brevity, but will be the real one)
