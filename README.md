# Dengue Watch — Model-connected Dengue Pulse

A Bangladesh ward-level dengue forecasting research dashboard. The browser dashboard now calls a local Python API, which loads the saved scikit-learn models in `artifacts/models/` and generates predictions from the bundled dataset. It no longer creates random ward names, scores, weather, or forecast values in JavaScript.

## What is connected

- All 13 saved horizon models: `model_h0.joblib` through `model_h12.joblib`.
- The real ward IDs and city assignments from `data/bangladesh_dengue_large_dataset.csv`.
- Forecasts for 0–12 weeks. Horizon 0 is the weather-only latest-week nowcast; horizons 1–12 use the matching saved horizon model and historical inputs available at the dataset's latest observation.
- Historical weekly reported cases, model evaluation metrics, and feature-group importance from `artifacts/results.json`.
- City selector, forecast horizon selector, ward search, and CSV export.

## Requirements

Use Python 3.10 or newer. The model artifacts were serialized with scikit-learn 1.9.1, so install the pinned version to avoid pickle/model compatibility problems.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows Git Bash:
source .venv/Scripts/activate
# macOS/Linux:
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## Run the website and model API

Run from the project root (`dengue-watch/`):

```bash
python app.py
```

Open **http://127.0.0.1:5000**. Keep the terminal running while using the dashboard. The API is served by Python's standard library HTTP server; no separate Node, Flask, or frontend build step is needed.

## Dengue chatbot ("Ask Dengue Watch")

A bilingual (English / বাংলা) assistant lives on the **Ask Dengue Watch** page and at `POST /api/chat`. It is a deterministic,
explainable engine - no external LLM or API key - so it works offline and never invents numbers.

| Layer | What it does | Code |
|---|---|---|
| Safety triage | Detects danger signs (belly pain, repeated vomiting, bleeding, drowsiness, breathing trouble, cold skin, low urine, seizure) in a personal context and answers with urgent hospital guidance + Bangladesh hotlines *before anything else* | `chatbot.py` |
| Symptom guidance | "I have fever for 3 days" -> test timing (NS1 vs antibody), care, no NSAIDs, when to go to hospital; higher-risk groups get same-day advice. Never diagnoses, never gives drug doses | `chatbot.py` |
| Knowledge base | 20 WHO-aligned topics in English and Bangla: symptoms, warning signs, prevention, treatment, home care, diet, platelets, testing, transmission, vaccines, myths, children/pregnancy, season, weather link... | `knowledge.py` |
| Live model answers | City/ward risk, top wards, city comparison, any month/year up to 2030, rainfall/temperature what-ifs, history, model accuracy, action plans by risk level | `chatbot.py` + `AppBackend` in `app.py` |
| Memory | Remembers city / ward / horizon between turns ("what about Gazipur?") | client sends back `context` |
| Honesty | The bundled data ends 2025-12-29. If that is >12 weeks before today the bot says so and switches from the 12-week models to the seasonal long-range forecast; what-ifs in the off-season are tested on the coming peak season | `_stale()` |

Examples: `risk in Dhaka North next 4 weeks`, `top wards in Gazipur`, `ward 5 in dhaka south`, `forecast for August 2026`,
`what if rainfall doubles in Gazipur`, `compare Dhaka North and Chattogram`, `how accurate is the model`, `ঢাকা উত্তরের ঝুঁকি`.

API:

```bash
curl -s -X POST localhost:5000/api/chat -H 'Content-Type: application/json' \
  -d '{"message":"top wards in Dhaka North","context":{},"lang":"en"}'
```

The reply contains `reply` (title/text/bullets/table/notes), `severity` (`info|caution|emergency`), `suggestions` (follow-up chips),
`sources`, `disclaimer` and the updated `context` to send with the next message. Requests are limited to 8 KB, messages to 500
characters and 40 messages/minute/IP.

Tests: `pip install pytest && python -m pytest tests -q`

**Safety note:** the assistant provides general health information, not diagnosis. Hotline numbers (DGHS 16263, IEDCR 10655,
emergency 999) should be re-verified before public deployment, and a clinician should review `knowledge.py` before it is shown to the public.

## Future forecast: 2026, 2027 and beyond (new)

The 0-12 week models need the latest observed weather/cases, so they stop at 2026-03-23. For anything later the
**long-range forecaster** (`src/dengue_watch/future.py`) uses the weather-only model and replays each of the 10 past
years' weather as a possible future (10 scenarios). Output per ward and week: `expected`, plus an 80% range (`p10`-`p90`)
that includes weather uncertainty **and** random case-count noise.

- Website: **http://127.0.0.1:5000/future.html** (sidebar: "Future 2026+"). Any city, any dates up to 2030-12-31,
  optional what-if (wetter/drier year, warmer temperature), CSV download.
- API: `GET /api/future?city=Dhaka%20North&start=2026-01-05&end=2027-12-31&rain_mult=1.0&temp_shift=0`
  (`city=All` for the whole dataset).
- CSV: `python scripts/forecast_future.py --end 2027-12-31` (ready-made: `artifacts/forecast_2026_2027.csv`).
- Accuracy test on unseen years: `python scripts/backtest_future.py` -> `artifacts/future_backtest.json`.

**Honest accuracy (train before year Y, forecast all of Y blind; Y = 2023, 2024, 2025):**

| Measure | Result |
|---|---|
| Ward-week R² | 0.64 (0.62-0.67) |
| City-week R² | 0.76 |
| Plain seasonal-average baseline R² | 0.62 (so the model adds only a little at this range) |
| Same model if real weather were known | 0.85 (the gap is the weather we cannot know) |
| Yearly total error | -16%, +26%, +12% |
| Peak-week timing | off by 3 to 8 weeks |
| 80% range actually covering the outcome (city-week) | 83-88% |

What this means: it is a good guide to **how big and when in the season** (roughly June-October, peak August) and
**which wards are worse**. It is not a prediction of which exact week or how large a specific year's outbreak will be.
2026 and 2027 come out almost identical **by construction** (no information separates them); the what-if sliders show
how the model responds to rain/temperature, not causal truth. Beyond 12 weeks the forecast does not get worse with
distance, because it no longer depends on current conditions.

## Risk prediction engine (new)

`GET /api/risk?city=Dhaka%20North&as_of=2025-08-04&horizon=3&rain_mult=1.0`

- `as_of`: any weekly date in the data. The model *inputs* stop at that date, **but the saved models were trained on all of 2016-2025, so back-tests on past dates are in-sample and look better than reality** (e.g. h3 R² 0.86 in-sample vs 0.77 held-out). Use `results.json` / Model accuracy page for honest numbers.
- `horizon`: 1-12 weeks ahead (2-4 weeks is the default early-warning window).
- `rain_mult`: what-if multiplier (0.2-3.0) on the last 4 weeks of rainfall.
- Returns Low / Medium / High / Critical per ward and city, plain-language drivers, the 8-week rainfall series, and real reported cases when back-testing a past date.
- Bands (expected cases per ward-week): Low <2, Medium 2-5, High 5-9, Critical >=9.
- Efficient: local models, no external API calls, cached results, only the last 30 weeks of history processed per request.

## Pages

Risk prediction (home), Forecasts, Ward explorer, Alerts, Action plan, Ask Dengue Watch, Model & data. Alerts, action plan and the Ask helper are generated from the current `/api/risk` result (no example data). Read/done state is kept in the browser. Logo files: `web/assets/img/`.

## API endpoints

- `GET /api/health` — backend status, loaded model count, cities, ward count, latest observation date.
- `GET /api/dashboard?city=Chattogram&horizon=3` — city totals, forecast series, observed history, model metrics, feature importance, and ward-level predictions.
- `GET /api/ward/CCC_Ward_01?horizon=3` — one ward's prediction output.
- `GET /api/future?...` — long-range forecast beyond the data (see above).

Supported city values are returned by `/api/health`: Chattogram, Dhaka North, Dhaka South, Gazipur, and Narayanganj. Horizon must be an integer from 0 to 12.

## Important interpretation notes

- The bundled dataset's latest observation is **2025-12-29**. Selecting a horizon forecasts relative to that date; it does not make the dataset current. New, validated surveillance and weather data must be supplied before using this as a current operational warning system.
- Predictions are expected case counts and may be fractional because the models estimate a mean. They are not guaranteed actual case counts.
- The priority labels are relative ranks among wards in the selected city (top 10%, next 20%, and remaining wards). They are not calibrated disease-risk probabilities or clinical risk categories.
- Feature-group importance comes from the saved evaluation results. It is not causal evidence.
- The dashboard is a research decision-support prototype, not an official public-health alert or medical advice.

## Retrain models

To reproduce/retrain the horizon models and regenerate the evaluation artifacts:

```bash
python scripts/train_dengue.py
```

This writes model files, test predictions, and `artifacts/results.json`. Restart `python app.py` after replacing the model artifacts so the server reloads them.

## Project structure

```text
dengue-watch/
├── app.py                         # Python API + static web server
├── data/bangladesh_dengue_large_dataset.csv
├── artifacts/
│   ├── models/model_h0.joblib ... model_h12.joblib
│   ├── predictions/
│   └── results.json
├── src/dengue_watch/              # Feature engineering, training pipeline, evaluation, EDA
├── scripts/train_dengue.py
└── web/
    ├── index.html
    └── assets/{css/dashboard.css,js/dashboard.js}
```
