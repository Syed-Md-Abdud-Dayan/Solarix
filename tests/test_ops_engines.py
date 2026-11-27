"""Unit tests for the Phase 2 engines: supply rule, bridge, allocation, overflow, simulator."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dengue_watch.ops import allocation as A
from dengue_watch.ops import config as C
from dengue_watch.ops import overflow as O

ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------- supply rule
def test_supply_rule_matches_onsite_dataset():
    path = ROOT / "data/bangladesh_dengue_onsite.csv"
    if not path.exists():
        pytest.skip("onsite CSV not present")
    d = pd.read_csv(path)
    for key, col in (("saline_bags", "saline_bags_needed"), ("diagnostic_kits", "diagnostic_kits_needed"),
                     ("hospital_beds", "hospital_beds_required")):
        pred = np.floor(d.dengue_cases * C.SUPPLY_RATES[key] + 0.5)
        assert (pred == d[col]).all(), key


def test_demand_rule_examples():
    assert A.demand_for_cases(10) == {"saline_bags": 24, "diagnostic_kits": 12, "hospital_beds": 3}
    assert A.demand_for_cases(0) == {"saline_bags": 0, "diagnostic_kits": 0, "hospital_beds": 0}
    assert A.demand_for_cases(10, buffer=0.1)["saline_bags"] == 26


# ----------------------------------------------------------------- allocation
def _wards():
    rows = []
    risks = ["Critical", "High", "Medium", "Low"]
    for i in range(16):
        risk = risks[i % 4]
        cases = {"Critical": 11, "High": 6, "Medium": 3, "Low": 1}[risk] + (i % 3)
        rows.append({"ward_id": f"W{i:02d}", "city": "X" if i < 8 else "Y",
                     "population_density_sqkm": 20000 + 4000 * i, "predicted_cases": float(cases), "risk": risk})
    return rows


@pytest.mark.parametrize("pct", [30, 45, 60, 80, 100])
def test_allocation_never_exceeds_stock(pct):
    res = A.allocate(_wards(), pct, 10)
    for s, t in res["totals"].items():
        assert t["allocated"] <= t["available"]
        assert all(0 <= w["allocated"][s] <= w["required"][s] for w in res["wards"])
    assert res["crews"]["assigned"] <= 10


def test_allocation_monotone_in_stock():
    prev = None
    for pct in range(30, 101, 5):
        res = A.allocate(_wards(), pct, 10)
        alloc = {w["ward_id"]: w["allocated"]["saline_bags"] for w in res["wards"]}
        if prev:
            assert sum(alloc.values()) >= sum(prev.values())
            top = res["wards"][0]["ward_id"]
            assert alloc[top] >= prev[top]
        prev = alloc


def test_full_stock_means_no_deficit_and_30pct_flags():
    full = A.allocate(_wards(), 100, 100)
    assert full["counts"]["OK"] == len(_wards()) and not full["warnings"]
    low = A.allocate(_wards(), 30, 100)
    assert low["counts"]["CRITICAL"] > 0 and low["warnings"]
    for w in low["wards"]:
        if w["fulfilment_pct"] < 60:
            assert w["deficit_level"] == "CRITICAL"
        elif w["fulfilment_pct"] < 100:
            assert w["deficit_level"] == "WARNING"


def test_critical_wards_served_before_low():
    res = A.allocate(_wards(), 40, 10)
    crit = [w["fulfilment"]["saline_bags"] for w in res["wards"] if w["risk"] == "Critical"]
    low = [w["fulfilment"]["saline_bags"] for w in res["wards"] if w["risk"] == "Low"]
    assert min(crit) >= max(low)


def test_density_breaks_ties():
    w = [{"ward_id": "A", "city": "X", "population_density_sqkm": 20000, "predicted_cases": 6.0, "risk": "High"},
         {"ward_id": "B", "city": "X", "population_density_sqkm": 70000, "predicted_cases": 6.0, "risk": "High"}]
    res = A.allocate(w, 50, 2, equity=False)
    by = {r["ward_id"]: r for r in res["wards"]}
    assert by["B"]["priority_rank"] == 1
    assert by["B"]["allocated"]["saline_bags"] >= by["A"]["allocated"]["saline_bags"]


def test_crews_assigned_by_risk_order_and_deterministic():
    a = A.allocate(_wards(), 60, 5)
    b = A.allocate(_wards(), 60, 5)
    assert a == b
    got = [w for w in a["wards"] if w["crews_assigned"] > 0]
    order = {k: i for i, k in enumerate(C.RISK_ORDER)}
    starved = [w for w in a["wards"] if w["crew_deficit"] > 0]
    if starved:
        assert max(order[w["risk"]] for w in got) <= max(order[w["risk"]] for w in starved)
    assert a["crews"]["assigned"] == 5


# ----------------------------------------------------------------- overflow
def _beds():
    return [
        {"ward_id": "A1", "city": "A", "bed_demand": 9, "capacity": 4},
        {"ward_id": "A2", "city": "A", "bed_demand": 1, "capacity": 5},
        {"ward_id": "A3", "city": "A", "bed_demand": 2, "capacity": 6},
        {"ward_id": "B1", "city": "B", "bed_demand": 8, "capacity": 3},
        {"ward_id": "B2", "city": "B", "bed_demand": 2, "capacity": 3},
        {"ward_id": "C1", "city": "C", "bed_demand": 0, "capacity": 20},
    ]


def test_overflow_never_crosses_cities():
    res = O.route(_beds())
    city = {w["ward_id"]: w["city"] for w in _beds()}
    assert res["transfers"]
    for t in res["transfers"]:
        assert city[t["from_ward"]] == city[t["to_ward"]] == t["city"]


def test_overflow_conserves_patients_and_respects_capacity():
    res = O.route(_beds())
    by = {w["ward_id"]: w for w in res["wards"]}
    assert sum(w["sent"] for w in res["wards"]) == sum(w["received"] for w in res["wards"]) == \
        sum(t["patients"] for t in res["transfers"])
    for w in res["wards"]:
        assert w["remaining_headroom"] >= 0 and w["net_deficit"] >= 0
    assert by["A1"]["net_deficit"] == 0                       # 5 extra fit into A2/A3
    b = next(c for c in res["cities"] if c["city"] == "B")
    assert b["surge"] and b["unresolved_deficit"] == 4        # city B lacks beds; C1 must NOT help
    assert by["C1"]["received"] == 0
    assert any(a["city"] == "B" for a in res["alerts"])


def test_overflow_prefers_lowest_burden():
    res = O.route([{"ward_id": "S", "city": "Z", "bed_demand": 5, "capacity": 4},
                   {"ward_id": "R1", "city": "Z", "bed_demand": 4, "capacity": 5},
                   {"ward_id": "R2", "city": "Z", "bed_demand": 0, "capacity": 5}])
    assert res["transfers"] == [{"from_ward": "S", "to_ward": "R2", "city": "Z", "patients": 1}]


def test_pooled_capacity_sums_to_pool():
    wards = [{"ward_id": f"W{i}", "city": "Q", "population_density_sqkm": 10000 * (i + 1), "history_beds": [0, 1, 2, 3] * 10}
             for i in range(4)]
    caps = O.pooled_capacities(wards, 99)
    weekly_total = [sum(week) for week in zip(*(w["history_beds"] for w in wards))]
    pool = O.baseline_capacity(weekly_total, 99)
    assert pool == 12   # all four wards peak together: 4 x 3 beds
    assert sum(caps.values()) == pool
    assert caps["W3"] >= caps["W0"]


def test_pooled_capacity_rejects_misaligned_history():
    wards = [{"ward_id": "A", "city": "Q", "population_density_sqkm": 1, "history_beds": [1, 2]},
             {"ward_id": "B", "city": "Q", "population_density_sqkm": 1, "history_beds": [1]}]
    with pytest.raises(ValueError):
        O.pooled_capacities(wards)


# ----------------------------------------------------------------- model-backed (bridge / simulator)
@pytest.fixture(scope="module")
def bridge():
    import app  # loads the 13 models once
    from dengue_watch.ops import forecast_bridge as FB
    FB.init(app)
    FB.set_force_fallback(False)
    return app, FB


def test_bridge_matches_phase1_predict_at(bridge):
    app, FB = bridge
    origin = FB.snap_origin("2025-08-04")
    ids = sorted(app._df.ward_id.unique())
    for h in (1, 3):
        v = FB.predict_variants(origin, h, [(w, w, 1.0, 1.0) for w in ids]).set_index("ward_id").predicted_cases
        ref = app.predict_at(origin, h).set_index("ward_id").predicted_cases.reindex(v.index)
        assert np.allclose(v.values, ref.values)


def test_fallback_forecast_is_flagged(bridge):
    _, FB = bridge
    FB.set_force_fallback(True)
    try:
        fc = FB.forecast_payload("2025-08-04")
        assert fc["source"] == "fallback" and len(fc["wards"]) == 60
    finally:
        FB.set_force_fallback(False)


def test_simulator_monotone_and_ward_specific(bridge):
    from dengue_watch.ops import simulator as S
    curves = S.response_curves("2025-08-04")
    for (_, _), g in curves.groupby(["ward_id", "horizon"]):
        p = g.sort_values("crews").prevented.values
        assert (np.diff(p) >= -1e-9).all() and (p >= 0).all()
    tot = curves[curves.crews.eq(2)].groupby("ward_id").prevented.sum()
    base = curves[curves.crews.eq(0)].groupby("ward_id").baseline.sum()
    pct = (tot / base.replace(0, np.nan)).dropna()
    assert pct.std() > 0.01, "effect must differ by ward (not a flat percentage)"


def test_coverage_has_diminishing_returns():
    from dengue_watch.ops import simulator as S
    gains = [S.coverage(k + 1, 1.0) - S.coverage(k, 1.0) for k in range(4)]
    assert all(a > b for a, b in zip(gains, gains[1:]))
    assert S.coverage(1, 1.5) < S.coverage(1, 1.0)            # denser ward -> less coverage per crew


def test_recommendation_respects_budget_and_ranking(bridge):
    from dengue_watch.ops import simulator as S
    r = S.recommend(8, "2025-08-04")
    assert sum(r["recommended_deployment"].values()) <= 8
    roi = [w["roi_1_crew"] for w in r["roi_ranking"]]
    assert roi == sorted(roi, reverse=True)
    gains = [s["marginal_cases_prevented"] for s in r["greedy_steps"]]
    assert all(g > 0 for g in gains)
    with pytest.raises(ValueError):
        S.simulate({"DNCC_Ward_01": 4, "DNCC_Ward_02": 4}, "2025-08-04", crew_cap=5)


def test_planner_end_to_end(bridge):
    from dengue_watch.ops import planner
    for pct in (100, 30):
        p = planner.plan("2025-08-04", stock_pct=pct, total_crews=20)
        assert len(p["allocation"]["wards"]) == 60
        city = {w["ward_id"]: w["city"] for w in p["allocation"]["wards"]}
        assert all(city[t["from_ward"]] == city[t["to_ward"]] for t in p["overflow"]["transfers"])
    assert planner.plan("2025-08-04", stock_pct=100)["allocation"]["counts"]["CRITICAL"] == 0
    assert planner.plan("2025-08-04", stock_pct=30)["allocation"]["warnings"]
