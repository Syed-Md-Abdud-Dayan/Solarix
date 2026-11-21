"""Smoke-test model loading and the 2–4 week dashboard predictions."""
import app

print(app.health_payload())
for city in app.CITIES:
    for horizon in (2, 3, 4):
        payload = app.dashboard_payload({"city": [city], "horizon": [str(horizon)]})
        assert payload["model_connected"] and payload["wards"]
        print(f"OK | {city} | {horizon}-week | {payload['ward_count']} wards | "
              f"{payload['predicted_total_cases']} expected cases | "
              f"risk bands={payload['risk_counts']}")
