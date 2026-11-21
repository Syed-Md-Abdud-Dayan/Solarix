"""Forecast metrics, temporal tuning and permutation importance."""
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, mean_poisson_deviance, r2_score, roc_auc_score
from sklearn.ensemble import HistGradientBoostingRegressor

SEED = 0
def metrics(y, p, meta):
    p = np.clip(np.asarray(p, float), 1e-6, None)
    y = np.asarray(y, float)
    peak = meta.month.between(6, 10).values
    agg = pd.DataFrame({"c": meta.city.values, "d": meta.date.values, "y": y, "p": p}).groupby(["c", "d"])[["y", "p"]].sum()
    return {
        "MAE": mean_absolute_error(y, p),
        "RMSE": float(np.sqrt(mean_squared_error(y, p))),
        "PoissonDeviance": mean_poisson_deviance(y, p),
        "R2": r2_score(y, p),
        "MAE_peak_season": mean_absolute_error(y[peak], p[peak]),
        "R2_city_week": r2_score(agg.y, agg.p),
        "AUC_outbreak_ge10": roc_auc_score(y >= 10, p) if (y >= 10).sum() > 5 else None,
    }


def cv_hgb(X, y, years, n_cfg=10):
    rng = np.random.RandomState(SEED)
    space = dict(learning_rate=[0.03, 0.05, 0.08], max_iter=[200, 350, 500], max_leaf_nodes=[8, 15, 31],
                 min_samples_leaf=[20, 40, 80], l2_regularization=[0.0, 1.0, 5.0], max_depth=[None, 4, 6])
    cfgs = [{k: v[rng.randint(len(v))] for k, v in space.items()} for _ in range(n_cfg)]
    best, best_s, log = None, 1e9, []
    for cfg in cfgs:
        sc = []
        for yr in (2020, 2021, 2022):
            tr, va = years < yr, years == yr
            m = HistGradientBoostingRegressor(loss="poisson", early_stopping=False, random_state=SEED, **cfg).fit(X[tr], y[tr])
            sc.append(mean_poisson_deviance(y[va], np.clip(m.predict(X[va]), 1e-6, None)))
        s = float(np.mean(sc)); log.append((cfg, s))
        if s < best_s: best, best_s = cfg, s
    return best, best_s


def group_importance(model, X, y, groups, n_rep=5, n=5000):
    rng = np.random.RandomState(SEED)
    idx = rng.choice(len(X), min(n, len(X)), replace=False)
    Xs, ys = X.iloc[idx].reset_index(drop=True), y[idx]
    base = mean_poisson_deviance(ys, np.clip(model.predict(Xs), 1e-6, None))
    out = {}
    for gname, cols in groups.items():
        inc = []
        for _ in range(n_rep):
            Xp = Xs.copy()
            perm = rng.permutation(len(Xs))
            Xp[cols] = Xs[cols].values[perm]
            inc.append(mean_poisson_deviance(ys, np.clip(model.predict(Xp), 1e-6, None)) - base)
        out[gname] = float(np.mean(inc))
    return out


