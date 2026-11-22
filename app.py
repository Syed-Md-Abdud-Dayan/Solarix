"""Dengue Watch API: serves predictions from the saved, trained models."""
from __future__ import annotations
import json
import os
import warnings
from datetime import timedelta
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
import time
import threading
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from dengue_watch.features import build_features
from dengue_watch import future as FUT
from dengue_watch.chatbot import ChatEngine

ROOT = Path(__file__).resolve().parent
DATA_PATH = Path(os.getenv("DENGUE_DATA", ROOT / "data/bangladesh_dengue_large_dataset.csv"))
MODEL_DIR = Path(os.getenv("DENGUE_MODEL_DIR", ROOT / "artifacts/models"))
RESULTS_PATH = Path(os.getenv("DENGUE_RESULTS", ROOT / "artifacts/results.json"))
WEB_DIR = ROOT / "web"


# Model files were serialized with scikit-learn 1.9.1. Use that version from
# requirements.txt to avoid cross-version pickle incompatibilities.
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    MODELS = {h: joblib.load(MODEL_DIR / f"model_h{h}.joblib") for h in range(13)}

_df = pd.read_csv(DATA_PATH, parse_dates=["date"]).sort_values(["ward_id", "date"]).reset_index(drop=True)
_df["year"] = _df.date.dt.year
_df["month"] = _df.date.dt.month
_df["woy"] = _df.date.dt.isocalendar().week.astype(int).clip(upper=52)
_df["city_mean_cases"] = _df.groupby(["city", "date"]).dengue_cases.transform("mean")
CITIES = sorted(_df.city.unique().tolist())
LATEST_DATE = _df.date.max()
LATEST = _df[_df.date.eq(LATEST_DATE)].copy()
with open(RESULTS_PATH, encoding="utf-8") as f:
    RESULTS = json.load(f)
DEPLOYED_MODEL = "Gradient Boosting (tuned, Poisson)"


def _forecast_features(h: int) -> pd.DataFrame:
    """Build the exact horizon features using only information available at latest date.

    For h>0, append h future placeholder weeks. build_features shifts dynamic
    inputs by h weeks, so the forecast row uses observations available today.
    Future weather/case values are NaN and are never used as predictors.
    """
    model_bundle = MODELS[h]
    if h == 0:
        work = _df.copy()
        X = build_features(work, 0, False, CITIES)
        rows = X.loc[LATEST.index].copy()
        rows.index = LATEST["ward_id"].values
    else:
        future = []
        for ward_id, hist in _df.groupby("ward_id", sort=False):
            last = hist.iloc[-1]
            for step in range(1, h + 1):
                future.append({
                    "date": last.date + timedelta(weeks=step),
                    "city": last.city,
                    "ward_id": ward_id,
                    "population_density_sqkm": last.population_density_sqkm,
                    "water_logging_risk_index": last.water_logging_risk_index,
                    "sanitation_score": last.sanitation_score,
                    "avg_temp_c": np.nan, "max_temp_c": np.nan,
                    "min_temp_c": np.nan, "rainfall_mm": np.nan,
                    "relative_humidity_pct": np.nan, "dengue_cases": np.nan,
                })
        fut = pd.DataFrame(future)
        fut["year"] = fut.date.dt.year
        fut["month"] = fut.date.dt.month
        fut["woy"] = fut.date.dt.isocalendar().week.astype(int).clip(upper=52)
        fut["city_mean_cases"] = np.nan
        work = pd.concat([_df, fut], ignore_index=True).sort_values(["ward_id", "date"]).reset_index(drop=True)
        X = build_features(work, h, True, CITIES)
        target_date = LATEST_DATE + timedelta(weeks=h)
        rows = X.loc[work.date.eq(target_date)].copy()
        rows.index = work.loc[work.date.eq(target_date), "ward_id"].values
    # Match the persisted training schema exactly and fail loudly on mismatch.
    missing = set(model_bundle["features"]) - set(rows.columns)
    if missing:
        raise RuntimeError(f"Missing model features for h{h}: {sorted(missing)}")
    rows = rows[model_bundle["features"]].replace([np.inf, -np.inf], np.nan)
    if rows.isna().any().any():
        bad = rows.columns[rows.isna().any()].tolist()
        raise RuntimeError(f"Null forecast features for h{h}: {bad}")
    return rows


# Cache model outputs: they only change when the source dataset or model files change.
_FORECAST_CACHE: dict[int, pd.DataFrame] = {}

def get_predictions(h: int) -> pd.DataFrame:
    if h not in _FORECAST_CACHE:
        X = _forecast_features(h)
        yhat = np.maximum(0, MODELS[h]["model"].predict(X))
        out = pd.DataFrame({"ward_id": X.index.astype(str), "predicted_cases": yhat})
        meta = LATEST[["ward_id", "city", "dengue_cases", "rainfall_mm", "avg_temp_c",
                       "relative_humidity_pct", "population_density_sqkm",
                       "water_logging_risk_index", "sanitation_score"]]
        out = out.merge(meta, on="ward_id", how="left")
        out["forecast_date"] = (LATEST_DATE + timedelta(weeks=h)).strftime("%Y-%m-%d")
        _FORECAST_CACHE[h] = out
    return _FORECAST_CACHE[h].copy()


def _risk_label(rank: float) -> str:
    # Relative prioritisation within the selected city, not a clinical risk score.
    if rank >= 0.90: return "Priority 1"
    if rank >= 0.70: return "Priority 2"
    return "Monitor"


def health_payload():
    return {"status": "ok", "model_connected": True, "risk_api": True, "models_loaded": len(MODELS),
            "latest_observation": LATEST_DATE.strftime("%Y-%m-%d"),
            "cities": CITIES, "wards": int(_df.ward_id.nunique())}


def dashboard_payload(params):
    city = params.get("city", [CITIES[0]])[0]
    try:
        horizon = int(params.get("horizon", ["3"])[0])
    except ValueError:
        raise ValueError("horizon must be an integer from 0 to 12 weeks")
    if city not in CITIES:
        raise ValueError(f"Unknown city. Choose one of: {', '.join(CITIES)}")
    if not 0 <= horizon <= 12:
        raise ValueError("horizon must be between 0 and 12 weeks")

    selected = get_predictions(horizon)
    city_rows = selected[selected.city.eq(city)].copy().sort_values("predicted_cases", ascending=False)
    rank = city_rows.predicted_cases.rank(method="average", pct=True)
    city_rows["priority"] = rank.map(_risk_label)
    city_rows["percentile"] = (rank * 100).round(1)
    horizon_series = []
    for h in range(13):
        pred = get_predictions(h)
        total = float(pred.loc[pred.city.eq(city), "predicted_cases"].sum())
        horizon_series.append({"horizon": h, "date": (LATEST_DATE + timedelta(weeks=h)).strftime("%Y-%m-%d"),
                               "predicted_cases": round(total, 2)})
    hist = (_df[_df.city.eq(city)].groupby("date").agg(
        cases=("dengue_cases", "sum"), rainfall_mm=("rainfall_mm", "mean")
    ).tail(16).reset_index())
    hist_payload = [{"date": r.date.strftime("%Y-%m-%d"), "cases": int(r.cases),
                     "rainfall_mm": round(float(r.rainfall_mm), 2)} for r in hist.itertuples()]
    scenario = RESULTS.get("scenarios", {}).get(f"h{horizon}", {})
    importance = scenario.get("group_importance", {})
    factors = [{"name": k, "importance": round(float(v), 4)}
               for k, v in sorted(importance.items(), key=lambda kv: -kv[1])[:6]]
    ward_payload = []
    for r in city_rows.itertuples():
        ward_payload.append({
            "ward_id": r.ward_id, "predicted_cases": round(float(r.predicted_cases), 2),
            "last_reported_cases": int(r.dengue_cases), "priority": r.priority,
            "percentile": float(r.percentile), "rainfall_mm": round(float(r.rainfall_mm), 2),
            "temperature_c": round(float(r.avg_temp_c), 2), "humidity_pct": round(float(r.relative_humidity_pct), 2),
            "population_density_sqkm": int(r.population_density_sqkm),
            "water_logging_risk_index": round(float(r.water_logging_risk_index), 3),
            "sanitation_score": round(float(r.sanitation_score), 3),
        })
    # The saved models/model_hN.joblib files are ALWAYS the refit gradient-boosting model, so report
    # that model's held-out metrics (not whichever model happened to rank "best" during training).
    metrics = scenario.get("metrics", {}).get(DEPLOYED_MODEL, {})
    return {
        "source": "trained_model", "model_connected": True, "city": city, "cities": CITIES,
        "horizon": horizon, "horizon_label": "Latest-week nowcast (weather only)" if horizon == 0 else f"{horizon}-week-ahead forecast",
        "latest_observation": LATEST_DATE.strftime("%Y-%m-%d"),
        "forecast_date": (LATEST_DATE + timedelta(weeks=horizon)).strftime("%Y-%m-%d"),
        "ward_count": len(ward_payload), "predicted_total_cases": round(float(city_rows.predicted_cases.sum()), 2),
        "actual_latest_week_cases": int(_df[(_df.city.eq(city)) & (_df.date.eq(LATEST_DATE))].dengue_cases.sum()),
        "priority_1_count": sum(w["priority"] == "Priority 1" for w in ward_payload),
        "priority_2_count": sum(w["priority"] == "Priority 2" for w in ward_payload),
        "best_model": DEPLOYED_MODEL, "test_metrics": metrics,
        "historical": hist_payload, "forecast_by_horizon": horizon_series, "wards": ward_payload,
        "feature_importance": factors,
        "data_period": {"start": _df.date.min().strftime("%Y-%m-%d"), "end": LATEST_DATE.strftime("%Y-%m-%d")},
        "notice": "Forecasts are model estimates from the supplied dataset, not official live surveillance. Future weather is unknown; horizon models use only the historical inputs available at the forecast origin. Priority labels are relative ranks within the selected city."
    }


# ---------------------------------------------------------------------------
# Risk prediction engine: any origin date, any horizon, optional rainfall what-if
# ---------------------------------------------------------------------------
RISK_BANDS = [(9.0, "Critical"), (5.0, "High"), (2.0, "Medium"), (0.0, "Low")]  # expected cases / ward-week
RISK_NOTE = ("Bands use expected weekly cases per ward: Low <2, Medium 2-5, High 5-9, Critical >=9 "
             "(roughly the 70th / 85th / 90th percentiles of historical ward-weeks).")
DATES = sorted(_df.date.unique())
KEEP_WEEKS = 30  # enough history for 12-week rolling windows + 8-week lags + horizon shift


def risk_level(v: float) -> str:
    for cut, name in RISK_BANDS:
        if v >= cut:
            return name
    return "Low"


_PRED_CACHE: dict = {}


def predict_at(origin, h: int, rain_mult: float = 1.0) -> pd.DataFrame:
    """Predict week origin+h for every ward using only data up to `origin`.
    rain_mult scales rainfall of the last 4 observed weeks (what-if heavy/low rain)."""
    key = (pd.Timestamp(origin).strftime("%Y-%m-%d"), h, round(rain_mult, 2))
    if key in _PRED_CACHE:
        return _PRED_CACHE[key].copy()
    origin = pd.Timestamp(origin)
    hist = _df[(_df.date <= origin) & (_df.date > origin - timedelta(weeks=KEEP_WEEKS))].copy()
    if rain_mult != 1.0:
        last4 = hist.date > origin - timedelta(weeks=4)
        hist.loc[last4, "rainfall_mm"] = hist.loc[last4, "rainfall_mm"] * rain_mult
    parts = [hist]
    if h > 0:
        for ward_id, w in hist.groupby("ward_id", sort=False):
            last = w.iloc[-1]
            for step in range(1, h + 1):
                parts.append(pd.DataFrame([{
                    "date": origin + timedelta(weeks=step), "city": last.city, "ward_id": ward_id,
                    "population_density_sqkm": last.population_density_sqkm,
                    "water_logging_risk_index": last.water_logging_risk_index,
                    "sanitation_score": last.sanitation_score,
                    "avg_temp_c": np.nan, "max_temp_c": np.nan, "min_temp_c": np.nan,
                    "rainfall_mm": np.nan, "relative_humidity_pct": np.nan, "dengue_cases": np.nan}]))
    work = pd.concat(parts, ignore_index=True)
    work["year"] = work.date.dt.year
    work["month"] = work.date.dt.month
    work["woy"] = work.date.dt.isocalendar().week.astype(int).clip(upper=52)
    work["city_mean_cases"] = work.groupby(["city", "date"]).dengue_cases.transform("mean")
    work = work.sort_values(["ward_id", "date"]).reset_index(drop=True)
    X = build_features(work, h, h > 0, CITIES)
    target = origin + timedelta(weeks=h)
    mask = work.date.eq(target)
    rows = X.loc[mask, MODELS[h]["features"]].replace([np.inf, -np.inf], np.nan)
    ids = work.loc[mask, "ward_id"].values
    ok = ~rows.isna().any(axis=1).values
    out = pd.DataFrame({"ward_id": ids[ok], "predicted_cases": np.maximum(0, MODELS[h]["model"].predict(rows[ok]))})
    # ward context at the origin week (what the officer sees today)
    ctx = hist[hist.date.eq(origin)][["ward_id", "city", "dengue_cases", "rainfall_mm", "avg_temp_c",
                                      "relative_humidity_pct", "population_density_sqkm",
                                      "water_logging_risk_index", "sanitation_score"]]
    r4 = hist[hist.date > origin - timedelta(weeks=4)].groupby("ward_id").rainfall_mm.sum().rename("rain_4w")
    r48 = hist[(hist.date <= origin - timedelta(weeks=4)) & (hist.date > origin - timedelta(weeks=8))] \
        .groupby("ward_id").rainfall_mm.sum().rename("rain_prev4w")
    out = out.merge(ctx, on="ward_id", how="left").merge(r4, on="ward_id", how="left").merge(r48, on="ward_id", how="left")
    out["target_date"] = target.strftime("%Y-%m-%d")
    _PRED_CACHE[key] = out
    if len(_PRED_CACHE) > 200:
        _PRED_CACHE.pop(next(iter(_PRED_CACHE)))
    return out.copy()


def _ward_drivers(r) -> list:
    """Plain-language drivers for one ward (rainfall lag window, climate, ward vulnerability)."""
    d = []
    if r.rain_4w > r.rain_prev4w * 1.3 and r.rain_4w > 60:
        d.append({"label": "Rainfall surge", "detail": f"{r.rain_4w:.0f} mm in last 4 wks vs {r.rain_prev4w:.0f} mm before - breeding window opens in 1-3 wks", "level": "high"})
    elif r.rain_4w > 60:
        d.append({"label": "Sustained rainfall", "detail": f"{r.rain_4w:.0f} mm over last 4 wks keeps larval sites wet", "level": "med"})
    else:
        d.append({"label": "Low recent rainfall", "detail": f"Only {r.rain_4w:.0f} mm in last 4 wks", "level": "low"})
    if 26 <= r.avg_temp_c <= 32 and r.relative_humidity_pct >= 70:
        d.append({"label": "Mosquito-friendly climate", "detail": f"{r.avg_temp_c:.1f} C and {r.relative_humidity_pct:.0f}% humidity", "level": "high"})
    elif r.avg_temp_c < 22:
        d.append({"label": "Cool weather", "detail": f"{r.avg_temp_c:.1f} C slows mosquito development", "level": "low"})
    else:
        d.append({"label": "Moderate climate", "detail": f"{r.avg_temp_c:.1f} C, {r.relative_humidity_pct:.0f}% humidity", "level": "med"})
    if r.water_logging_risk_index >= 0.7:
        d.append({"label": "Drainage bottleneck", "detail": f"Water-logging index {r.water_logging_risk_index:.2f}", "level": "high"})
    if r.sanitation_score <= 0.4:
        d.append({"label": "Weak sanitation", "detail": f"Sanitation score {r.sanitation_score:.2f}", "level": "high"})
    if r.population_density_sqkm >= 60000:
        d.append({"label": "High crowding", "detail": f"{int(r.population_density_sqkm):,} people/sq km", "level": "med"})
    if r.dengue_cases >= 5:
        d.append({"label": "Active transmission", "detail": f"{int(r.dengue_cases)} cases reported at origin week", "level": "high"})
    return d


def risk_payload(params):
    city = params.get("city", [CITIES[0]])[0]
    if city not in CITIES:
        raise ValueError(f"Unknown city. Choose one of: {', '.join(CITIES)}")
    try:
        h = int(params.get("horizon", ["3"])[0])
        rain_mult = float(params.get("rain_mult", ["1"])[0])
    except ValueError:
        raise ValueError("horizon must be an integer 1-12 and rain_mult a number")
    if not 1 <= h <= 12:
        raise ValueError("horizon must be between 1 and 12 weeks")
    if not 0.2 <= rain_mult <= 3.0:
        raise ValueError("rain_mult must be between 0.2 and 3.0")
    try:
        origin = pd.Timestamp(params.get("as_of", [str(LATEST_DATE.date())])[0])
    except Exception:
        raise ValueError("as_of must be a date like 2025-08-04")
    pos = np.searchsorted(DATES, np.datetime64(origin), side="right") - 1
    if pos < 40:
        raise ValueError("as_of is too early - at least 40 weeks of history are needed")
    origin = pd.Timestamp(DATES[pos])  # snap to the weekly observation date
    pred = predict_at(origin, h, rain_mult)
    pred = pred[pred.city.eq(city)].sort_values("predicted_cases", ascending=False)
    pred["risk"] = pred.predicted_cases.map(risk_level)
    # truth for back-testing, only when that week exists in the data
    target = pd.Timestamp(pred.target_date.iloc[0])
    actual = _df[(_df.city.eq(city)) & (_df.date.eq(target))].set_index("ward_id").dengue_cases
    wards = []
    for r in pred.itertuples():
        wards.append({
            "ward_id": r.ward_id, "predicted_cases": round(float(r.predicted_cases), 2), "risk": r.risk,
            "actual_cases": (int(actual[r.ward_id]) if r.ward_id in actual.index else None),
            "cases_at_origin": int(r.dengue_cases), "rain_4w_mm": round(float(r.rain_4w), 1),
            "temperature_c": round(float(r.avg_temp_c), 1), "humidity_pct": round(float(r.relative_humidity_pct), 1),
            "water_logging_risk_index": round(float(r.water_logging_risk_index), 2),
            "sanitation_score": round(float(r.sanitation_score), 2),
            "population_density_sqkm": int(r.population_density_sqkm),
            "drivers": _ward_drivers(r)})
    counts = {k: sum(w["risk"] == k for w in wards) for k in ("Critical", "High", "Medium", "Low")}
    city_total = round(float(pred.predicted_cases.sum()), 1)
    overall = risk_level(float(pred.predicted_cases.mean()) * 1.0) if wards else "Low"
    # city risk is driven by the share of wards at High/Critical, not just the mean
    share = (counts["Critical"] + counts["High"]) / max(1, len(wards))
    city_level = "Critical" if counts["Critical"] / max(1, len(wards)) >= 0.3 else "High" if share >= 0.3 else "Medium" if (share > 0 or counts["Medium"] / max(1, len(wards)) >= 0.3) else "Low"
    # rainfall at origin for the lag explainer: last 8 weeks, city mean
    rain = (_df[(_df.city.eq(city)) & (_df.date <= origin) & (_df.date > origin - timedelta(weeks=8))]
            .groupby("date").rainfall_mm.mean())
    if rain_mult != 1.0:
        rain.iloc[-4:] = rain.iloc[-4:] * rain_mult
    return {
        "city": city, "origin_date": origin.strftime("%Y-%m-%d"), "target_date": target.strftime("%Y-%m-%d"),
        "horizon": h, "rain_mult": rain_mult, "city_risk": city_level, "city_expected_cases": city_total,
        "counts": counts, "wards": wards, "risk_note": RISK_NOTE,
        "rainfall_8w": [{"date": d.strftime("%Y-%m-%d"), "mm": round(float(v), 1)} for d, v in rain.items()],
        "backtest": any(w["actual_cases"] is not None for w in wards),
        "actual_total": (int(sum(w["actual_cases"] or 0 for w in wards)) if any(w["actual_cases"] is not None for w in wards) else None),
        "date_range": {"min": pd.Timestamp(DATES[40]).strftime("%Y-%m-%d"), "max": LATEST_DATE.strftime("%Y-%m-%d")},
        "model": DEPLOYED_MODEL,
        "backtest_in_sample": bool(any(w["actual_cases"] is not None for w in wards)),
        "backtest_warning": ("Deployed models were refit on ALL data (2016-2025), so back-tests on past dates are in-sample and look "
                             "better than real accuracy. Honest held-out accuracy (2023-2025) is in results.json / the Model & data page."),
    }


def map_payload(params):
    """All wards of every city in one response, for the district risk map."""
    wards, cities, meta = [], [], {}
    for c in CITIES:
        p = dict(params); p["city"] = [c]
        d = risk_payload(p)
        meta = d
        cities.append({"city": c, "risk": d["city_risk"], "counts": d["counts"], "expected_cases": d["city_expected_cases"], "wards": len(d["wards"])})
        for w in d["wards"]:
            w["city"] = c
            w["ward_no"] = int(w["ward_id"].rsplit("_", 1)[-1])
            wards.append(w)
    return {"origin_date": meta["origin_date"], "target_date": meta["target_date"], "horizon": meta["horizon"],
            "rain_mult": meta["rain_mult"], "date_range": meta["date_range"], "backtest": meta["backtest"],
            "risk_note": meta["risk_note"], "model": meta["model"], "cities": cities, "wards": wards}


# ---------------------------------------------------------------------------
# Long-range forecast: any date AFTER the data (2026, 2027, ... up to FUTURE_MAX)
# ---------------------------------------------------------------------------
FUTURE_MAX = pd.Timestamp("2030-12-31")
_FUT_SCEN = FUT.weather_scenarios(_df)
_FUT_CACHE: dict = {}
try:
    FUTURE_BACKTEST = json.loads((ROOT / "artifacts/future_backtest.json").read_text(encoding="utf-8"))
except Exception:
    FUTURE_BACKTEST = None


def _future_long(end, rain_mult, temp_shift):
    key = (pd.Timestamp(end).strftime("%Y-%m-%d"), round(rain_mult, 2), round(temp_shift, 2))
    if key not in _FUT_CACHE:
        dates = FUT.forecast_dates(_df, None, end)
        _FUT_CACHE[key] = FUT.forecast_weather_only(_df, MODELS[0], dates, _FUT_SCEN, rain_mult, temp_shift)
        if len(_FUT_CACHE) > 6:
            _FUT_CACHE.pop(next(iter(_FUT_CACHE)))
    return _FUT_CACHE[key]


def future_payload(params):
    city = params.get("city", ["Dhaka North"])[0]
    if city != "All" and city not in CITIES:
        raise ValueError(f"Unknown city. Choose 'All' or one of: {', '.join(CITIES)}")
    try:
        rain_mult = float(params.get("rain_mult", ["1"])[0]); temp_shift = float(params.get("temp_shift", ["0"])[0])
        start = pd.Timestamp(params.get("start", [str((LATEST_DATE + timedelta(weeks=1)).date())])[0])
        end = pd.Timestamp(params.get("end", ["2027-12-31"])[0])
    except Exception:
        raise ValueError("start/end must be dates like 2026-01-05 and rain_mult/temp_shift numbers")
    if not 0.3 <= rain_mult <= 2.5: raise ValueError("rain_mult must be between 0.3 and 2.5")
    if not -2 <= temp_shift <= 3: raise ValueError("temp_shift must be between -2 and +3 degrees C")
    if end <= LATEST_DATE: raise ValueError(f"end must be after the last data week ({LATEST_DATE.date()}); use /api/risk for dates inside the data")
    if end > FUTURE_MAX: raise ValueError(f"end must be on or before {FUTURE_MAX.date()}")
    if start > end: raise ValueError("start must be before end")
    cache_end = pd.Timestamp("2028-12-31") if end <= pd.Timestamp("2028-12-31") else FUTURE_MAX  # 2 buckets -> better cache reuse
    long = _future_long(cache_end, rain_mult, temp_shift)
    long = long[(long.date >= start) & (long.date <= end)].copy()
    if long.empty: raise ValueError("No forecast weeks fall inside that date range")
    if city != "All": long = long[long.city.eq(city)]
    long["year"] = long.date.dt.year; long["month"] = long.date.dt.to_period("M").astype(str)
    weekly = FUT.summarize(long, by=("date",))
    monthly = FUT.summarize(long, by=("month",))
    yearly = FUT.summarize(long, by=("year",))
    near = {}
    if start <= LATEST_DATE + timedelta(weeks=12):
        for h in range(1, 13):
            pr = get_predictions(h)
            if city != "All": pr = pr[pr.city.eq(city)]
            near[(LATEST_DATE + timedelta(weeks=h)).strftime("%Y-%m-%d")] = float(pr.predicted_cases.sum())
    wk = [{"date": r.date.strftime("%Y-%m-%d"), "expected": round(r.expected, 1), "p10": round(r.p10, 1), "p90": round(r.p90, 1),
           "near_term_model": (round(near[r.date.strftime("%Y-%m-%d")], 1) if r.date.strftime("%Y-%m-%d") in near else None)}
          for r in weekly.itertuples()]
    ward = long.groupby(["ward_id", "city", "date"]).predicted_cases.mean().reset_index()
    wsum = ward.groupby(["ward_id", "city"]).predicted_cases.agg(total="sum", peak="max").reset_index()
    pk = ward.loc[ward.groupby("ward_id").predicted_cases.idxmax()][["ward_id", "date"]].rename(columns={"date": "peak_date"})
    wsum = wsum.merge(pk, on="ward_id").sort_values("total", ascending=False)
    wards = [{"ward_id": r.ward_id, "city": r.city, "expected_total": round(r.total, 1), "peak_week": r.peak_date.strftime("%Y-%m-%d"),
              "peak_expected_per_week": round(r.peak, 2), "peak_risk": risk_level(float(r.peak))} for r in wsum.itertuples()]
    bt = FUTURE_BACKTEST["mean"] if FUTURE_BACKTEST else None
    return {
        "city": city, "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "last_data_week": LATEST_DATE.strftime("%Y-%m-%d"),
        "rain_mult": rain_mult, "temp_shift": temp_shift, "n_weather_scenarios": int(long.scenario.nunique()),
        "weeks": len(wk), "weekly": wk,
        "monthly": [{"month": r.month, "expected": round(r.expected), "p10": round(r.p10), "p90": round(r.p90)} for r in monthly.itertuples()],
        "yearly": [{"year": int(r.year), "expected": round(r.expected), "p10": round(r.p10), "p90": round(r.p90)} for r in yearly.itertuples()],
        "wards": wards, "backtest": FUTURE_BACKTEST,
        "accuracy_summary": ({"ward_week_R2": round(bt["R2"], 2), "city_week_R2": round(bt["R2_city_week"], 2),
                              "ward_week_R2_if_weather_known": round(bt["R2_if_real_weather_known"], 2),
                              "seasonal_average_baseline_R2": round(bt["R2_climatology_baseline"], 2)} if bt else None),
        "notice": ("Long-range forecast: future weather is unknown, so each of the past years' weather patterns is replayed as a scenario. "
                   "It shows a typical season and a plausible range, NOT a prediction of which specific week an outbreak will hit. "
                   "Held-out yearly totals were off by -16% to +26%. It cannot know about new outbreaks, control programmes, serotype shifts or climate trends."),
    }


# ---------------------------------------------------------------------------
# Chatbot: backend adapter (the engine in dengue_watch/chatbot.py only talks to this)
# ---------------------------------------------------------------------------
try:
    CLASSIFICATION = json.loads((ROOT / "artifacts/classification_metrics.json").read_text(encoding="utf-8"))
except Exception:
    CLASSIFICATION = None


class AppBackend:
    cities = CITIES
    latest = LATEST_DATE

    def today(self):
        return date.today()

    def risk(self, city, h, as_of, rain_mult):
        params = {"city": [city], "horizon": [str(h)], "rain_mult": [str(rain_mult)]}
        if as_of:
            params["as_of"] = [str(as_of)]
        return risk_payload(params)

    def future(self, city, start, end, rain_mult, temp_shift):
        return future_payload({"city": [city], "start": [str(start)], "end": [str(end)],
                               "rain_mult": [str(rain_mult)], "temp_shift": [str(temp_shift)]})

    def actuals(self, city, start, end):
        d = _df[(_df.date >= pd.Timestamp(start)) & (_df.date <= pd.Timestamp(end))]
        if city != "All":
            d = d[d.city.eq(city)]
        weekly = d.groupby("date").dengue_cases.sum()
        wards = d.groupby("ward_id").dengue_cases.sum().sort_values(ascending=False).head(5)
        return {"total": float(d.dengue_cases.sum()), "peak_week": weekly.idxmax().strftime("%Y-%m-%d") if len(weekly) else "-",
                "peak_cases": float(weekly.max()) if len(weekly) else 0.0, "top_wards": [(k, float(v)) for k, v in wards.items()]}

    def season(self, city):
        d = _df if city == "All" else _df[_df.city.eq(city)]
        monthly = d.groupby(d.date.dt.month).dengue_cases.sum()
        total = float(monthly.sum()) or 1.0
        share = {int(m): float(monthly.get(m, 0.0)) / total * 100 for m in range(1, 13)}
        yearly = d.groupby(d.date.dt.year).dengue_cases.sum()
        return {"monthly_share": share, "peak_month": max(share, key=share.get), "yearly": {int(y): float(v) for y, v in yearly.items()}}

    def accuracy(self, h):
        sc = RESULTS.get("scenarios", {}).get(f"h{h}", {})
        out = {"model": DEPLOYED_MODEL, "metrics": sc.get("metrics", {}).get(DEPLOYED_MODEL, {})}
        if CLASSIFICATION:
            t = CLASSIFICATION.get("default_threshold")
            rows = CLASSIFICATION.get("horizons", {}).get(str(h), [])
            out["classification"] = next((r for r in rows if r["t"] == t), None)
        return out

    def info(self):
        return {"wards": int(_df.ward_id.nunique()), "cities": CITIES,
                "start": _df.date.min().strftime("%Y-%m-%d"), "end": LATEST_DATE.strftime("%Y-%m-%d")}


CHAT = ChatEngine(AppBackend())
_RATE: dict = {}
_RATE_LOCK = threading.Lock()
RATE_LIMIT, RATE_WINDOW = 40, 60  # messages per IP per minute
MAX_BODY = 8 * 1024


def rate_ok(ip: str) -> bool:
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE.get(ip, []) if now - t < RATE_WINDOW]
        if len(hits) >= RATE_LIMIT:
            _RATE[ip] = hits
            return False
        hits.append(now)
        _RATE[ip] = hits
        if len(_RATE) > 2000:
            _RATE.clear()
    return True


def chat_payload(body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    msg = body.get("message", "")
    if not isinstance(msg, str):
        raise ValueError("message must be a string")
    lang = body.get("lang")
    return CHAT.reply(msg, body.get("context"), lang if lang in ("en", "bn") else None)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else str(body).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path != "/api/chat":
                return self._send(404, {"error": "Not found"})
            if not rate_ok(self.client_address[0]):
                return self._send(429, {"error": "Too many messages - please wait a moment."})
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._send(400, {"error": "Request body must be 1-8 KB of JSON"})
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"error": "Invalid JSON"})
            return self._send(200, chat_payload(body))
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            print(f"Chat failed: {exc}")
            return self._send(500, {"error": "Chat failed"})

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                return self._send(200, health_payload())
            if parsed.path == "/api/chat/suggestions":
                from dengue_watch import knowledge as _K
                return self._send(200, _K.SUGGESTIONS)
            if parsed.path == "/api/future":
                return self._send(200, future_payload(parse_qs(parsed.query)))
            if parsed.path == "/api/map":
                return self._send(200, map_payload(parse_qs(parsed.query)))
            if parsed.path == "/api/risk":
                return self._send(200, risk_payload(parse_qs(parsed.query)))
            if parsed.path == "/api/dashboard":
                return self._send(200, dashboard_payload(parse_qs(parsed.query)))
            if parsed.path.startswith("/api/ward/"):
                ward_id = unquote(parsed.path[len("/api/ward/"):])
                h = int(parse_qs(parsed.query).get("horizon", ["3"])[0])
                if h not in range(13): return self._send(400, {"error": "horizon must be 0–12"})
                rows = get_predictions(h)
                row = rows[rows.ward_id.eq(ward_id)]
                if row.empty: return self._send(404, {"error": "Ward not found"})
                return self._send(200, row.iloc[0].to_dict())
            relative = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
            target = (WEB_DIR / relative).resolve()
            if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
                return self._send(403, "Forbidden", "text/plain; charset=utf-8")
            if not target.is_file(): return self._send(404, "Not found", "text/plain; charset=utf-8")
            types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
            return self._send(200, target.read_bytes(), types.get(target.suffix, "application/octet-stream"))
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            print(f"Request failed: {exc}")
            return self._send(500, {"error": f"Model prediction failed: {exc}"})

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"Dengue Watch API ready at http://127.0.0.1:{port}")
    print(f"Loaded {len(MODELS)} trained horizon models for {len(CITIES)} cities / {_df.ward_id.nunique()} wards")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
