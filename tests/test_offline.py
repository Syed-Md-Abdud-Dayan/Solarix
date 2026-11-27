"""Kill-switch test: with ALL network access blocked, the full pipeline must still run.

forecast -> allocation -> overflow -> simulate -> dispatch -> notify/outbox -> export
must complete with no exception and ZERO network attempts. Also checks the deterministic
fallback when a model is broken, and that nothing in web/ loads a remote asset.
"""
import re
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_network(monkeypatch):
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(args)
        raise OSError("network disabled by test (kill-switch)")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    return attempts


@pytest.fixture(scope="module")
def ops():
    import app  # loads models from local files only
    from dengue_watch.ops import forecast_bridge as FB
    FB.set_force_fallback(False)
    return app


def test_full_pipeline_offline(ops, no_network, tmp_path):
    from dengue_watch.ops import db, dispatch as D, notify, planner, simulator, tasks
    from dengue_watch.ops import forecast_bridge as FB

    fc = FB.forecast_payload("2025-07-07")
    assert fc["source"] == "model" and len(fc["wards"]) == 60
    for pct in (100, 30):
        p = planner.plan("2025-07-07", stock_pct=pct, total_crews=15)
        assert len(p["allocation"]["wards"]) == 60
    sim = simulator.recommend(5, "2025-07-07")
    assert sim["total"]["cases_prevented"] >= 0
    ward = p["allocation"]["wards"][0]["ward_id"]
    ctx = D.ward_context(p, ward)
    for lang in ("en", "bn"):
        for team in D.TEAMS:
            assert D.sms(ctx, team, lang)["short"]
            assert D.whatsapp(ctx, team, lang)["text"]
        assert "<html" in D.brief_html(ctx, lang)
    D.brief_pdf(ctx)                      # optional reportlab path must not crash either way

    # DB + task generation + outbox + retry, all offline
    db.init_db()
    admin = db.user_by_name("admin")
    assert admin is not None
    res = tasks.generate(admin)
    assert res["wards"] == 60
    r = notify.retry_queued()             # no live adapters -> no probe, no exception
    assert r["sent"] == 0
    assert no_network == [], f"network was attempted: {no_network[:3]}"


def test_live_adapter_configured_but_offline_never_raises(ops, no_network, monkeypatch):
    from dengue_watch.ops import notify
    monkeypatch.setenv("TWILIO_SID", "x"); monkeypatch.setenv("TWILIO_TOKEN", "y"); monkeypatch.setenv("TWILIO_FROM", "+1")
    r = notify.retry_queued()
    assert r["online"] is False and r["sent"] == 0   # probe failed cleanly, messages stay queued


def test_broken_model_falls_back(ops, monkeypatch):
    from dengue_watch.ops import forecast_bridge as FB

    class Broken:
        def predict(self, X):
            raise RuntimeError("corrupt model file")

    bundle = dict(ops.MODELS[2])
    bundle["model"] = Broken()
    monkeypatch.setitem(ops.MODELS, 2, bundle)
    ops._PRED_CACHE.clear()
    FB._CACHE.clear()
    try:
        fc = FB.ward_forecast("2025-06-02", (1, 2))
        assert set(fc[fc.horizon.eq(2)].source) == {"fallback"}
        assert set(fc[fc.horizon.eq(1)].source) == {"model"}
        assert fc.predicted_cases.notna().all()
    finally:
        FB._CACHE.clear()
        ops._PRED_CACHE.clear()


def test_health_reports_offline_capable(ops):
    from dengue_watch.ops import routes
    h = routes.health()
    assert h["offline_capable"] is True and h["external_calls"] == [] and h["llm_used"] is False


def test_chatbot_is_local():
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src/dengue_watch").glob("*.py"))
    for pat in ("openai", "anthropic", "urllib.request", "import requests", "http.client"):
        assert pat not in src, pat


def test_web_loads_no_remote_assets():
    pat = re.compile(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//|@import\s+url\(\s*["']?https?:|url\(\s*["']?https?:""", re.I)
    bad = []
    for p in (ROOT / "web").rglob("*"):
        if p.suffix in (".html", ".css", ".js") and pat.search(p.read_text(encoding="utf-8", errors="ignore")):
            bad.append(str(p.relative_to(ROOT)))
    assert bad == [], bad
