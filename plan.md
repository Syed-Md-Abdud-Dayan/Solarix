# Bangladesh Dengue Hackathon — Preliminary Round
## Project Feasibility Proposal: What We Can and Cannot Do

| | |
|---|---|
| **Document type** | Pre-development scope and feasibility proposal |
| **Dataset** | `hackathon_preli_dataset_-_bangladesh_dengue_large_dataset.csv` |
| **Status** | Draft v1 — based on the dataset only (the official problem statement has not yet been reviewed against this document) |

---

## 1. Purpose

This document sets out, before any development starts, which objectives the provided dataset can credibly support and which it cannot. Its aim is to fix a realistic scope, avoid unsupported claims in the final submission, and give the team a shared reference.

> **Important:** This proposal is derived from the data alone. Once the official task brief and judging criteria are confirmed, Sections 7 and 10 should be used to re-align scope.

---

## 2. Dataset Summary

| Property | Value |
|---|---|
| Rows × columns | 31,320 × 12 |
| Time span | 2016-01-04 to 2025-12-29 (10 years) |
| Time resolution | **Weekly** (522 weeks, every record 7 days apart) |
| Spatial unit | **Ward** (60 wards across 5 cities) |
| Panel structure | 60 wards × 522 weeks, fully balanced |
| Missing values | None |
| Duplicate (date, ward) pairs | None |
| Temperature consistency (min ≤ avg ≤ max) | No violations |

### 2.1 Coverage by city

| City | Wards | Total cases (10 yrs) |
|---|---:|---:|
| Dhaka South | 20 | 27,193 |
| Dhaka North | 20 | 27,001 |
| Chattogram | 10 | 13,470 |
| Gazipur | 5 | 8,295 |
| Narayanganj | 5 | 6,613 |

### 2.2 Column groups

| Group | Columns | Behaviour |
|---|---|---|
| Identifiers | `date`, `city`, `ward_id` | — |
| Static ward attributes | `population_density_sqkm`, `water_logging_risk_index`, `sanitation_score` | Constant per ward over all 10 years |
| Dynamic weather | `avg_temp_c`, `max_temp_c`, `min_temp_c`, `rainfall_mm`, `relative_humidity_pct` | Vary weekly |
| Target | `dengue_cases` | Weekly count per ward (range 0–41) |

---

## 3. Key Findings from Initial Profiling

1. **Strong seasonality.** Cases are almost absent from November to March and peak in July–September (mean weekly cases per ward: Jan ≈ 0.01, Aug ≈ 9.5, Sep ≈ 8.5).
2. **Rainfall acts with a delay.** Correlation with cases is 0.53 at lag 0, rising to **0.75 at a 3-week lag**, then declining. This is epidemiologically plausible (rain → breeding sites → mosquito development → cases).
3. **Temperature also acts with a delay.** Correlation with average temperature rises from 0.34 (lag 0) to 0.60 at a 6-week lag.
4. **Humidity** shows a same-week correlation of 0.53.
5. **Ward-level risk differs systematically.** Across the 60 wards, total cases correlate with water-logging risk at **0.82**, population density at 0.57, and sanitation score at −0.40 (higher sanitation → fewer cases).
6. **Cases are strongly autocorrelated** (week-to-week correlation 0.75).
7. **The target is zero-inflated and skewed.** 58% of rows are zero; the 95th percentile is 13 cases and the maximum is 41.
8. **Year-to-year outbreak size varies.** Annual totals range from about 6,500 to 10,000, with no clean monotonic trend.

### 3.1 Quick baseline check (feasibility test only)

A simple gradient-boosting model was trained on 2016–2023 and tested on 2024–2025, predicting **one week ahead** per ward using lagged cases and lagged weather.

| Model | MAE (cases/ward/week) | R² |
|---|---:|---:|
| Predict global mean | 3.13 | — |
| Persistence (last week's cases) | 1.41 | 0.46 |
| Gradient boosting (lags + weather + ward attributes) | **1.03** | **0.72** |
| Same, **without** past-case lags (weather and ward attributes only) | 1.04 | 0.71 |

This is a feasibility indicator only, not a final result. It shows that the data carries genuine predictive signal, and notably that **weather and ward attributes alone are almost as informative as past case counts**.

---

## 4. What We CAN Do

| # | Objective | Why the data supports it | Confidence |
|---|---|---|---|
| C1 | **Exploratory analysis and visualisation** of seasonality, city and ward patterns, yearly outbreaks | Complete, clean, balanced panel | High |
| C2 | **Short-term forecasting** (1–4 weeks ahead) of weekly cases per ward | Strong autocorrelation and lagged weather signal; baseline already beats naive methods | High |
| C3 | **Weather-lag analysis**: quantify how many weeks rainfall, temperature and humidity lead cases | Clear lag structure found (peak around 3 weeks for rainfall) | High |
| C4 | **Ward risk ranking / hotspot identification** using static attributes plus historical burden | Large, consistent between-ward differences linked to water-logging, density, sanitation | High |
| C5 | **Early-warning indicator**: flag weeks or wards likely to exceed an outbreak threshold | Seasonal and lagged-weather signal; can be framed as classification | Medium–High |
| C6 | **Driver interpretation** (feature importance, partial dependence, SHAP) | Few, interpretable variables | Medium–High |
| C7 | **What-if / scenario exploration** (e.g. heavier rainfall, hotter season, improved sanitation) as a *model-based sensitivity tool* | Model can be queried with altered inputs | Medium (see limits in 5.3) |
| C8 | **Interactive dashboard** (city/ward filters, risk map-style grid, forecast chart, alerts) | All components computable from the dataset | High |
| C9 | **Cross-city comparison** and per-city model performance | Five cities available | Medium (small cities have only 5 wards each) |
| C10 | **Resource-allocation guidance** (which wards to prioritise for inspection or fogging, and when) derived from C4 and C5 | Directly follows from risk ranking and forecasts | Medium |

---

## 5. What We CANNOT Do (or Cannot Claim)

### 5.1 Data that is absent

| # | Limitation | Reason |
|---|---|---|
| X1 | **True geographic mapping** (choropleth on real ward boundaries) | No latitude/longitude or boundary data. Only anonymised ward IDs are provided. A real map would require external, verified boundary files. |
| X2 | **Spatial spread modelling** (neighbour-to-neighbour transmission, diffusion) | No adjacency or coordinates; ward IDs do not reveal neighbours. |
| X3 | **Entomological analysis** (mosquito density, Breteau/House indices, larval surveys) | Not in the dataset. |
| X4 | **Serotype analysis** (DENV-1 to DENV-4) or immunity-driven outbreak explanation | Not in the dataset. |
| X5 | **Demographic or individual-level analysis** (age, sex, severity, hospitalisation, mortality) | Only aggregated weekly counts. |
| X6 | **Intervention-effect evaluation** (did fogging or campaigns work?) | No intervention records. |
| X7 | **Daily-resolution forecasting** | Data is weekly. |
| X8 | **Population-normalised incidence rates** (cases per 100,000) | Only density (people/km²) is given, not ward population or area. |

### 5.2 Structural constraints

| # | Limitation | Consequence |
|---|---|---|
| X9 | Ward attributes are **constant for 10 years** | We cannot study how changing sanitation, drainage or density affects cases over time. |
| X10 | Only **10 yearly seasons** | Limited evidence for year-level outbreak size; long-horizon (seasonal-total) forecasting is unreliable. |
| X11 | Only **60 wards**, with 5 each in two cities | Ward-level conclusions per small city are statistically weak. |
| X12 | Weather variables are **mutually correlated** (avg, max, min temperature) | Individual coefficients and "effect of one degree" claims are unstable. |
| X13 | Weather is **observed**, not forecast | A truly operational forecast would need external weather forecasts beyond about 3 weeks; our lead time is naturally limited by the lag structure. |

### 5.3 Claims we must not make

- **No causal claims.** The data shows association and lag, not proof of cause. Statements such as "improving sanitation by X reduces cases by Y" cannot be validated here.
- **No claim of real-world deployment readiness.** Results are retrospective on one dataset, with no external validation.
- **No generalisation beyond the five cities** or beyond the observed climate range (2016–2025).
- **No ward-specific public-health decisions** presented as final; outputs are decision-support only.

---

## 6. Data Provenance Caveat

Several characteristics suggest the dataset may be **partly or wholly simulated** for the hackathon: perfectly balanced panel, zero missing values, ward attributes fixed for a decade, very regular seasonality, and ward totals that track the supplied risk indices very closely. This is an observation, not a confirmed fact. It matters because:

- Strong results may partly reflect how the data was generated rather than real-world dynamics.
- We should present findings as *"patterns in the provided dataset"*, not as validated epidemiological conclusions.
- We should confirm provenance with the organisers if possible.

---

## 7. Proposed Scope

### 7.1 Recommended core deliverables (priority order)

1. **Data audit and EDA** — seasonality, city/ward comparison, outlier and zero-inflation handling (C1, C3).
2. **Forecasting model** — 1–4 week ahead cases per ward with a strict time-based validation (train 2016–2023, test 2024–2025, optionally rolling-origin) and comparison against naive baselines (C2).
3. **Ward risk ranking and hotspot view** — combining static attributes and model outputs (C4, C10).
4. **Early-warning flag** — outbreak-threshold classification with precision/recall reported (C5).
5. **Interpretability layer** — drivers and lag effects explained in plain language (C3, C6).
6. **Dashboard** — forecast, risk ranking, ward/city filters, alert panel (C8).

### 7.2 Optional extensions (only if time allows)

- Scenario sliders for rainfall, temperature and sanitation, clearly labelled as sensitivity analysis (C7).
- Uncertainty intervals on forecasts (e.g. quantile or count-distribution models suited to zero-inflated data).
- Per-city model comparison (C9).

### 7.3 Explicitly out of scope

Everything listed in Section 5 (X1–X13), including real maps, spatial transmission, mosquito or serotype analysis, and any causal intervention claims.

---

## 8. Proposed Technical Approach

| Stage | Plan |
|---|---|
| **Preparation** | Parse dates; sort by ward and date; build lag features (cases and weather, 1–6 weeks); add week-of-year and cyclical seasonality features; encode city. |
| **Validation** | Strictly chronological split. Never shuffle, to avoid future leakage. Hold out whole recent seasons. Check the ward-level and peak-season performance separately, not just the overall average. |
| **Models** | Baselines: persistence, seasonal average. Main: gradient boosting (LightGBM / HistGradientBoosting). Consider count-aware objectives (Poisson / Tweedie) given zero inflation. Optional: simple interpretable model (e.g. negative binomial regression) for transparency. |
| **Metrics** | MAE and RMSE; Poisson deviance; R²; for alerts: precision, recall, F1 on the outbreak threshold; peak-timing error. |
| **Interpretation** | Feature importance, SHAP, lag-correlation plots. |
| **Presentation** | Dashboard plus a short written methodology with the limitations in Section 5 stated openly. |

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Over-optimistic scores from leakage (e.g. random split, same-week features) | Invalid results | Chronological validation; only use information available at prediction time |
| Misleading overall metrics because ~58% of rows are zero | Model looks good in off-season, poor at peak | Report season-stratified metrics and peak-season errors |
| Overinterpretation of simulated-looking data | Unsupported claims | State provenance caveat (Section 6) and avoid causal wording |
| Same-week weather used as a predictor | Not usable for real forecasting | Use only lagged weather (≥ 1 week) in the main model |
| Scope creep into unsupported areas (maps, spread, mosquito data) | Wasted time, weak claims | Keep to Section 7.1; treat Section 5 as a hard boundary |

---

## 10. Open Questions (to confirm before coding)

1. What exactly does the official problem statement ask for: forecasting, risk mapping, a dashboard, a policy proposal, or a combination?
2. Which evaluation criteria and metrics will judges use?
3. Are external datasets allowed (e.g. ward boundaries, population, weather forecasts)?
4. Is the dataset real, synthetic, or a mix?
5. Are there submission format requirements (notebook, app, slides, report) and deadlines?

---

## 11. Conclusion

The dataset is **clean, complete, and well suited to weekly, ward-level dengue forecasting, risk ranking, and weather-lag analysis**, with a clear seasonal pattern and a measurable 3-week rainfall lead. A quick baseline already shows meaningful predictive power. It is **not suited** to real-map visualisation, spatial spread modelling, entomological or serotype analysis, intervention evaluation, or any causal claim. We recommend focusing on the core deliverables in Section 7.1 and stating the limits in Section 5 clearly in the final submission.
