"""Honest test of the long-range forecaster.

For each test year Y: train ONLY on data before Y-01-01, then forecast every week
of Y with no knowledge of Y's weather or cases (weather scenarios come from the
earlier years only). This mimics "it is 31 Dec, forecast next year".

    python scripts/backtest_future.py
"""
import json, sys, warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance, r2_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dengue_watch import future as F
from dengue_watch.features import build_features

warnings.filterwarnings("ignore")
TEST_YEARS = (2023, 2024, 2025)

df = F.prepare(pd.read_csv(ROOT / "data/bangladesh_dengue_large_dataset.csv", parse_dates=["date"]))
cities = sorted(df.city.unique())
cfg = joblib.load(ROOT / "artifacts/models/model_h0.joblib")["params"]
X0 = build_features(df, 0, False, cities)
ok = X0.notna().all(axis=1)

rows, city_rows = [], []
for Y in TEST_YEARS:
    cut = pd.Timestamp(f"{Y}-01-01")
    tr = (ok & (df.date < cut)).values
    model = HistGradientBoostingRegressor(loss="poisson", early_stopping=False, random_state=0, **cfg).fit(X0[tr], df.dengue_cases[tr])
    bundle = {"model": model, "features": list(X0.columns)}
    hist = df[df.date < cut]
    test = df[(df.date >= cut) & (df.date < pd.Timestamp(f"{Y+1}-01-01"))]
    dates = pd.DatetimeIndex(sorted(test.date.unique()))
    scen = F.weather_scenarios(hist)  # earlier years only
    long = F.forecast_weather_only(hist, bundle, dates, scen)
    s = F.summarize(long).merge(test[["ward_id", "date", "dengue_cases"]], on=["ward_id", "date"])
    cs = F.city_summary(long).merge(test.groupby(["city", "date"]).dengue_cases.sum().reset_index(), on=["city", "date"])

    # baseline: seasonal average of past cases per ward x week-of-year
    clim = hist.groupby(["ward_id", "woy"]).dengue_cases.mean().rename("clim").reset_index()
    s = s.merge(test[["ward_id", "date", "woy"]], on=["ward_id", "date"]).merge(clim, on=["ward_id", "woy"], how="left")
    # upper bound: same model but told the real weather (what the old h0 'nowcast' measures)
    Xt = X0[(df.date >= cut) & (df.date < pd.Timestamp(f"{Y+1}-01-01"))]
    oracle = np.maximum(0, model.predict(Xt))

    y, p = s.dengue_cases.values, s.expected.values
    row = dict(year=Y, n_scenarios=len(scen),
               R2=r2_score(y, p), MAE=mean_absolute_error(y, p),
               PoissonDeviance=mean_poisson_deviance(y, np.clip(p, 1e-6, None)),
               R2_climatology_baseline=r2_score(y, s.clim), MAE_climatology_baseline=mean_absolute_error(y, s.clim),
               R2_if_real_weather_known=r2_score(df.loc[Xt.index, "dengue_cases"], oracle),
               R2_city_week=r2_score(cs.dengue_cases, cs.expected),
               MAE_city_week=mean_absolute_error(cs.dengue_cases, cs.expected),
               actual_total=int(y.sum()), predicted_total=float(p.sum()),
               band_coverage_ward_week_p10_p90=float(((s.dengue_cases >= s.p10) & (s.dengue_cases <= s.p90)).mean()),
               total_error_pct=100 * (p.sum() - y.sum()) / y.sum(),
               band_coverage_city_week_p10_p90=float(((cs.dengue_cases >= cs.p10) & (cs.dengue_cases <= cs.p90)).mean()),
               peak_week_actual=str(cs.groupby("date").dengue_cases.sum().idxmax().date()),
               peak_week_predicted=str(cs.groupby("date").expected.sum().idxmax().date()))
    rows.append(row)
    for c, g in cs.groupby("city"):
        city_rows.append(dict(year=Y, city=c, actual=int(g.dengue_cases.sum()), predicted=round(float(g.expected.sum()), 1),
                              error_pct=round(100 * (g.expected.sum() - g.dengue_cases.sum()) / g.dengue_cases.sum(), 1),
                              R2_week=round(r2_score(g.dengue_cases, g.expected), 3)))
    print(Y, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()})

summary = pd.DataFrame(rows)
out = {"method": "train on data before the test year; forecast the whole year using weather scenarios from earlier years only",
       "per_year": json.loads(summary.round(4).to_json(orient="records")),
       "mean": json.loads(summary.drop(columns=["year", "peak_week_actual", "peak_week_predicted"]).mean().round(4).to_json()),
       "per_city": city_rows}
(ROOT / "artifacts/future_backtest.json").write_text(json.dumps(out, indent=1))
print("\nMEAN", out["mean"])
print(pd.DataFrame(city_rows).to_string(index=False))
