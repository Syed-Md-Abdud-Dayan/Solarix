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

## Risk prediction engine (new)

`GET /api/risk?city=Dhaka%20North&as_of=2025-08-04&horizon=3&rain_mult=1.0`

- `as_of`: any weekly date in the data (the model sees only data up to that date, no leakage).
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
