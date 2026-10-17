from app.config import Settings


def test_cf_header_trusted_by_default_on_render(monkeypatch):
    monkeypatch.delenv("TRADEOS_TRUST_CF_CONNECTING_IP", raising=False)
    monkeypatch.setenv("RENDER", "true")
    assert Settings.from_env().trust_cf_connecting_ip is True


def test_cf_header_not_trusted_off_render(monkeypatch):
    monkeypatch.delenv("TRADEOS_TRUST_CF_CONNECTING_IP", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert Settings.from_env().trust_cf_connecting_ip is False


def test_explicit_env_wins_on_render(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRADEOS_TRUST_CF_CONNECTING_IP", "0")
    assert Settings.from_env().trust_cf_connecting_ip is False
