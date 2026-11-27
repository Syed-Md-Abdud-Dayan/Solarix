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
    assert notify.sms_target("+8801700000007") is None          # demo placeholder: never texted
    assert notify.sms_target("") is None
    assert notify.sms_target("01812345678") == "+8801812345678"  # local BD format -> E.164
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
