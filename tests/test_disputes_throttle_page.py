"""A throttled POST on the Disputes page stays on the Disputes page (it used to render the dashboard)."""
from app.config import Settings


def test_throttled_disputes_sync_stays_on_the_disputes_page(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.notes import TemplateNoteWriter
    from app.paypal_mock import MockPayPalClient
    from tests.helpers import FakeExtractor
    s = Settings(db_path=settings.db_path, rate_limit_per_minute=1, rate_limit_per_hour=100)
    client = TestClient(create_app(settings=s, paypal=MockPayPalClient(), extractor=FakeExtractor(),
                                   note_writer=TemplateNoteWriter()))
    assert client.post("/disputes/sync").status_code != 429
    for path in ("/disputes/sync", "/disputes/D1/refresh"):
        r = client.post(path)
        assert r.status_code == 429 and "Rate limit" in r.text, (path, r.status_code)
        assert "Fetch from PayPal" in r.text  # the Disputes page, not the dashboard
