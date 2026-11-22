"""Smoke-test model loading, the 0-12 week dashboard predictions and the long-range (2026+) forecast."""
import app

print(app.health_payload())
for city in app.CITIES:
    for horizon in (2, 3, 4):
        payload = app.dashboard_payload({"city": [city], "horizon": [str(horizon)]})
        assert payload["model_connected"] and payload["wards"]
        print(f"OK | {city} | {horizon}-week | {payload['ward_count']} wards | "
              f"{payload['predicted_total_cases']} expected cases | "
              f"priority-1 wards={payload['priority_1_count']}, priority-2 wards={payload['priority_2_count']}")

# long-range forecast beyond the data
f = app.future_payload({"city": ["Dhaka North"], "start": ["2026-01-05"], "end": ["2027-12-31"]})
assert f["weeks"] > 100 and f["yearly"] and f["wards"]
print("OK | future 2026-2027 | Dhaka North | yearly:", f["yearly"])

# chatbot smoke test
for q in ("hello", "risk in Dhaka North next 4 weeks", "my child has fever and keeps vomiting", "ডেঙ্গুর লক্ষণ কী?"):
    r = app.chat_payload({"message": q})
    assert r["reply"]["text"] or r["reply"]["bullets"]
    print("OK | chat |", q, "->", r["intent"], r["severity"])
