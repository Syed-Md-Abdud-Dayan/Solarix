"""Phase 2 operations constants: every rate, weight, threshold and assumption lives here.

Nothing in the engines (allocation / overflow / simulator / dispatch) hardcodes a number;
they all read from this module so the math can be defended and tuned in one place.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 1. Supply conversion rule  (cases -> saline / kits / beds)
# ---------------------------------------------------------------------------
# Derived by scripts/verify_onsite_dataset.py from data/bangladesh_dengue_onsite.csv.
# For every one of the 31,320 rows the three new targets are an EXACT deterministic
# function of dengue_cases:
#       target = round_half_up(rate * dengue_cases)
# The feasible rate intervals that reproduce 100% of rows are
#       saline  [2.3834, 2.3863]  -> we use 2.385
#       kits    [1.1618, 1.1666]  -> we use 1.164
#       beds    [0.2969, 0.3000)  -> we use 0.298
# (The "round" numbers 2.4 / 1.15 / 0.3 only match 74% / 82% / 92% of rows.)
# For a forecast (fractional expected cases) we apply the same rate to the expected
# value and round half-up, which is the unbiased extension of the dataset rule.
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
# Optional planning safety buffer added on top of the forecast demand (0.10 = +10%).
DEFAULT_SAFETY_BUFFER = 0.0

# ---------------------------------------------------------------------------
# 2. Forecast / planning window
# ---------------------------------------------------------------------------
# The last data week (2025-12-29) is off-season (~1 case city-wide), so the demo
# planning week defaults to the existing "Peak season 2025" preset of the Phase 1 UI.
# Any data week can be chosen in the UI; operationally this would be the latest week.
DEFAULT_ORIGIN = os.getenv("OPS_ORIGIN", "2025-08-04")
DEFAULT_PLAN_HORIZON = 1          # allocation covers origin + 1 week ("upcoming week")
SIM_HORIZONS = (2, 3, 4)          # what-if simulator window (weeks ahead)

# Existing Phase 1 risk bands (app.RISK_BANDS) are reused; weights used for priority.
RISK_ORDER = ["Critical", "High", "Medium", "Low"]
RISK_WEIGHTS = {"Critical": 4.0, "High": 3.0, "Medium": 2.0, "Low": 1.0}

# ---------------------------------------------------------------------------
# 3. Allocation engine
# ---------------------------------------------------------------------------
# priority = risk_weight * (predicted_cases + PRIORITY_CASE_FLOOR) * density_factor
# density_factor = (density / median_density) ** DENSITY_EXPONENT
# The exponent < 1 keeps density a tie-breaker-plus, not a dominator.
DENSITY_EXPONENT = 0.5
PRIORITY_CASE_FLOOR = 0.5
# Equity guard: before the greedy pass, Critical/High wards are guaranteed this share
# of their own demand (if stock allows), so a very dense Medium ward cannot starve them.
EQUITY_FLOOR = {"Critical": 0.6, "High": 0.4, "Medium": 0.0, "Low": 0.0}
# Deficit flags on fulfilment ratio
DEFICIT_WARNING_BELOW = 1.0       # anything < 100% fulfilled is at least WARNING
DEFICIT_CRITICAL_BELOW = 0.6      # < 60% fulfilled is CRITICAL
# Regional stock at the 100% slider position = total demand of the PEAK week in the
# 4-week planning window (so 100% always covers the worst upcoming week).
# Super admin can override absolute numbers from the Admin panel / DB.
STOCK_PCT_MIN, STOCK_PCT_MAX = 30, 100

# ---------------------------------------------------------------------------
# 4. Spraying crews (vector control)
# ---------------------------------------------------------------------------
# crews_needed = clamp(ceil(BASE[risk] * density_factor), 0, MAX_CREWS_PER_WARD)
CREW_BASE_BY_RISK = {"Critical": 3.0, "High": 2.0, "Medium": 1.0, "Low": 0.0}
MAX_CREWS_PER_WARD = 4
DEFAULT_TOTAL_CREWS = 60

# ---------------------------------------------------------------------------
# 5. Hospital bed capacity (ASSUMPTION - the dataset has no capacity column)
# ---------------------------------------------------------------------------
# The dataset has no bed-capacity column, so capacity is an explicit, editable ASSUMPTION:
#   city_pool(c)  = ceil(P{CAPACITY_PERCENTILE} of city c's historical weekly TOTAL
#                   hospital_beds_required)   ("the city's hospitals cover all but the
#                   worst 1% of weeks"; P100 would make a city surge impossible)
#   capacity(w)   = city_pool(c) split across the city's wards in proportion to
#                   population_density_sqkm (population proxy), largest-remainder rounding.
# So capacity follows population, while demand follows population AND local transmission
# (water-logging, sanitation, rainfall) - which is exactly what creates intra-city imbalance.
# Stored in the DB and editable by hospital users / super admin. Not real hospital data.
CAPACITY_PERCENTILE = 99
MIN_WARD_BEDS = 1
# Overflow routing only sends patients to wards whose utilisation after receiving is
# <= this target (keeps a small headroom margin in receivers).
RECEIVER_MAX_UTILISATION = 1.0

# ---------------------------------------------------------------------------
# 6. What-if vector control simulator (model-driven)
# ---------------------------------------------------------------------------
# A crew deployment is translated into perturbations of the very features the ML
# horizon models consume, and the models are re-run (see simulator.py):
#   coverage(c) = 1 - exp(-COVERAGE_K * crews / density_factor)     (saturating)
#   larviciding  -> effective breeding-water (rainfall) of last INTERVENTION_WEEKS
#                   weeks multiplied by (1 - LARVICIDE_EFFICACY * coverage)
#   fogging      -> recent case pressure (transmission) of last INTERVENTION_WEEKS
#                   weeks multiplied by (1 - FOGGING_EFFICACY * coverage)
# Efficacy values are conservative mid-range figures from field literature on
# larval source management / space spraying (typically 30-80% vector reduction,
# short-lived for fogging). They are planning parameters, not measured here.
COVERAGE_K = 0.6
LARVICIDE_EFFICACY = 0.6
FOGGING_EFFICACY = 0.4
INTERVENTION_WEEKS = 4
SIM_MAX_CREWS_PER_WARD = 4
DEFAULT_SIM_CREWS = 10

# ---------------------------------------------------------------------------
# 7. Tasks / escalation
# ---------------------------------------------------------------------------
ACK_ESCALATION_HOURS = 12         # unacknowledged task older than this -> escalated
TASK_DUE_DAYS = {"saline": 2, "spraying": 3, "bed_routing": 1, "other": 3}

# ---------------------------------------------------------------------------
# 8. Uncertainty (shown next to allocations)
# ---------------------------------------------------------------------------
# Held-out MAE per horizon is read from artifacts/results.json at runtime; this
# fallback is used only if that file is unavailable.
FALLBACK_MAE = {1: 0.95, 2: 1.06, 3: 1.12, 4: 1.15}
