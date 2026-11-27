"""Orchestrates forecast -> allocation -> overflow for one planning week (pure, local)."""
from __future__ import annotations

from functools import lru_cache

from . import config as C
from . import forecast_bridge as FB
from . import allocation as A
from . import overflow as O


@lru_cache(maxsize=1)
def baseline_capacities() -> dict:
    """ASSUMED capacity per ward from its history.

    The historical weekly hospital_beds_required is reproduced exactly from
    dengue_cases with the verified dataset rule (see scripts/verify_onsite_dataset.py),
    so the runtime does not even need the onsite CSV to be present.
    """
    df = FB.data().sort_values(["ward_id", "date"])
    rate = C.SUPPLY_RATES["hospital_beds"]
    static = FB.ward_static()
    wards = []
    for ward, g in df.groupby("ward_id"):
        wards.append({"ward_id": ward, "city": static.loc[ward, "city"],
                      "population_density_sqkm": float(static.loc[ward, "population_density_sqkm"]),
                      "history_beds": [A.round_half_up(rate * c) for c in g.dengue_cases.tolist()]})
    return O.pooled_capacities(wards)


def plan(origin=None, horizon: int = C.DEFAULT_PLAN_HORIZON, stock_pct: float = 100,
         total_crews: int = C.DEFAULT_TOTAL_CREWS, buffer: float = C.DEFAULT_SAFETY_BUFFER,
         full_stock_override: dict | None = None, capacities: dict | None = None,
         occupied: dict | None = None, equity: bool = True) -> dict:
    window = sorted({1, 2, 3, 4} | {int(horizon)})
    fc = FB.ward_forecast(origin, tuple(window))
    week = fc[fc.horizon.eq(int(horizon))]
    wards = [{"ward_id": r.ward_id, "city": r.city, "population_density_sqkm": float(r.population_density_sqkm),
              "predicted_cases": float(r.predicted_cases), "risk": r.risk, "mae": float(r.mae)} for r in week.itertuples()]
    peak = A.full_stock_from_peak({h: g.predicted_cases.tolist() for h, g in fc.groupby("horizon")}, buffer)
    full = dict(peak)
    for k, v in (full_stock_override or {}).items():
        if k in full and v is not None and int(v) > 0:
            full[k] = int(v)
    alloc = A.allocate(wards, stock_pct, total_crews, full, buffer, equity)
    alloc["full_stock_basis"] = "admin override" if full_stock_override else "peak-week demand of the 4-week window"
    mae = {w["ward_id"]: w["mae"] for w in wards}
    for r in alloc["wards"]:
        r["uncertainty_cases"] = round(mae[r["ward_id"]], 2)
    caps = dict(baseline_capacities())
    caps.update({k: int(v) for k, v in (capacities or {}).items()})
    beds = [{"ward_id": r["ward_id"], "city": r["city"], "bed_demand": r["required"]["hospital_beds"],
             "capacity": caps.get(r["ward_id"], C.MIN_WARD_BEDS), "occupied": (occupied or {}).get(r["ward_id"], 0)}
            for r in alloc["wards"]]
    ovf = O.route(beds)
    trends = {}
    for ward, g in fc.groupby("ward_id"):
        trends[ward] = [{"horizon": int(r.horizon), "target_date": r.target_date,
                         "predicted_cases": round(float(r.predicted_cases), 2), "risk": r.risk} for r in g.sort_values("horizon").itertuples()]
    return {"origin": fc.origin.iloc[0], "horizon": int(horizon), "target_date": week.target_date.iloc[0],
            "source": "fallback" if (fc.source == "fallback").any() else "model",
            "allocation": alloc, "overflow": ovf, "trends": trends,
            "risk_counts": week.risk.value_counts().reindex(C.RISK_ORDER, fill_value=0).astype(int).to_dict()}
