"""Constrained resource allocation engine (Requirement 1).

Pure functions, no I/O, no network. Input is a list of ward records with the
forecast for the planning week; output is a per-ward allocation plus a summary.

Math (all constants in config.py)
---------------------------------
demand_s(w)   = round_half_up(rate_s * predicted_cases(w) * (1 + buffer))
density_f(w)  = (density(w) / median_density) ** DENSITY_EXPONENT
priority(w)   = RISK_WEIGHT[risk(w)] * (predicted_cases(w) + PRIORITY_CASE_FLOOR) * density_f(w)
stock_s       = floor(full_stock_s * stock_pct / 100)
full_stock_s  = total demand of the PEAK week in the planning window (or admin override)

For each supply s independently:
  1. Equity guard - in priority order, Critical / High wards first receive
     ceil(EQUITY_FLOOR[risk] * demand) units (while stock lasts).
  2. Greedy fill - in priority order, top every ward up to its full demand.
Ties are broken by ward_id, so the result is deterministic.

Why greedy is optimal here: the objective is to maximise priority-weighted units
delivered, sum_w priority(w) * x_w, subject to sum_w x_w <= stock and 0 <= x_w <= demand_w.
Every unit costs 1 unit of stock, so this is a fractional knapsack with equal
weights; the optimum fills wards in descending value-per-unit (= priority). The
equity floor is an explicit fairness constraint applied before that.

Crews: crews_needed(w) = clamp(ceil(CREW_BASE[risk] * density_f), 0, MAX_CREWS_PER_WARD),
assigned in strict risk order (Critical > High > Medium > Low), then priority.
"""
from __future__ import annotations

import math
from statistics import median

from . import config as C

SUPPLIES = ("saline_bags", "diagnostic_kits", "hospital_beds")


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def demand_for_cases(cases: float, buffer: float = 0.0) -> dict:
    """Dataset rule (config.SUPPLY_RATES) applied to (possibly fractional) cases."""
    c = max(0.0, float(cases)) * (1.0 + max(0.0, buffer))
    return {s: round_half_up(C.SUPPLY_RATES[s] * c) for s in SUPPLIES}


def density_factor(density: float, med: float) -> float:
    return (max(density, 1.0) / max(med, 1.0)) ** C.DENSITY_EXPONENT


def priority_score(risk: str, cases: float, dfac: float) -> float:
    return C.RISK_WEIGHTS.get(risk, 1.0) * (max(cases, 0.0) + C.PRIORITY_CASE_FLOOR) * dfac


def crews_needed(risk: str, dfac: float) -> int:
    base = C.CREW_BASE_BY_RISK.get(risk, 0.0)
    return int(min(C.MAX_CREWS_PER_WARD, max(0, math.ceil(base * dfac - 1e-9)))) if base > 0 else 0


def full_stock_from_peak(window_cases: dict[int, list[float]], buffer: float = 0.0) -> dict:
    """100% stock = demand of the worst week in the planning window.

    window_cases: {horizon: [cases per ward]}.
    """
    best = {s: 0 for s in SUPPLIES}
    for cases in window_cases.values():
        tot = {s: 0 for s in SUPPLIES}
        for c in cases:
            for s, v in demand_for_cases(c, buffer).items():
                tot[s] += v
        for s in SUPPLIES:
            best[s] = max(best[s], tot[s])
    return best


def _level(ratio: float) -> str:
    if ratio >= C.DEFICIT_WARNING_BELOW - 1e-9:
        return "OK"
    if ratio < C.DEFICIT_CRITICAL_BELOW:
        return "CRITICAL"
    return "WARNING"


def allocate(wards: list[dict], stock_pct: float = 100, total_crews: int = C.DEFAULT_TOTAL_CREWS,
             full_stock: dict | None = None, buffer: float = C.DEFAULT_SAFETY_BUFFER,
             equity: bool = True) -> dict:
    """Allocate scarce regional stock and spraying crews across wards.

    wards: [{ward_id, city, population_density_sqkm, predicted_cases, risk}]
    stock_pct: 30..100 (clamped) share of full_stock available this week.
    full_stock: {supply: units at 100%}; default = this week's total demand.
    """
    stock_pct = float(min(C.STOCK_PCT_MAX, max(C.STOCK_PCT_MIN, stock_pct)))
    total_crews = max(0, int(total_crews))
    med = median([w["population_density_sqkm"] for w in wards]) if wards else 1.0

    rows = []
    for w in wards:
        dfac = density_factor(w["population_density_sqkm"], med)
        rows.append({
            "ward_id": w["ward_id"], "city": w["city"], "risk": w["risk"],
            "predicted_cases": round(float(w["predicted_cases"]), 2),
            "population_density_sqkm": int(w["population_density_sqkm"]),
            "density_factor": round(dfac, 3),
            "priority_score": round(priority_score(w["risk"], w["predicted_cases"], dfac), 3),
            "required": demand_for_cases(w["predicted_cases"], buffer),
            "allocated": {s: 0 for s in SUPPLIES},
            "crews_needed": crews_needed(w["risk"], dfac),
            "crews_assigned": 0,
        })
    # deterministic priority order
    rows.sort(key=lambda r: (-r["priority_score"], r["ward_id"]))
    for i, r in enumerate(rows, 1):
        r["priority_rank"] = i

    if full_stock is None:
        full_stock = {s: sum(r["required"][s] for r in rows) for s in SUPPLIES}
    available = {s: int(math.floor(full_stock.get(s, 0) * stock_pct / 100.0)) for s in SUPPLIES}

    for s in SUPPLIES:
        left = available[s]
        if equity:
            for r in rows:
                share = C.EQUITY_FLOOR.get(r["risk"], 0.0)
                if share <= 0 or left <= 0:
                    continue
                give = min(left, math.ceil(share * r["required"][s]))
                r["allocated"][s] += give
                left -= give
        for r in rows:
            if left <= 0:
                break
            give = min(left, r["required"][s] - r["allocated"][s])
            if give > 0:
                r["allocated"][s] += give
                left -= give

    # crews: strict risk order, then priority
    risk_rank = {k: i for i, k in enumerate(C.RISK_ORDER)}
    crew_left = total_crews
    for r in sorted(rows, key=lambda r: (risk_rank.get(r["risk"], 9), -r["priority_score"], r["ward_id"])):
        give = min(crew_left, r["crews_needed"])
        r["crews_assigned"] = give
        crew_left -= give
    spray_seq = [r for r in sorted(rows, key=lambda r: (risk_rank.get(r["risk"], 9), -r["priority_score"], r["ward_id"]))
                 if r["crews_needed"] > 0]
    for i, r in enumerate(spray_seq, 1):
        r["spray_sequence"] = i

    warnings, shorted = [], {k: {"wards": 0, "units_short": 0} for k in C.RISK_ORDER}
    for r in rows:
        r["deficit"] = {s: r["required"][s] - r["allocated"][s] for s in SUPPLIES}
        r["fulfilment"] = {s: (1.0 if r["required"][s] == 0 else round(r["allocated"][s] / r["required"][s], 4))
                           for s in SUPPLIES}
        worst = min(r["fulfilment"].values())
        r["fulfilment_pct"] = round(worst * 100, 1)
        r["deficit_level"] = _level(worst)
        r.setdefault("spray_sequence", None)
        r["crew_deficit"] = r["crews_needed"] - r["crews_assigned"]
        cut = [f"{C.SUPPLY_LABELS[s]} -{r['deficit'][s]}" for s in SUPPLIES if r["deficit"][s] > 0]
        if r["crew_deficit"] > 0:
            cut.append(f"Spraying crews -{r['crew_deficit']}")
        r["what_got_cut"] = (", ".join(cut) + f" (priority rank {r['priority_rank']} of {len(rows)})") if cut else ""
        if r["deficit_level"] != "OK":
            shorted[r["risk"]]["wards"] += 1
            shorted[r["risk"]]["units_short"] += sum(r["deficit"].values())
            warnings.append({"ward_id": r["ward_id"], "city": r["city"], "risk": r["risk"],
                             "level": r["deficit_level"], "fulfilment_pct": r["fulfilment_pct"],
                             "deficit": r["deficit"],
                             "message": f"{r['ward_id']} ({r['risk']}) can only be {r['fulfilment_pct']:.0f}% supplied: {r['what_got_cut']}"})
    warnings.sort(key=lambda w: (w["level"] != "CRITICAL", w["fulfilment_pct"], w["ward_id"]))

    totals = {s: {"required": sum(r["required"][s] for r in rows),
                  "available": available[s], "full_stock": int(full_stock.get(s, 0)),
                  "allocated": sum(r["allocated"][s] for r in rows)} for s in SUPPLIES}
    for s in SUPPLIES:
        totals[s]["deficit"] = totals[s]["required"] - totals[s]["allocated"]
        totals[s]["unused"] = totals[s]["available"] - totals[s]["allocated"]

    replenish = {}
    for r in rows:
        c = replenish.setdefault(r["city"], {s: 0 for s in SUPPLIES})
        for s in SUPPLIES:
            c[s] += r["deficit"][s]

    return {
        "stock_pct": stock_pct, "total_crews": total_crews, "buffer": buffer, "equity_guard": equity,
        "crews": {"total": total_crews, "needed": sum(r["crews_needed"] for r in rows),
                  "assigned": total_crews - crew_left, "unused": crew_left,
                  "unassigned_wards": [r["ward_id"] for r in spray_seq if r["crew_deficit"] > 0]},
        "totals": totals, "wards": rows, "warnings": warnings,
        "shorted_by_risk": shorted,
        "counts": {lvl: sum(r["deficit_level"] == lvl for r in rows) for lvl in ("OK", "WARNING", "CRITICAL")},
        "replenishment_by_city": replenish,
    }
