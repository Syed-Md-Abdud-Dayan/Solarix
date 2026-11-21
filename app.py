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

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from dengue_watch.features import build_features

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
    metrics = scenario.get("metrics", {}).get(scenario.get("best", ""), {})
    return {
        "source": "trained_model", "model_connected": True, "city": city, "cities": CITIES,
        "horizon": horizon, "horizon_label": "Latest-week nowcast (weather only)" if horizon == 0 else f"{horizon}-week-ahead forecast",
        "latest_observation": LATEST_DATE.strftime("%Y-%m-%d"),
        "forecast_date": (LATEST_DATE + timedelta(weeks=horizon)).strftime("%Y-%m-%d"),
        "ward_count": len(ward_payload), "predicted_total_cases": round(float(city_rows.predicted_cases.sum()), 2),
        "actual_latest_week_cases": int(_df[(_df.city.eq(city)) & (_df.date.eq(LATEST_DATE))].dengue_cases.sum()),
        "priority_1_count": sum(w["priority"] == "Priority 1" for w in ward_payload),
        "priority_2_count": sum(w["priority"] == "Priority 2" for w in ward_payload),
        "best_model": scenario.get("best", "Saved horizon model"), "test_metrics": metrics,
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
        "model": RESULTS.get("scenarios", {}).get(f"h{h}", {}).get("best", "Gradient boosting"),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else str(body).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                return self._send(200, health_payload())
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
