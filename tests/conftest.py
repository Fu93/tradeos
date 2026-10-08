import os
import sys
import tempfile
from pathlib import Path

import pytest

# Tests must never talk to real PayPal or a real LLM, and must not touch ./tradeos.db.
for var in list(os.environ):
    if var.startswith(("PAYPAL_", "LLM_")):
        del os.environ[var]
os.environ["TRADEOS_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "import-time.db")
os.environ["PAYPAL_MOCK"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest.mock import MagicMock  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.intent import KeywordIntentExtractor  # noqa: E402
from app.paypal_mock import MockPayPalClient  # noqa: E402
from app.workflow import Workflow  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=str(tmp_path / "test.db"), paypal_client_id="", paypal_client_secret="")


@pytest.fixture
def paypal():
    """A MockPayPalClient wrapped in MagicMock so tests can assert which APIs were (not) called."""
    return MagicMock(wraps=MockPayPalClient(), is_mock=True)


@pytest.fixture
def workflow(settings, paypal):
    db = Database(settings.db_path)
    db.init(reset=True)
    wf = Workflow(db, settings, KeywordIntentExtractor(), paypal=paypal)
    wf.seed_demo()
    return wf
