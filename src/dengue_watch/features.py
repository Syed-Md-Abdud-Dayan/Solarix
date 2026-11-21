"""Leakage-aware feature engineering for each forecast horizon."""
import numpy as np
import pandas as pd

def build_features(d, h, use_cases, CITIES=None):
    CITIES = CITIES or sorted(d.city.unique())
    g = d.groupby("ward_id", sort=False)
    F = {}

    def lag(col, k):
        return g[col].shift(k)

    def roll(col, w, how):
        return g[col].transform(lambda s: getattr(s.shift(h).rolling(w, min_periods=w), how)())

    for k in (0, 1, 2, 3, 4, 6, 8):
        F[f"rain_lag{k}"] = lag("rainfall_mm", h + k)
    for w in (4, 8, 12):
        F[f"rain_sum{w}"] = roll("rainfall_mm", w, "sum")
    for k in (0, 2, 4, 6, 8):
        F[f"temp_avg_lag{k}"] = lag("avg_temp_c", h + k)
    for w in (4, 8, 12):
        F[f"temp_avg_mean{w}"] = roll("avg_temp_c", w, "mean")
    F["temp_max_lag0"] = lag("max_temp_c", h)
    F["temp_min_lag0"] = lag("min_temp_c", h)
    F["temp_min_mean4"] = roll("min_temp_c", 4, "mean")
    for k in (0, 2, 4):
        F[f"hum_lag{k}"] = lag("relative_humidity_pct", h + k)
    for w in (4, 8):
        F[f"hum_mean{w}"] = roll("relative_humidity_pct", w, "mean")
    F["rain_x_hum"] = F["rain_sum4"] * F["hum_mean4"] / 100.0

    if use_cases:
        for k in range(4):
            F[f"cases_lag{k}"] = lag("dengue_cases", h + k)
        F["cases_mean4"] = roll("dengue_cases", 4, "mean")
        F["cases_mean8"] = roll("dengue_cases", 8, "mean")
        F["city_cases_lag0"] = lag("city_mean_cases", h)
        F["city_cases_mean4"] = roll("city_mean_cases", 4, "mean")

    F["static_density"] = d.population_density_sqkm / 1000.0
    F["static_waterlog"] = d.water_logging_risk_index
    F["static_sanitation"] = d.sanitation_score
    for c in CITIES:
        F["static_city_" + c.replace(" ", "_")] = (d.city == c).astype(float)
    F["season_sin"] = np.sin(2 * np.pi * d.woy / 52)
    F["season_cos"] = np.cos(2 * np.pi * d.woy / 52)
    X = pd.DataFrame(F, index=d.index)
    return X


def group_of(name):
    if name.startswith("rain"): return "Rainfall"
    if name.startswith("temp"): return "Temperature"
    if name.startswith("hum"): return "Humidity"
    if name.startswith("city_cases"): return "City case history"
    if name.startswith("cases"): return "Ward case history"
    if name.startswith("static"): return "Ward profile (density, sanitation, water-logging, city)"
    return "Seasonality"


