"""Verify the onsite dataset and re-derive the supply conversion rule.

Run:  python scripts/verify_onsite_dataset.py

Checks:
  * onsite CSV has the same 31,320 rows (60 wards x 522 weeks) as the Phase 1 CSV,
    identical shared columns and no missing values;
  * the three new targets are a deterministic function of dengue_cases;
  * the rates in src/dengue_watch/ops/config.py reproduce 100% of rows with
    round_half_up(rate * cases), and prints the feasible interval for each rate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dengue_watch.ops import config as C  # noqa: E402

TARGETS = {"saline_bags": "saline_bags_needed", "diagnostic_kits": "diagnostic_kits_needed",
           "hospital_beds": "hospital_beds_required"}


def main() -> int:
    onsite = pd.read_csv(ROOT / "data/bangladesh_dengue_onsite.csv")
    phase1 = pd.read_csv(ROOT / "data/bangladesh_dengue_large_dataset.csv")
    assert onsite.shape == (31320, 15), onsite.shape
    assert int(onsite.isna().sum().sum()) == 0
    assert onsite.ward_id.nunique() == 60 and onsite.date.nunique() == 522
    assert onsite.date.min() == "2016-01-04" and onsite.date.max() == "2025-12-29"
    assert onsite[phase1.columns].astype(str).equals(phase1.astype(str)), "shared columns differ"
    print("OK  rows/wards/weeks:", len(onsite), onsite.ward_id.nunique(), onsite.date.nunique())
    print("OK  wards per city:", onsite.groupby("city").ward_id.nunique().to_dict())

    table = onsite.groupby("dengue_cases")[list(TARGETS.values())].nunique()
    assert (table == 1).all().all(), "targets are not a deterministic function of cases"
    print("OK  each target is a deterministic function of dengue_cases (0..%d)" % onsite.dengue_cases.max())

    cases = onsite.dengue_cases.to_numpy(dtype=float)
    uniq = np.unique(cases)
    for key, col in TARGETS.items():
        y = onsite[col].to_numpy()
        rate = C.SUPPLY_RATES[key]
        pred = np.floor(cases * rate + 0.5)
        acc = float((pred == y).mean())
        first = onsite.groupby("dengue_cases")[col].first().reindex(uniq).to_numpy()
        grid = np.arange(0.05, 3.0, 0.0001)
        feas = [r for r in grid if (np.floor(uniq * r + 0.5) == first).all()]
        print(f"{'OK ' if acc == 1.0 else 'BAD'} {col}: rate={rate} matches {acc:.2%} of rows; "
              f"feasible interval [{min(feas):.4f}, {max(feas):.4f}]")
        assert acc == 1.0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
