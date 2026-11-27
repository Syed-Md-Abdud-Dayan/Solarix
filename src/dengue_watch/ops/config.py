"""Phase 2 operations constants: every rate, weight, threshold and assumption lives here.

Nothing in the engines (allocation / overflow / simulator / dispatch) hardcodes a number;
they all read from this module so the math can be defended and tuned in one place.
"""
from __future__ import annotations

import os

SUPPLY_RATES = {
    "saline_bags": 2.385,
    "diagnostic_kits": 1.164,
    "hospital_beds": 0.298,
}
SUPPLY_LABELS = {
    "saline_bags": "Saline bags",
    "diagnostic_kits": "Diagnostic kits",
    "hospital_beds": "Hospital beds",
}
SUPPLY_LABELS_BN = {
    "saline_bags": "স্যালাইন ব্যাগ",
    "diagnostic_kits": "ডায়াগনস্টিক কিট",
    "hospital_beds": "হাসপাতাল বেড",
}
DEFAULT_SAFETY_BUFFER = 0.0

DEFAULT_ORIGIN = os.getenv("OPS_ORIGIN", "2025-08-04")
DEFAULT_PLAN_HORIZON = 1
SIM_HORIZONS = (2, 3, 4)

RISK_ORDER = ["Critical", "High", "Medium", "Low"]
RISK_WEIGHTS = {"Critical": 4.0, "High": 3.0, "Medium": 2.0, "Low": 1.0}

DENSITY_EXPONENT = 0.5
PRIORITY_CASE_FLOOR = 0.5
EQUITY_FLOOR = {"Critical": 0.6, "High": 0.4, "Medium": 0.0, "Low": 0.0}
DEFICIT_WARNING_BELOW = 1.0
DEFICIT_CRITICAL_BELOW = 0.6
STOCK_PCT_MIN, STOCK_PCT_MAX = 30, 100

CREW_BASE_BY_RISK = {"Critical": 3.0, "High": 2.0, "Medium": 1.0, "Low": 0.0}
MAX_CREWS_PER_WARD = 4
DEFAULT_TOTAL_CREWS = 60

CAPACITY_PERCENTILE = 99
MIN_WARD_BEDS = 1
RECEIVER_MAX_UTILISATION = 1.0

COVERAGE_K = 0.6
LARVICIDE_EFFICACY = 0.6
FOGGING_EFFICACY = 0.4
INTERVENTION_WEEKS = 4
SIM_MAX_CREWS_PER_WARD = 4
DEFAULT_SIM_CREWS = 10

ACK_ESCALATION_HOURS = 12
TASK_DUE_DAYS = {"saline": 2, "spraying": 3, "bed_routing": 1, "other": 3}

FALLBACK_MAE = {1: 0.95, 2: 1.06, 3: 1.12, 4: 1.15}
