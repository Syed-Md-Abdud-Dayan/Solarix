"""Forecast weeks AFTER the end of the data (2026, 2027, ...) and save a CSV.

    python scripts/forecast_future.py --end 2027-12-31
    python scripts/forecast_future.py --end 2028-12-31 --rain-mult 1.3 --temp-shift 1 --out artifacts/wet_warm.csv

Output columns (one row per ward per week):
    expected      mean predicted cases over 10 historical-weather scenarios
    p10 / p90     80% range (weather uncertainty + random case-count noise)
    risk          Low <2, Medium 2-5, High 5-9, Critical >=9 (on `expected`)
"""
import argparse, sys, warnings
from pathlib import Path
import joblib, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dengue_watch import future as F

warnings.filterwarnings("ignore")

def risk(v):
    return "Critical" if v >= 9 else "High" if v >= 5 else "Medium" if v >= 2 else "Low"

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data/bangladesh_dengue_large_dataset.csv"))
    ap.add_argument("--model", default=str(ROOT / "artifacts/models/model_h0.joblib"), help="weather-only (h0) model")
    ap.add_argument("--start", default=None, help="first week to keep (default: first week after the data)")
    ap.add_argument("--end", default="2027-12-31")
    ap.add_argument("--rain-mult", type=float, default=1.0, help="what-if rainfall multiplier, e.g. 1.3 = 30%% wetter")
    ap.add_argument("--temp-shift", type=float, default=0.0, help="what-if temperature change in deg C")
    ap.add_argument("--out", default=str(ROOT / "artifacts/forecast_future.csv"))
    a = ap.parse_args()

    df = pd.read_csv(a.data, parse_dates=["date"])
    res = F.forecast(df, joblib.load(a.model), end=a.end, start=a.start, rain_mult=a.rain_mult, temp_shift=a.temp_shift)
    res["risk"] = res.expected.map(risk)
    res[["expected", "p10", "p50", "p90"]] = res[["expected", "p10", "p50", "p90"]].round(2)
    res.to_csv(a.out, index=False)
    print(f"Saved {len(res):,} rows ({res.ward_id.nunique()} wards x {res.date.nunique()} weeks, "
          f"{res.date.min().date()} -> {res.date.max().date()}) to {a.out}")
    print(res.groupby(res.date.dt.year).expected.sum().round(0).to_string())

if __name__ == "__main__":
    main()
