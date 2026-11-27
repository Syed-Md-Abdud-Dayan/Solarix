"""Smoke-test the Phase 2 engines and endpoints without a browser (python verify_ops.py)."""
import os
import tempfile

os.environ.setdefault("OPS_DB", os.path.join(tempfile.mkdtemp(), "verify.db"))
import app  # noqa: E402
from dengue_watch.ops import dispatch as D, planner, routes, simulator  # noqa: E402

h = routes.health()
assert h["offline_capable"] and not h["external_calls"]
print("OK | ops health | offline_capable =", h["offline_capable"], "| models =", h["models_loaded"], "| llm_used =", h["llm_used"])

for pct in (100, 60, 30):
    p = planner.plan("2025-08-04", stock_pct=pct, total_crews=40)
    a, o = p["allocation"], p["overflow"]
    for s, t in a["totals"].items():
        assert t["allocated"] <= t["available"]
    city = {w["ward_id"]: w["city"] for w in a["wards"]}
    assert all(city[t["from_ward"]] == city[t["to_ward"]] for t in o["transfers"]), "cross-city transfer!"
    print(f"OK | alloc {pct:>3}% | saline {a['totals']['saline_bags']['allocated']}/{a['totals']['saline_bags']['required']} | "
          f"flags {a['counts']} | crews {a['crews']['assigned']}/{a['crews']['needed']} | "
          f"beds routed {o['summary']['patients_routed']} | city surge {o['summary']['unresolved_deficit']}")

sim = simulator.recommend(10, "2025-08-04")
print("OK | simulator | deployment", sim["recommended_deployment"], "| prevented", sim["total"]["cases_prevented"],
      "| ROI", sim["total"]["roi"], "| top ROI ward", sim["roi_ranking"][0]["ward_id"])

ctx = D.ward_context(p, a["wards"][0]["ward_id"])
s = D.sms(ctx, "saline", "en")
assert len(s["short"]) <= 160
print("OK | dispatch | SMS", s["short_chars"], "chars:", s["short"])
print("OK | dispatch | BN SMS:", D.sms(ctx, "spraying", "bn")["short"].encode("ascii", "replace").decode()[:40], "...")
assert "Predicted cases" in D.brief_html(ctx, "en")
print("OK | brief html + pdf:", "pdf bytes" if D.brief_pdf(ctx) else "HTML print fallback (reportlab not installed)")
