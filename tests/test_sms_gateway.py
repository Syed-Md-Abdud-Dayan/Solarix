"""Own-SIM SMS adapter (SMS Gateway for Android): payload, safety guards. No real network."""
import json
import urllib.request

import pytest

from dengue_watch.ops import notify


@pytest.fixture
def gateway(monkeypatch):
    for k in ("SMS_TEST_TO", "TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM", "SMSGATE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMSGATE_USER", "u")
    monkeypatch.setenv("SMSGATE_PASSWORD", "p")
    calls = []

    class Resp:
        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def test_sms_target_rules(monkeypatch):
    monkeypatch.delenv("SMS_TEST_TO", raising=False)
    assert notify.sms_target("+8801700000007") is None
    assert notify.sms_target("") is None
    assert notify.sms_target("01812345678") == "+8801812345678"
    monkeypatch.setenv("SMS_TEST_TO", "+8801999999999")
    assert notify.sms_target("+8801700000007") == "+8801999999999"


def test_gateway_payload(gateway):
    assert "sms" in notify.live_adapters()
    ok, err = notify._send_live({"channel": "sms", "phone": "01812345678", "body": "hello"})
    assert ok, err
    req = gateway[0]
    assert req.full_url == notify.SMSGATE_CLOUD_URL
    assert json.loads(req.data) == {"textMessage": {"text": "hello"}, "phoneNumbers": ["+8801812345678"]}
    assert req.get_header("Authorization").startswith("Basic ")


def test_gateway_local_url_and_placeholder_skip(gateway, monkeypatch):
    monkeypatch.setenv("SMSGATE_URL", "http://192.168.0.5:8080/message")
    ok, err = notify._send_live({"channel": "sms", "phone": "+8801700000003", "body": "x"})
    assert not ok and "placeholder" in err and gateway == []
    ok, _ = notify._send_live({"channel": "sms", "phone": "+8801812345678", "body": "x"})
    assert ok and gateway[0].full_url == "http://192.168.0.5:8080/message"


@pytest.fixture
def outbox(monkeypatch):
    from dengue_watch.ops import db
    db.init_db()
    db.x("DELETE FROM outbox")
    monkeypatch.setattr(notify, "online", lambda timeout=1.5: True)

    def add(phone, i):
        db.x("INSERT INTO outbox(dispatch_id, ward_id, team, channel, lang, recipient, phone, body, status, created_at)"
             " VALUES (?,?,?,?,?,?,?,?,?,?)", (f"T{i}", "W1", "saline", "sms", "en", f"u{i}", phone, "x", "queued", db.now()))

    def status():
        return {r["recipient"]: (r["status"], r["error"]) for r in db.q("SELECT recipient, status, error FROM outbox")}
    return add, status


def test_placeholders_do_not_use_sms_budget(gateway, outbox, monkeypatch):
    add, status = outbox
    monkeypatch.setenv("SMS_MAX_PER_RUN", "2")
    for i in range(5):
        add(f"+880170000000{i}", i)
    add("01812345678", 5)
    add("01812345679", 6)
    r = notify.retry_queued()
    s = status()
    assert all(s[f"u{i}"][0] == "failed" for i in range(5))
    assert s["u5"][0] == s["u6"][0] == "sent" and len(gateway) == 2
    assert r["sent"] == 2 and r["failed"] == 5 and r["still_queued"] == 0


def _fail_with(monkeypatch, code):
    import urllib.error

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", boom)


@pytest.mark.parametrize("code,expected", [(401, "failed"), (400, "failed"), (429, "queued"), (503, "queued")])
def test_permanent_errors_fail_transient_stay_queued(gateway, outbox, monkeypatch, code, expected):
    add, status = outbox
    add("01812345678", 0)
    _fail_with(monkeypatch, code)
    notify.retry_queued()
    assert status()["u0"][0] == expected


def test_lan_gateway_sends_without_internet(gateway, outbox, monkeypatch):
    add, status = outbox
    monkeypatch.setattr(notify, "online", lambda timeout=1.5: False)
    add("01812345678", 0)
    monkeypatch.setenv("SMSGATE_URL", "https://api.example.com/x")
    assert notify.retry_queued()["sent"] == 0 and gateway == []
    monkeypatch.setenv("SMSGATE_URL", "http://192.168.0.5:8080/message")
    r = notify.retry_queued()
    assert r["sent"] == 1 and r["online"] is False and status()["u0"][0] == "sent"
