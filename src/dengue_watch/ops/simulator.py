"""What-if vector control simulator (Requirement 3), model-driven.

How a crew deployment becomes a counterfactual ML forecast
-----------------------------------------------------------
The horizon models (Gradient Boosting, Poisson) predict cases at t+h from the ward's
recent rainfall (breeding habitat), weather, case history (transmission pressure),
ward profile and season. Vector control acts on exactly two of those drivers:

  * larviciding / source reduction removes water-filled breeding sites, so the ward's
    *effective* breeding rainfall of the last INTERVENTION_WEEKS weeks is scaled by
        rain_mult = 1 - LARVICIDE_EFFICACY * coverage
  * fogging kills infective adult mosquitoes, lowering transmission pressure, so the
    ward's recent case history that the model reads is scaled by
        case_mult = 1 - FOGGING_EFFICACY * coverage

  coverage(crews, ward) = 1 - exp(-COVERAGE_K * crews / density_factor(ward))
  -> saturating (diminishing returns per extra crew); denser wards need more crews
     for the same coverage.

The perturbed history is pushed through the SAME h=2,3,4 horizon models (one batched
call per horizon via forecast_bridge.predict_variants) and compared with the baseline.
The effect therefore depends on the ward's own features, the horizon and the number
of crews (e.g. a dry ward gains little from larviciding; the 4-week model reacts
differently from the 2-week model) - it is not a flat percentage.

Guard: tree ensembles are piece-wise constant, so a tiny perturbation can move a
prediction by a small amount in either direction. We report
    prevented(k) = max(0, max_{j<=k} raw_prevented(j))
i.e. more crews can never look worse than fewer (isotonic guard). Values are
rounded to 0.1 case.

Recommendation: greedy by marginal ROI. Each step gives one more crew to the ward
whose next crew prevents the most extra cases (ties by ward_id), until the crew cap.
ROI = cases prevented over weeks 2-4 / crews deployed.
"""
from __future__ import annotations

import math

import pandas as pd

from . import config as C
from . import forecast_bridge as FB
from .allocation import density_factor

RATE_BEDS = C.SUPPLY_RATES["hospital_beds"]
RATE_SALINE = C.SUPPLY_RATES["saline_bags"]


def coverage(crews: int, dfac: float) -> float:
    if crews <= 0:
        return 0.0
    return 1.0 - math.exp(-C.COVERAGE_K * crews / max(dfac, 0.1))


def multipliers(crews: int, dfac: float) -> tuple[float, float]:
    cov = coverage(crews, dfac)
    return 1.0 - C.LARVICIDE_EFFICACY * cov, 1.0 - C.FOGGING_EFFICACY * cov


_CURVE_CACHE: dict = {}


def response_curves(origin=None, horizons=C.SIM_HORIZONS, max_crews: int = C.SIM_MAX_CREWS_PER_WARD,
                    wards: list[str] | None = None) -> pd.DataFrame:
    """Model-predicted cases for every ward at 0..max_crews crews, per horizon.

    Returns long DataFrame[ward_id, crews, horizon, predicted_cases, prevented].
    """
    origin = FB.snap_origin(origin)
    key = (origin.strftime("%Y-%m-%d"), tuple(horizons), max_crews, tuple(wards or []), FB.FORCE_FALLBACK["on"])
    if key in _CURVE_CACHE:
        return _CURVE_CACHE[key].copy()
    static = FB.ward_static()
    med = float(static.population_density_sqkm.median())
    ids = sorted(wards or static.index.tolist())
    variants = []
    for w in ids:
        dfac = density_factor(float(static.loc[w, "population_density_sqkm"]), med)
        for k in range(max_crews + 1):
            rm, cm = multipliers(k, dfac)
            variants.append((f"{w}#{k}", w, rm, cm))
    frames = []
    for h in horizons:
        if FB.FORCE_FALLBACK["on"]:
            pred = _fallback_curves(origin, h, ids, max_crews, static, med)
        else:
            try:
                pred = FB.predict_variants(origin, h, variants)
            except Exception as exc:  # deterministic fallback, never crash
                print(f"[ops] simulator model h{h} failed ({exc}); using fallback efficacy curve")
                pred = _fallback_curves(origin, h, ids, max_crews, static, med)
        pred["crews"] = pred.variant_id.str.rsplit("#", n=1).str[-1].astype(int)
        pred["horizon"] = h
        frames.append(pred[["ward_id", "crews", "horizon", "predicted_cases"]])
    out = pd.concat(frames, ignore_index=True).sort_values(["ward_id", "horizon", "crews"]).reset_index(drop=True)
    base = out[out.crews.eq(0)].set_index(["ward_id", "horizon"]).predicted_cases
    out["baseline"] = [base[(w, h)] for w, h in zip(out.ward_id, out.horizon)]
    out["raw_prevented"] = out.baseline - out.predicted_cases
    # isotonic guard: non-negative and non-decreasing in crews
    out["prevented"] = out.groupby(["ward_id", "horizon"]).raw_prevented.cummax().clip(lower=0)
    out["intervened"] = (out.baseline - out.prevented).clip(lower=0)
    _CURVE_CACHE[key] = out
    if len(_CURVE_CACHE) > 12:
        _CURVE_CACHE.pop(next(iter(_CURVE_CACHE)))
    return out.copy()


def _fallback_curves(origin, h, ids, max_crews, static, med):
    """No-model path: seasonal baseline x the same coverage/efficacy curve (ramped by horizon)."""
    base = FB.fallback_predict(origin, h).set_index("ward_id").predicted_cases
    ramp = min(1.0, h / max(C.SIM_HORIZONS))   # effect builds up over the weeks
    rows = []
    for w in ids:
        dfac = density_factor(float(static.loc[w, "population_density_sqkm"]), med)
        for k in range(max_crews + 1):
            cov = coverage(k, dfac)
            eff = 1 - (1 - C.LARVICIDE_EFFICACY * cov * ramp) * (1 - C.FOGGING_EFFICACY * cov * (1 - ramp))
            rows.append({"variant_id": f"{w}#{k}", "ward_id": w, "predicted_cases": float(base.get(w, 0.0)) * (1 - eff)})
    return pd.DataFrame(rows)


def _ward_result(curves: pd.DataFrame, ward: str, crews: int) -> dict:
    g = curves[(curves.ward_id == ward) & (curves.crews == min(crews, curves.crews.max()))].sort_values("horizon")
    weeks = [{"horizon": int(r.horizon), "baseline_cases": round(float(r.baseline), 2),
              "intervened_cases": round(float(r.intervened), 2), "cases_prevented": round(float(r.prevented), 2),
              "beds_saved": round(float(r.prevented) * RATE_BEDS, 2),
              "saline_saved": round(float(r.prevented) * RATE_SALINE, 1)} for r in g.itertuples()]
    prevented = sum(w["cases_prevented"] for w in weeks)
    return {"ward_id": ward, "crews": int(crews), "weeks": weeks,
            "baseline_cases": round(sum(w["baseline_cases"] for w in weeks), 2),
            "intervened_cases": round(sum(w["intervened_cases"] for w in weeks), 2),
            "cases_prevented": round(prevented, 2),
            "beds_saved": round(prevented * RATE_BEDS, 2), "saline_saved": round(prevented * RATE_SALINE, 1),
            "roi": round(prevented / crews, 3) if crews else 0.0}


def simulate(deployment: dict, origin=None, horizons=C.SIM_HORIZONS, crew_cap: int | None = None) -> dict:
    """Simulate a user-chosen deployment {ward_id: crews}."""
    deployment = {w: max(0, min(C.SIM_MAX_CREWS_PER_WARD, int(k))) for w, k in deployment.items() if int(k) > 0}
    if crew_cap is not None and sum(deployment.values()) > crew_cap:
        raise ValueError(f"deployment uses {sum(deployment.values())} crews but only {crew_cap} are available")
    curves = response_curves(origin, horizons)
    known = set(curves.ward_id)
    bad = [w for w in deployment if w not in known]
    if bad:
        raise ValueError(f"unknown ward(s): {', '.join(bad)}")
    wards = [_ward_result(curves, w, k) for w, k in sorted(deployment.items())]
    wards.sort(key=lambda r: (-r["roi"], r["ward_id"]))
    for i, r in enumerate(wards, 1):
        r["roi_rank"] = i
    by_week = []
    for h in horizons:
        hb = curves[(curves.horizon == h) & (curves.crews == 0)]
        base = float(hb.baseline.sum())
        prev = sum(next(x["cases_prevented"] for x in w["weeks"] if x["horizon"] == h) for w in wards)
        by_week.append({"horizon": h, "baseline_cases": round(base, 1), "intervened_cases": round(base - prev, 1),
                        "cases_prevented": round(prev, 2), "beds_baseline": round(base * RATE_BEDS, 1),
                        "beds_intervened": round((base - prev) * RATE_BEDS, 1),
                        "saline_baseline": round(base * RATE_SALINE), "saline_intervened": round((base - prev) * RATE_SALINE)})
    total_prev = sum(w["cases_prevented"] for w in wards)
    used = sum(deployment.values())
    return {"origin": FB.snap_origin(origin).strftime("%Y-%m-%d"), "horizons": list(horizons),
            "method": "model-driven counterfactual (features perturbed, horizon models re-run)",
            "source": "fallback" if FB.FORCE_FALLBACK["on"] else "model",
            "crews_used": used, "wards": wards, "by_week": by_week,
            "compare": {"no_intervention": {"cases": round(sum(b["baseline_cases"] for b in by_week), 1),
                                            "beds": round(sum(b["beds_baseline"] for b in by_week), 1),
                                            "saline": sum(b["saline_baseline"] for b in by_week)},
                        "intervention": {"cases": round(sum(b["intervened_cases"] for b in by_week), 1),
                                         "beds": round(sum(b["beds_intervened"] for b in by_week), 1),
                                         "saline": sum(b["saline_intervened"] for b in by_week)}},
            "total": {"cases_prevented": round(total_prev, 2), "beds_saved": round(total_prev * RATE_BEDS, 2),
                      "saline_saved": round(total_prev * RATE_SALINE, 1),
                      "roi": round(total_prev / used, 3) if used else 0.0}}


def recommend(total_crews: int, origin=None, horizons=C.SIM_HORIZONS, wards: list[str] | None = None) -> dict:
    """Greedy-by-marginal-ROI deployment of a limited crew budget, plus the full ROI ranking."""
    curves = response_curves(origin, horizons)
    if wards:
        curves = curves[curves.ward_id.isin(wards)]
    tot = curves.groupby(["ward_id", "crews"]).prevented.sum()
    ids = sorted(curves.ward_id.unique())
    maxk = int(curves.crews.max())
    alloc = {w: 0 for w in ids}
    steps = []
    for _ in range(max(0, int(total_crews))):
        best, gain = None, 0.0
        for w in ids:
            k = alloc[w]
            if k >= maxk:
                continue
            g = float(tot[(w, k + 1)] - tot[(w, k)])
            if g > gain + 1e-9 or (abs(g - gain) <= 1e-9 and best is not None and g > 0 and w < best):
                best, gain = w, g
        if best is None or gain <= 1e-6:
            break
        alloc[best] += 1
        steps.append({"step": len(steps) + 1, "ward_id": best, "crew_no": alloc[best], "marginal_cases_prevented": round(gain, 3)})
    deployment = {w: k for w, k in alloc.items() if k > 0}
    # ROI ranking for a single crew per ward (comparable across wards)
    ranking = [{"ward_id": w, "cases_prevented_1_crew": round(float(tot[(w, 1)]), 3),
                "cases_prevented_max": round(float(tot[(w, maxk)]), 3),
                "roi_1_crew": round(float(tot[(w, 1)]), 3)} for w in ids]
    ranking.sort(key=lambda r: (-r["roi_1_crew"], r["ward_id"]))
    for i, r in enumerate(ranking, 1):
        r["rank"] = i
    result = simulate(deployment, origin, horizons) if deployment else simulate({}, origin, horizons)
    result.update({"recommended_deployment": deployment, "greedy_steps": steps, "roi_ranking": ranking,
                   "crews_available": int(total_crews)})
    return result
