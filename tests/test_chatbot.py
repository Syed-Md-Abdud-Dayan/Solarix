"""Chatbot tests. Run from the project root:  python -m pytest tests -q   (or: python tests/test_chatbot.py)"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import app  # noqa: E402  (loads real models/data)
from dengue_watch.chatbot import ChatEngine, detect_lang, find_red_flags, extract_entities  # noqa: E402


class PinnedBackend(app.AppBackend):
    """Real models, but with a fixed 'today' so tests don't depend on the wall clock."""
    def __init__(self, today, latest=None):
        self._today = today
        if latest is not None:
            self.latest = pd.Timestamp(latest)

    def today(self):
        return self._today


STALE = ChatEngine(PinnedBackend(date(2026, 11, 22)))                     # data ~46 weeks old -> seasonal forecasts
FRESH = ChatEngine(PinnedBackend(date(2026, 1, 5)))                       # data 1 week old -> 12-week models


def ask(engine, msg, ctx=None, lang=None):
    return engine.reply(msg, ctx, lang)


def text_of(r):
    rp = r["reply"]
    return " ".join([rp.get("title") or "", rp["text"], *rp["bullets"], *rp["notes"]])


# ---------------------------------------------------------------- safety
def test_emergency_personal_red_flags():
    for q in ["my son has fever and keeps vomiting and stomach pain", "bleeding gums and drowsy", "he is vomiting blood",
              "my father has fever and difficulty breathing", "আমার মেয়ের জ্বর আর পেটে ব্যথা, বারবার বমি হচ্ছে"]:
        r = ask(STALE, q)
        assert r["severity"] == "emergency", q
        assert "16263" in text_of(r) or "১৬২৬৩" in text_of(r), q


def test_info_question_about_red_flags_is_not_emergency():
    r = ask(STALE, "does dengue cause bleeding?")
    assert r["severity"] == "info" and r["intent"] == "kb:warning_signs"
    r = ask(STALE, "what are the warning signs?")
    assert r["severity"] == "info" and r["intent"] == "kb:warning_signs"


def test_symptom_check_gives_test_timing_and_no_nsaids():
    r = ask(STALE, "I have fever for 3 days and headache")
    assert r["intent"] == "symptom_check" and r["severity"] == "caution"
    t = text_of(r).lower()
    assert "ns1" in t and "ibuprofen" in t
    r = ask(STALE, "my child has fever")
    assert "today" in text_of(r).lower()      # higher-risk group -> same-day care


def test_no_dosing_or_nsaid_advice():
    t = text_of(ask(STALE, "what medicine should I take for dengue?")).lower()
    assert "avoid aspirin" in t and "i do not give dosing" in t


def test_red_flag_regex_misses_nothing_obvious():
    assert find_red_flags("nose bleeding") and find_red_flags("black stool") and find_red_flags("very little urine")
    assert not find_red_flags("how to prevent dengue")


# ---------------------------------------------------------------- language
def test_language_detection_and_reply():
    assert detect_lang("ডেঙ্গুর লক্ষণ কী?") == "bn" and detect_lang("symptoms") == "en"
    r = ask(STALE, "ডেঙ্গুর লক্ষণ কী?")
    assert r["lang"] == "bn" and r["intent"] == "kb:symptoms"
    r = ask(STALE, "dengue symptoms", lang="bn")
    assert r["lang"] == "bn" and "লক্ষণ" in r["reply"]["title"]


def test_bangla_digits_and_city():
    e = extract_entities("ঢাকা উত্তরে আগামী ৪ সপ্তাহের ঝুঁকি", app.CITIES, date(2026, 11, 22))
    assert e["city"] == "Dhaka North" and e["horizon"] == 4


# ---------------------------------------------------------------- knowledge
def test_knowledge_topics():
    cases = {"how do I prevent dengue": "prevention", "is dengue contagious": "transmission", "can I take ibuprofen": "treatment",
             "papaya leaf juice": "diet", "platelet count low": "platelets", "dengue vaccine": "vaccine", "NS1 test": "testing",
             "dengu symtoms": "symptoms", "hotline number": "hotline", "chikungunya vs dengue": "vs_other"}
    for q, tid in cases.items():
        assert ask(STALE, q)["intent"] == f"kb:{tid}", q


def test_off_topic_and_fallback():
    assert ask(STALE, "tell me a joke")["intent"] == "off_topic"
    assert ask(STALE, "asdf qwer zxcv")["intent"] == "fallback"
    assert ask(STALE, "")["intent"] == "empty"


# ---------------------------------------------------------------- data answers
def test_stale_data_uses_seasonal_forecast_and_says_so():
    r = ask(STALE, "risk in Dhaka North next 4 weeks")
    assert r["intent"] == "forecast:city" and "Data note" in text_of(r)


def test_future_month_is_peak_season():
    r = ask(STALE, "forecast for August 2026 in Dhaka North")
    t = text_of(r)
    assert r["intent"] == "forecast:time" and "August 2026" in t
    assert r["reply"]["table"]["rows"], "ward table missing"
    low = ask(STALE, "forecast for January 2027 in Dhaka North")
    assert "low season" in text_of(low)


def test_fresh_data_uses_models_and_ward_detail():
    r = ask(FRESH, "risk in Dhaka North next 4 weeks")
    assert r["intent"] == "risk:city" and r["context"]["city"] == "Dhaka North" and r["context"]["horizon"] == 4
    r2 = ask(FRESH, "what about Gazipur?", r["context"])          # follow-up keeps horizon, swaps city
    assert r2["context"]["city"] == "Gazipur" and r2["context"]["horizon"] == 4
    w = ask(FRESH, "ward 5 in dhaka south")
    assert w["intent"] == "ward:detail" and "DSCC_Ward_05" in text_of(w)
    top = ask(FRESH, "top wards in Chattogram")
    assert top["intent"] == "top:wards" and len(top["reply"]["table"]["rows"]) == 5


def test_whatif_rain_increases_peak_season_cases():
    r = ask(STALE, "what if rainfall doubles in Gazipur")
    assert r["intent"] == "whatif" and r["entities"]["rain_mult"] == 2.0
    assert "+" in r["reply"]["text"] and "peak season" in text_of(r)   # off-season -> switched to peak season


def test_compare_history_accuracy_season():
    assert ask(STALE, "compare Dhaka North and Gazipur")["intent"] == "compare"
    h = ask(STALE, "how many cases in 2024 all cities")
    assert h["intent"] == "history:period" and "6,760" in text_of(h)
    a = ask(STALE, "how accurate is the model")
    assert a["intent"] == "accuracy" and "AUC" in text_of(a)
    s = ask(STALE, "when is dengue season")
    assert s["intent"] == "kb:season" and "August" in text_of(s)


def test_actions_by_risk_level():
    r = ask(STALE, "what should we do in Gazipur")
    assert r["intent"] == "actions" and r["reply"]["bullets"]


# ---------------------------------------------------------------- robustness
def test_context_is_sanitised_and_message_truncated():
    r = ask(STALE, "hello", {"city": "Atlantis", "horizon": "abc", "evil": "<script>"})
    assert "evil" not in r["context"] and "city" not in r["context"]
    long = ask(STALE, "dengue " * 400)
    assert long["intent"]


def test_http_payload_validation():
    import pytest
    with pytest.raises(ValueError):
        app.chat_payload({"message": 5})
    with pytest.raises(ValueError):
        app.chat_payload([])
    assert app.chat_payload({"message": "hi"})["intent"] == "greet"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
