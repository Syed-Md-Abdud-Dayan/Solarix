"""Bridge between the Phase 1 forecasting code (app.py) and the Phase 2 engines.

`init(app_module)` is called once by app.py; the bridge then reuses the already
loaded data frame (`_df`), the 13 horizon models (`MODELS`), `CITIES`, `risk_level`
and the exact feature builder, so Phase 2 numbers are identical to Phase 1 numbers
(`tests/test_ops_engines.py` asserts equality with `app.predict_at`).

Two extras on top of `predict_at`:

* `predict_variants` - predicts many *copies* of wards in one model call, where each
  copy can have its recent rainfall / case history scaled. This is how the what-if
  simulator runs counterfactuals THROUGH the ML models (see simulator.py).
* a deterministic seasonal fallback forecast used if a model is missing/broken or
  if fallback is forced (env OPS_FORCE_FALLBACK=1 or the admin "model kill-switch").
  fallback = 0.6 * same-week-of-year mean of the ward (all prior years, +-1 week)
           + 0.4 * the ward's mean of the last 4 observed weeks
  It is fully local, needs no model file, and is flagged "source": "fallback".
"""
from __future__ import annotations

import json
import os
import threading
from datetime import timedelta

import numpy as np
import pandas as pd

from dengue_watch.features import build_features
from . import config as C

_APP = None
_LOCK = threading.Lock()
_CACHE: dict = {}
FORCE_FALLBACK = {"on": os.getenv("OPS_FORCE_FALLBACK", "0") == "1"}
SEASONAL_WEIGHT = 0.6
KEEP_WEEKS = 30
STATIC_COLS = ["city", "population_density_sqkm", "water_logging_risk_index", "sanitation_score"]


def init(app_module) -> None:
    """Attach the running app module (gives access to data, models, risk bands)."""
    global _APP
    _APP = app_module


def app():
    if _APP is None:
        raise RuntimeError("forecast_bridge.init(app) has not been called")
    return _APP


def data() -> pd.DataFrame:
    return app()._df


def cities() -> list[str]:
    return list(app().CITIES)


def risk_level(v: float) -> str:
    return app().risk_level(float(v))


def ward_static() -> pd.DataFrame:
    df = data()
    last = df[df.date.eq(df.date.max())]
    return last.set_index("ward_id")[STATIC_COLS].copy()


def snap_origin(origin=None) -> pd.Timestamp:
    """Snap any date to the latest weekly observation on/before it (>= 40 weeks of history)."""
    dates = app().DATES
    origin = pd.Timestamp(origin or C.DEFAULT_ORIGIN)
    pos = int(np.searchsorted(dates, np.datetime64(origin), side="right") - 1)
    pos = min(max(pos, 40), len(dates) - 1)
    return pd.Timestamp(dates[pos])


def horizon_mae(h: int) -> float:
    try:
        return float(app().RESULTS["scenarios"][f"h{h}"]["metrics"][app().DEPLOYED_MODEL]["MAE"])
    except Exception:
        return float(C.FALLBACK_MAE.get(h, 1.2))


def predict_variants(origin, h: int, variants: list[tuple]) -> pd.DataFrame:
    """Predict week origin+h for arbitrary ward *variants* in ONE model call.

    variants: list of (variant_id, ward_id, rain_mult, case_mult). The variant gets a copy
    of the ward's last KEEP_WEEKS weeks of history; rainfall and case counts of the last
    C.INTERVENTION_WEEKS observed weeks are multiplied by rain_mult / case_mult.
    city_mean_cases is taken from the unmodified history (a single-ward intervention
    barely moves the city mean; ignoring it is slightly conservative).
    Returns DataFrame[variant_id, ward_id, predicted_cases].
    """
    a = app()
    origin = pd.Timestamp(origin)
    df = a._df
    hist = df[(df.date <= origin) & (df.date > origin - timedelta(weeks=KEEP_WEEKS))].copy()
    hist["dengue_cases"] = hist["dengue_cases"].astype(float)
    hist["city_mean_cases"] = hist.groupby(["city", "date"]).dengue_cases.transform("mean")
    by_ward = {w: g for w, g in hist.groupby("ward_id", sort=False)}
    recent_cut = origin - timedelta(weeks=C.INTERVENTION_WEEKS)
    parts = []
    for vid, ward, rain_mult, case_mult in variants:
        g = by_ward[ward].copy()
        if rain_mult != 1.0 or case_mult != 1.0:
            recent = g.date > recent_cut
            g.loc[recent, "rainfall_mm"] = g.loc[recent, "rainfall_mm"] * rain_mult
            g.loc[recent, "dengue_cases"] = g.loc[recent, "dengue_cases"] * case_mult
        g["ward_id"] = vid
        g["_ward"] = ward
        parts.append(g)
        if h > 0:
            last = g.iloc[-1]
            fut = pd.DataFrame({"date": [origin + timedelta(weeks=s) for s in range(1, h + 1)]})
            for col in STATIC_COLS:
                fut[col] = last[col]
            fut["ward_id"] = vid
            fut["_ward"] = ward
            parts.append(fut)
    work = pd.concat(parts, ignore_index=True)
    work["year"] = work.date.dt.year
    work["month"] = work.date.dt.month
    work["woy"] = work.date.dt.isocalendar().week.astype(int).clip(upper=52)
    work = work.sort_values(["ward_id", "date"], kind="stable").reset_index(drop=True)
    X = build_features(work, h, h > 0, a.CITIES)
    mask = work.date.eq(origin + timedelta(weeks=h))
    rows = X.loc[mask, a.MODELS[h]["features"]].replace([np.inf, -np.inf], np.nan)
    if rows.isna().any().any():
        raise RuntimeError(f"null features for h{h}")
    yhat = np.maximum(0, a.MODELS[h]["model"].predict(rows))
    return pd.DataFrame({"variant_id": work.loc[mask, "ward_id"].values,
                         "ward_id": work.loc[mask, "_ward"].values, "predicted_cases": yhat})


def fallback_predict(origin, h: int) -> pd.DataFrame:
    """Deterministic seasonal-baseline forecast (no model file needed)."""
    df = data()
    origin = pd.Timestamp(origin)
    target = origin + timedelta(weeks=h)
    twoy = min(int(target.isocalendar().week), 52)
    past = df[df.date <= origin]
    near = past[(past.woy - twoy).abs().isin([0, 1, 51])]
    seasonal = near.groupby("ward_id").dengue_cases.mean()
    recent = past[past.date > origin - timedelta(weeks=4)].groupby("ward_id").dengue_cases.mean()
    pred = (SEASONAL_WEIGHT * seasonal + (1 - SEASONAL_WEIGHT) * recent.reindex(seasonal.index).fillna(0)).clip(lower=0)
    return pd.DataFrame({"ward_id": pred.index, "predicted_cases": pred.values})


def _predict_baseline(origin, h: int) -> tuple[pd.DataFrame, str]:
    if FORCE_FALLBACK["on"]:
        return fallback_predict(origin, h), "fallback"
    try:
        a = app()
        if h not in a.MODELS:
            raise RuntimeError(f"model h{h} not loaded")
        out = a.predict_at(origin, h)[["ward_id", "predicted_cases"]]
        if len(out) != data().ward_id.nunique():
            raise RuntimeError("incomplete model output")
        return out, "model"
    except Exception as exc:
        print(f"[ops] model h{h} failed ({exc}); using seasonal fallback")
        return fallback_predict(origin, h), "fallback"


def ward_forecast(origin=None, horizons=(1, 2, 3, 4)) -> pd.DataFrame:
    """Long table: one row per (ward, horizon) with cases, risk band and source."""
    origin = snap_origin(origin)
    key = (origin.strftime("%Y-%m-%d"), tuple(horizons), FORCE_FALLBACK["on"])
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key].copy()
    static = ward_static()
    frames = []
    for h in horizons:
        pred, source = _predict_baseline(origin, h)
        pred = pred.merge(static, left_on="ward_id", right_index=True, how="left")
        pred["horizon"] = h
        pred["target_date"] = (origin + timedelta(weeks=h)).strftime("%Y-%m-%d")
        pred["risk"] = pred.predicted_cases.map(risk_level)
        pred["source"] = source
        pred["mae"] = horizon_mae(h)
        frames.append(pred)
    out = pd.concat(frames, ignore_index=True)
    out["origin"] = origin.strftime("%Y-%m-%d")
    with _LOCK:
        _CACHE[key] = out
        if len(_CACHE) > 40:
            _CACHE.pop(next(iter(_CACHE)))
    return out.copy()


def forecast_payload(origin=None, horizons=(1, 2, 3, 4)) -> dict:
    """JSON-friendly forecast, plus the 'upcoming week' High/Medium/Low view."""
    fc = ward_forecast(origin, horizons)
    first = fc[fc.horizon.eq(min(horizons))]
    wards = []
    for ward_id, g in fc.groupby("ward_id", sort=True):
        g = g.sort_values("horizon")
        r0 = g.iloc[0]
        wards.append({
            "ward_id": ward_id, "city": r0.city, "population_density_sqkm": int(r0.population_density_sqkm),
            "upcoming_risk": r0.risk, "upcoming_notice_band": "High" if r0.risk in ("High", "Critical") else r0.risk,
            "weeks": [{"horizon": int(r.horizon), "target_date": r.target_date,
                       "predicted_cases": round(float(r.predicted_cases), 2), "risk": r.risk,
                       "low": round(max(0.0, float(r.predicted_cases - r.mae)), 2),
                       "high": round(float(r.predicted_cases + r.mae), 2)} for r in g.itertuples()],
        })
    return {"origin": fc.origin.iloc[0], "horizons": list(horizons),
            "source": "fallback" if (fc.source == "fallback").any() else "model",
            "counts": first.risk.value_counts().reindex(C.RISK_ORDER, fill_value=0).astype(int).to_dict(),
            "wards": wards}


def set_force_fallback(on: bool) -> None:
    FORCE_FALLBACK["on"] = bool(on)


def to_json(obj) -> str:
    return json.dumps(obj, default=str)
