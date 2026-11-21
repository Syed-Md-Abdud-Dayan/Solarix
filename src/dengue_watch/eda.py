"""Exploratory data analysis payload for the dashboard."""
import numpy as np
import pandas as pd

def add_eda_payload(df, CITIES, TEST_START, R):
    # ------------------------------------------------------------------ EDA payload
    d0 = df.copy()
    d0["season_year"] = d0.year
    eda = {}
    eda["meta"] = {"rows": len(d0), "wards": int(d0.ward_id.nunique()), "cities": CITIES,
                   "start": str(d0.date.min().date()), "end": str(d0.date.max().date()),
                   "total_cases": int(d0.dengue_cases.sum()), "weeks": int(d0.date.nunique()),
                   "zero_share": float((d0.dengue_cases == 0).mean()), "peak_week_max": int(d0.dengue_cases.max()),
                   "test_start": TEST_START}
    yc = d0.groupby(["year", "city"]).dengue_cases.sum().unstack().fillna(0)
    eda["yearly_city"] = {"year": yc.index.tolist(), **{c: yc[c].astype(int).tolist() for c in yc.columns}}
    mc = d0.groupby(["month", "city"]).dengue_cases.mean().unstack().round(3)
    eda["monthly_city"] = {"month": mc.index.tolist(), **{c: mc[c].tolist() for c in mc.columns}}
    wk = d0.groupby("date").dengue_cases.sum().reset_index()
    eda["weekly_total"] = {"date": wk.date.dt.strftime("%Y-%m-%d").tolist(), "cases": wk.dengue_cases.tolist()}
    wd = d0.groupby(["ward_id", "city"]).agg(total=("dengue_cases", "sum"), density=("population_density_sqkm", "first"),
                                              waterlog=("water_logging_risk_index", "first"), sanitation=("sanitation_score", "first"),
                                              peak=("dengue_cases", "max")).reset_index()
    eda["wards"] = wd.round(3).to_dict("records")
    cols = ["dengue_cases", "rainfall_mm", "avg_temp_c", "relative_humidity_pct", "water_logging_risk_index", "sanitation_score", "population_density_sqkm"]
    eda["corr"] = {"cols": ["Dengue cases", "Rainfall", "Avg temp", "Humidity", "Water-logging", "Sanitation", "Pop. density"],
                   "matrix": d0[cols].corr().round(3).values.tolist()}
    g = d0.groupby("ward_id")
    lc = {"lag": list(range(0, 13))}
    for nm, col in [("rain", "rainfall_mm"), ("temp", "avg_temp_c"), ("hum", "relative_humidity_pct")]:
        lc[nm] = [round(float(g[col].shift(L).corr(d0.dengue_cases)), 3) for L in lc["lag"]]
    lc["cases"] = [None] + [round(float(g.dengue_cases.shift(L).corr(d0.dengue_cases)), 3) for L in lc["lag"][1:]]
    eda["lag_corr"] = lc
    b = {}
    for nm, col, q in [("rain", "rainfall_mm", 8), ("temp", "avg_temp_c", 8), ("hum", "relative_humidity_pct", 8)]:
        bins = pd.qcut(d0[col], q, duplicates="drop")
        t = d0.groupby(bins).agg(x=(col, "mean"), y=("dengue_cases", "mean")).round(3)
        b[nm] = {"x": t.x.tolist(), "y": t.y.tolist()}
    for nm, col in [("sanitation", "sanitation_score"), ("waterlog", "water_logging_risk_index"), ("density", "population_density_sqkm")]:
        t = wd.groupby(pd.qcut(wd[{"sanitation": "sanitation", "waterlog": "waterlog", "density": "density"}[nm]], 5, duplicates="drop")).agg(x=(nm, "mean"), y=("total", "mean")).round(3)
        b[nm] = {"x": t.x.tolist(), "y": t.y.tolist()}
    eda["binned"] = b
    R["eda"] = eda


    return R
