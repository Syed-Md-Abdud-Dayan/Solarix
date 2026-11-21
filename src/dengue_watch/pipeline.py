"""End-to-end Bangladesh ward-level dengue forecasting pipeline."""
from __future__ import annotations
import json, os, sys, warnings
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.inspection import partial_dependence
from .features import build_features, group_of
from .evaluation import metrics, cv_hgb, group_importance, SEED
from .eda import add_eda_payload

warnings.filterwarnings("ignore")
TEST_START = 2023

def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if (o != o) else round(float(o), 4)
    if isinstance(o, (np.integer,)): return int(o)
    return o

def run_pipeline(csv_path: str, output_dir: str = "artifacts"):
    os.makedirs(os.path.join(output_dir, "models"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "predictions"), exist_ok=True)
    df = pd.read_csv(csv_path, parse_dates=["date"]).sort_values(["ward_id", "date"]).reset_index(drop=True)
    df["year"] = df.date.dt.year
    df["month"] = df.date.dt.month
    df["woy"] = df.date.dt.isocalendar().week.astype(int).clip(upper=52)
    df["city_mean_cases"] = df.groupby(["city", "date"]).dengue_cases.transform("mean")
    CITIES = sorted(df.city.unique())
    SCEN = {f"h{h}": dict(h=h, use_cases=h > 0,
                          label="Nowcast (weather only, no case reports)" if h == 0 else f"{h}-week-ahead forecast")
            for h in range(0, 13)}

    R = {"scenarios": {}}
    test_preds = {}
    for sk, sc in SCEN.items():
        print(f"\n=== {sk}: {sc['label']}")
        X = build_features(df, sc["h"], sc["use_cases"], CITIES)
        ok = X.notna().all(axis=1)
        Xd, d = X[ok].reset_index(drop=True), df[ok].reset_index(drop=True)
        y = d.dengue_cases.values.astype(float)
        tr, te = (d.year < TEST_START).values, (d.year >= TEST_START).values
        print("train", tr.sum(), "test", te.sum())
        res, preds = {}, {}

        # --- baselines
        clim = d[tr].groupby(["ward_id", "woy"]).dengue_cases.mean().rename("clim").reset_index()
        pc = d[te].merge(clim, on=["ward_id", "woy"], how="left").clim.fillna(d[tr].dengue_cases.mean()).values
        preds["Seasonal climatology"] = pc
        if sc["use_cases"]:
            preds["Persistence (last known week)"] = Xd.loc[te, "cases_lag0"].values

        # --- Poisson GLM
        Xg = Xd.copy()
        for c in Xg.columns:
            if c.startswith(("rain", "cases", "city_cases")): Xg[c] = np.log1p(Xg[c].clip(lower=0))
        glm = make_pipeline(StandardScaler(), PoissonRegressor(alpha=1e-3, max_iter=2000)).fit(Xg[tr], y[tr])
        preds["Poisson GLM"] = glm.predict(Xg[te])

        # --- Random forest
        rf = RandomForestRegressor(n_estimators=200, min_samples_leaf=5, max_features=0.4, n_jobs=-1, random_state=SEED).fit(Xd[tr], y[tr])
        preds["Random Forest"] = rf.predict(Xd[te])

        # --- tuned Poisson gradient boosting
        yrs = d.year.values
        cfg, cv_s = cv_hgb(Xd[tr].reset_index(drop=True), y[tr], yrs[tr])
        print("best HGB cfg", cfg, "cv deviance", round(cv_s, 4))
        hgb = HistGradientBoostingRegressor(loss="poisson", early_stopping=False, random_state=SEED, **cfg).fit(Xd[tr], y[tr])
        preds["Gradient Boosting (tuned, Poisson)"] = hgb.predict(Xd[te])
        preds["Ensemble (GB + RF)"] = 0.5 * preds["Gradient Boosting (tuned, Poisson)"] + 0.5 * preds["Random Forest"]

        meta = d[te][["date", "city", "ward_id", "month", "year"]].reset_index(drop=True)
        yt = y[te]
        for name, p in preds.items():
            res[name] = metrics(yt, p, meta)
            print(f"{name:38s} MAE={res[name]['MAE']:.3f} RMSE={res[name]['RMSE']:.3f} R2={res[name]['R2']:.3f} dev={res[name]['PoissonDeviance']:.3f}")
        ml = [k for k in res if k not in ("Seasonal climatology", "Persistence (last known week)")]
        best = min(ml, key=lambda k: res[k]["PoissonDeviance"])
        print("best:", best)

        # --- importance + partial dependence (gradient boosting, test data)
        groups = {}
        for c in Xd.columns: groups.setdefault(group_of(c), []).append(c)
        gi = group_importance(hgb, Xd[te].reset_index(drop=True), yt, groups)
        fi = group_importance(hgb, Xd[te].reset_index(drop=True), yt, {c: [c] for c in Xd.columns}, n_rep=3)
        top_f = dict(sorted(fi.items(), key=lambda kv: -kv[1])[:12])

        pdp = {}
        if True:
            for f in ["rain_sum4", "temp_avg_mean4", "hum_mean4", "static_sanitation", "static_waterlog", "static_density"]:
                if f in Xd.columns:
                    r_ = partial_dependence(hgb, Xd[tr].sample(4000, random_state=SEED), [f], grid_resolution=18, kind="average")
                    pdp[f] = {"x": r_["grid_values"][0].tolist(), "y": r_["average"][0].tolist()}

        # --- final refit on ALL data (2016-2025) for deployment
        fin = HistGradientBoostingRegressor(loss="poisson", early_stopping=False, random_state=SEED, **cfg).fit(Xd, y)
        joblib.dump({"model": fin, "features": list(Xd.columns), "scenario": sc, "params": cfg}, f"{output_dir}/models/model_{sk}.joblib")

        # --- dashboard payloads
        pb = preds[best]
        tdf = meta.assign(y=yt, p=pb)
        wk = tdf.groupby("date")[["y", "p"]].sum().reset_index()
        cityw = {c: tdf[tdf.city == c].groupby("date")[["y", "p"]].sum().round(2).reset_index() for c in CITIES}
        tdf["dec"] = pd.qcut(tdf.p.rank(method="first"), 10, labels=False)
        calib = tdf.groupby("dec")[["p", "y"]].mean().round(3).reset_index()
        ward = tdf.assign(ae=(tdf.y - tdf.p).abs()).groupby(["ward_id", "city"]).agg(actual=("y", "sum"), pred=("p", "sum"), mae=("ae", "mean")).round(2).reset_index()
        mon = tdf.groupby("month").agg(mae=("y", lambda s: 0)).index  # placeholder to keep month ordering
        monthly = tdf.groupby("month")[["y", "p"]].mean().round(3).reset_index()

        R["scenarios"][sk] = {
            "label": sc["label"], "best": best, "cv_deviance": cv_s, "params": cfg,
            "metrics": res, "group_importance": gi, "top_features": top_f, "pdp": pdp,
            "test_weekly": {"date": wk.date.dt.strftime("%Y-%m-%d").tolist(), "actual": wk.y.round(1).tolist(), "pred": wk.p.round(1).tolist()},
            "test_city": {c: {"date": v.date.dt.strftime("%Y-%m-%d").tolist(), "actual": v.y.tolist(), "pred": v.p.tolist()} for c, v in cityw.items()},
            "calibration": {"pred": calib.p.tolist(), "actual": calib.y.tolist()},
            "monthly": {"month": monthly.month.tolist(), "actual": monthly.y.tolist(), "pred": monthly.p.tolist()},
            "ward_test": ward.to_dict("records"),
            "n_train": int(tr.sum()), "n_test": int(te.sum()),
        }
        out = meta.copy(); out["actual"] = yt
        for k, v in preds.items(): out[k] = np.round(v, 3)
        out.to_csv(f"{output_dir}/predictions/test_predictions_{sk}.csv", index=False)

    add_eda_payload(df, CITIES, TEST_START, R)
    with open(os.path.join(output_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(clean(R), f)
    print("\nSaved artifacts to", output_dir)


if __name__ == "__main__":
    csv = sys.argv[1] if len(sys.argv) > 1 else "data/bangladesh_dengue_large_dataset.csv"
    output = sys.argv[2] if len(sys.argv) > 2 else "artifacts"
    run_pipeline(csv, output)
