"""Long-range forecasts for dates AFTER the end of the data (2026, 2027, ...).

Why this exists
---------------
The horizon models h1..h12 need the most recent observed weather/cases, so they
can only look 12 weeks past the last observation. For anything further out the
future weather is unknown, so we use the weather-only model (h0) and feed it
*weather scenarios*: each past year (2016..2025) is replayed as a possible
weather pattern for the future. The model is run once per scenario, giving

    expected  = mean over scenarios   (the point forecast)
    p10 / p90 = spread caused by weather uncertainty

Limits (be honest about them): it cannot know about a specific future outbreak,
new control programmes, serotype shifts or climate trends. Beyond ~12 weeks it
is a "typical season given possible weather" forecast, not a prediction of a
particular week.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import build_features

WEATHER = ["avg_temp_c", "max_temp_c", "min_temp_c", "rainfall_mm", "relative_humidity_pct"]
STATIC = ["city", "population_density_sqkm", "water_logging_risk_index", "sanitation_score"]
LOOKBACK_WEEKS = 30  # >= 12-week windows + 8-week lags


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    d = df.sort_values(["ward_id", "date"]).reset_index(drop=True).copy()
    d["year"] = d.date.dt.year
    d["month"] = d.date.dt.month
    d["woy"] = d.date.dt.isocalendar().week.astype(int).clip(upper=52)
    d["city_mean_cases"] = d.groupby(["city", "date"]).dengue_cases.transform("mean")
    return d


def weather_scenarios(df: pd.DataFrame, before: str | pd.Timestamp | None = None) -> dict[int, pd.DataFrame]:
    """One weather 'year' per complete ISO year in the data: {iso_year: (ward_id, woy) -> weather}."""
    d = df if before is None else df[df.date < pd.Timestamp(before)]
    iso = d.date.dt.isocalendar()
    d = d.assign(iso_year=iso.year.astype(int).values,
                 woy=iso.week.astype(int).clip(upper=52).values)
    scen = {}
    for y, g in d.groupby("iso_year"):
        if g.date.nunique() < 52:  # skip partial years (e.g. a stray ISO week 1 of the next year)
            continue
        scen[int(y)] = g.groupby(["ward_id", "woy"])[WEATHER].mean().reset_index()
    return scen


def _future_frame(hist, dates, wx, rain_mult, temp_shift):
    last = hist.groupby("ward_id", sort=False).tail(1).set_index("ward_id")[STATIC].reset_index()
    fut = pd.MultiIndex.from_product([last.ward_id, dates], names=["ward_id", "date"]).to_frame(index=False)
    fut = fut.merge(last, on="ward_id")
    fut["woy"] = fut.date.dt.isocalendar().week.astype(int).clip(upper=52).values
    fut = fut.merge(wx, on=["ward_id", "woy"], how="left")
    if fut[WEATHER].isna().any().any():
        raise RuntimeError("Weather scenario has gaps for some ward/week")
    fut["rainfall_mm"] = fut.rainfall_mm * rain_mult
    for c in ("avg_temp_c", "max_temp_c", "min_temp_c"):
        fut[c] = fut[c] + temp_shift
    fut["relative_humidity_pct"] = fut.relative_humidity_pct.clip(upper=100)
    fut["dengue_cases"] = np.nan
    fut["year"], fut["month"] = fut.date.dt.year, fut.date.dt.month
    fut["city_mean_cases"] = np.nan
    return fut


def forecast_dates(df: pd.DataFrame, start=None, end=None) -> pd.DatetimeIndex:
    """Weekly (Monday) dates after the last observation, up to `end`."""
    last = df.date.max()
    first = last + pd.Timedelta(weeks=1)
    dates = pd.date_range(first, pd.Timestamp(end), freq="7D")
    if start is not None:
        dates = dates[dates >= pd.Timestamp(start)]
    return dates


def forecast_weather_only(hist: pd.DataFrame, bundle: dict, dates, scenarios: dict,
                          rain_mult: float = 1.0, temp_shift: float = 0.0) -> pd.DataFrame:
    """Run the weather-only (h0) model for every scenario. Returns long frame:
    ward_id, city, date, scenario, predicted_cases."""
    cities = sorted(hist.city.unique())
    base = hist.sort_values(["ward_id", "date"]).groupby("ward_id", sort=False).tail(LOOKBACK_WEEKS)
    out = []
    for sy, wx in scenarios.items():
        fut = _future_frame(base, dates, wx, rain_mult, temp_shift)
        work = pd.concat([base, fut], ignore_index=True).sort_values(["ward_id", "date"]).reset_index(drop=True)
        X = build_features(work, 0, False, cities)
        m = work.date.isin(dates).values
        rows = X.loc[m, bundle["features"]]
        if rows.isna().any().any():
            raise RuntimeError("NaN features in long-range forecast (not enough lookback history)")
        out.append(pd.DataFrame({"ward_id": work.loc[m, "ward_id"].values, "city": work.loc[m, "city"].values,
                                 "date": work.loc[m, "date"].values, "scenario": sy,
                                 "predicted_cases": np.maximum(0, bundle["model"].predict(rows))}))
    return pd.concat(out, ignore_index=True)


DISPERSION = 1.4  # measured variance/mean of weekly ward cases (real weather known) = 1.36 -> negative binomial


def _nb_draws(mu: np.ndarray, phi: float, n: int, rng) -> np.ndarray:
    """Draw case counts with mean mu and variance phi*mu (Poisson if phi<=1)."""
    mu = np.asarray(mu, float)
    if phi <= 1.0:
        return rng.poisson(mu[:, None], (len(mu), n))
    r = np.maximum(mu / (phi - 1.0), 1e-9)
    return rng.negative_binomial(r[:, None], 1.0 / phi, (len(mu), n))


def summarize(long: pd.DataFrame, by=("ward_id", "city", "date"), n_draws: int = 40,
              phi: float = DISPERSION, seed: int = 0) -> pd.DataFrame:
    """Collapse weather scenarios into expected cases + a p10-p90 band.

    The band combines (1) weather uncertainty (one run per scenario) and (2) random
    case-count noise (negative-binomial draws). Without (2) the band was far too
    narrow (it covered ~31% of real outcomes instead of 80%). Group sums (e.g. a
    city) add the noise per ward first, so they stay correct.
    """
    by = list(by)
    keys = by + ["scenario"]
    rng = np.random.RandomState(seed)
    D = _nb_draws(long.predicted_cases.values, phi, n_draws, rng)
    gid = long.groupby(keys, sort=True).ngroup().values
    S = pd.DataFrame(D).groupby(gid).sum().values                      # unit x draws
    units = long.groupby(keys, sort=True).predicted_cases.sum().reset_index()
    n_scen = long.scenario.nunique()
    n_by = len(units) // n_scen
    pooled = S.reshape(n_by, n_scen * n_draws)
    mu = units.predicted_cases.values.reshape(n_by, n_scen)
    out = units[by].iloc[::n_scen].reset_index(drop=True)
    out["expected"] = mu.mean(1)
    out["p10"], out["p50"], out["p90"] = np.percentile(pooled, [10, 50, 90], axis=1)
    out["n_scenarios"] = n_scen
    return out


def city_summary(long: pd.DataFrame, **kw) -> pd.DataFrame:
    """City-week totals with a correctly aggregated band."""
    return summarize(long, by=("city", "date"), **kw)


def forecast(df: pd.DataFrame, bundle: dict, end, start=None, rain_mult: float = 1.0,
             temp_shift: float = 0.0, scenarios: dict | None = None) -> pd.DataFrame:
    """High-level helper: ward-level expected cases + band for every week up to `end`."""
    d = prepare(df)
    dates = forecast_dates(d, None, end)
    scen = scenarios or weather_scenarios(d)
    long = forecast_weather_only(d, bundle, dates, scen, rain_mult, temp_shift)
    res = summarize(long)
    if start is not None:
        res = res[res.date >= pd.Timestamp(start)]
    return res.sort_values(["date", "city", "ward_id"]).reset_index(drop=True)
