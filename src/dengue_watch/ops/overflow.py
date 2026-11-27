"""Hospital surge and cross-ward overflow routing (Requirement 2).

Pure, deterministic, no network.

Per ward w:
    effective_capacity(w) = max(0, capacity(w) - occupied(w))     (occupied = optional offset
                                                                    entered by hospital users)
    deficit(w)  = max(0, bed_demand(w) - effective_capacity(w))
    headroom(w) = max(0, effective_capacity(w) - bed_demand(w))

Routing, independently for EACH city pool (never across cities):
    repeat for every patient in deficit, senders in descending deficit (ward_id ties):
        receiver = ward in the SAME city with headroom > 0 and the lowest projected
                   utilisation (load / effective_capacity) after the transfer, ward_id ties
    This is a water-filling rule: overflow goes to the lowest-burden ward first and load
    is levelled across receivers. Patients are conserved: sum(sent) == sum(received).
If the whole city lacks headroom, the unrouted remainder is reported as a CITY SURGE.
"""
from __future__ import annotations

import math

from . import config as C


def baseline_capacity(history_beds: list[float], percentile: float = C.CAPACITY_PERCENTILE) -> int:
    """ceil(P_q) of a weekly bed-demand series (used on a city's weekly totals), min MIN_WARD_BEDS."""
    vals = sorted(float(v) for v in history_beds)
    if not vals:
        return C.MIN_WARD_BEDS
    k = (len(vals) - 1) * percentile / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    q = vals[lo] + (vals[hi] - vals[lo]) * (k - lo)
    return max(C.MIN_WARD_BEDS, int(math.ceil(q - 1e-9)))


def pooled_capacities(wards: list[dict], percentile: float = C.CAPACITY_PERCENTILE) -> dict:
    """ASSUMED capacity: city pool = ceil(P_q of the city's weekly TOTAL bed demand),
    split across the city's wards by population density.

    wards: [{ward_id, city, population_density_sqkm, history_beds: [..]}] -> {ward_id: beds}
    history_beds must be aligned by week (same weeks, same order) within a city.
    Largest-remainder rounding keeps sum(capacity) == city pool exactly.
    """
    out = {}
    for city in sorted({w["city"] for w in wards}):
        g = sorted([w for w in wards if w["city"] == city], key=lambda w: w["ward_id"])
        lengths = {len(w["history_beds"]) for w in g}
        if len(lengths) != 1:
            raise ValueError(f"{city}: ward bed histories are not aligned by week")
        weekly_total = [sum(week) for week in zip(*(w["history_beds"] for w in g))]
        pool = baseline_capacity(weekly_total, percentile)
        dens = sum(float(w["population_density_sqkm"]) for w in g) or 1.0
        share = {w["ward_id"]: pool * float(w["population_density_sqkm"]) / dens for w in g}
        base = {k: int(math.floor(v)) for k, v in share.items()}
        rest = pool - sum(base.values())
        for k in sorted(share, key=lambda k: (-(share[k] - base[k]), k))[:rest]:
            base[k] += 1
        for k, v in base.items():
            out[k] = max(C.MIN_WARD_BEDS, v)
    return out


def route(wards: list[dict]) -> dict:
    """wards: [{ward_id, city, bed_demand, capacity, occupied?}] -> routing plan."""
    state = {}
    for w in wards:
        cap = max(0, int(w["capacity"]) - int(w.get("occupied", 0) or 0))
        dem = max(0, int(w["bed_demand"]))
        state[w["ward_id"]] = {"ward_id": w["ward_id"], "city": w["city"], "bed_demand": dem,
                               "capacity": int(w["capacity"]), "occupied": int(w.get("occupied", 0) or 0),
                               "effective_capacity": cap, "deficit": max(0, dem - cap),
                               "headroom": max(0, cap - dem), "received": 0, "sent": 0}

    transfers: dict[tuple, int] = {}
    alerts, cities = [], {}
    for city in sorted({s["city"] for s in state.values()}):
        pool = [s for s in state.values() if s["city"] == city]
        senders = sorted([s for s in pool if s["deficit"] > 0], key=lambda s: (-s["deficit"], s["ward_id"]))
        for snd in senders:
            need = snd["deficit"]
            while need > 0:
                cands = [r for r in pool if r is not snd and r["headroom"] - r["received"] > 0]
                if not cands:
                    break
                rcv = min(cands, key=lambda r: ((r["bed_demand"] + r["received"] + 1) / max(r["effective_capacity"], 1),
                                                r["ward_id"]))
                rcv["received"] += 1
                snd["sent"] += 1
                need -= 1
                transfers[(snd["ward_id"], rcv["ward_id"])] = transfers.get((snd["ward_id"], rcv["ward_id"]), 0) + 1
        demand = sum(s["bed_demand"] for s in pool)
        cap = sum(s["effective_capacity"] for s in pool)
        unresolved = sum(s["deficit"] - s["sent"] for s in pool)
        cities[city] = {"city": city, "wards": len(pool), "bed_demand": demand, "capacity": cap,
                        "utilisation_pct": round(100.0 * demand / cap, 1) if cap else None,
                        "headroom_after_routing": max(0, cap - demand),
                        "patients_routed": sum(s["sent"] for s in pool),
                        "unresolved_deficit": unresolved, "surge": unresolved > 0,
                        "wards_in_deficit": sum(s["deficit"] > 0 for s in pool)}
        if unresolved > 0:
            alerts.append({"city": city, "level": "CITY_SURGE", "unresolved": unresolved,
                           "message": f"CITY SURGE: {city} needs {unresolved} more beds than the whole city pool has. "
                                      f"Open surge beds or escalate to regional command (cross-city routing is not allowed)."})

    rows = []
    for s in state.values():
        s["net_deficit"] = s["deficit"] - s["sent"]
        s["remaining_headroom"] = s["headroom"] - s["received"]
        s["utilisation_pct"] = round(100.0 * s["bed_demand"] / s["effective_capacity"], 1) if s["effective_capacity"] else None
        s["utilisation_after_pct"] = (round(100.0 * (s["bed_demand"] - s["sent"] + s["received"]) / s["effective_capacity"], 1)
                                      if s["effective_capacity"] else None)
        s["status"] = ("SURGE" if s["net_deficit"] > 0 else "SENDING" if s["sent"] else
                       "RECEIVING" if s["received"] else "OK")
        rows.append(s)
    rows.sort(key=lambda s: (s["city"], -s["deficit"], s["ward_id"]))
    tlist = [{"from_ward": a, "to_ward": b, "city": state[a]["city"], "patients": n}
             for (a, b), n in sorted(transfers.items(), key=lambda kv: (state[kv[0][0]]["city"], -kv[1], kv[0]))]
    total_demand = sum(c["bed_demand"] for c in cities.values())
    total_cap = sum(c["capacity"] for c in cities.values())
    return {"wards": rows, "transfers": tlist, "cities": list(cities.values()), "alerts": alerts,
            "summary": {"bed_demand": total_demand, "capacity": total_cap,
                        "utilisation_pct": round(100.0 * total_demand / total_cap, 1) if total_cap else None,
                        "patients_routed": sum(t["patients"] for t in tlist),
                        "unresolved_deficit": sum(c["unresolved_deficit"] for c in cities.values()),
                        "capacity_note": CAPACITY_NOTE}}


CAPACITY_NOTE = ("Assumed baseline capacity, editable: the dataset has no bed-capacity column, so each city's bed pool = "
                 "P%d of the city's historical weekly total bed requirement, split across wards by population density. "
                 "Hospital users can overwrite it with real numbers. It is not real hospital data." % C.CAPACITY_PERCENTILE)
