# Dengue Watch

**A ward-level dengue forecasting and early-warning dashboard for Bangladesh.**

Dengue Watch analyzes weekly case and weather data across 60 wards in five cities. It produces forecasts up to 12 weeks ahead, classifies ward-level risk, and presents alerts, visual analytics, and an English–Bangla information assistant.

> **Research prototype:** This project is intended for experimentation and decision-support research. It is not an official public-health warning system, and its results have not been validated against independent surveillance records.

[Live Demo](https://dengue-watcher.onrender.com) · [Architecture](ARCHITECTURE.md) · [Project Plan](plan.md)

---
## Team Solarix
 
| Name | Student ID |
|---|---|
| Md. Abrar Hossain | 232006512 |
| Syed Mohammad Abdud Dayan | 232001312 |
| Mohtada Ayesha Aalim Chowdhury | 232007512 |
## Overview

The dashboard is designed to help users explore where dengue risk may increase and how that risk changes over time.

- **Ward-level forecasting:** Estimates weekly dengue cases from the current week to 12 weeks ahead.
- **Risk classification:** Groups predicted cases into Low, Medium, High, and Critical risk levels.
- **Ward exploration:** Compare wards and inspect their forecast trends.
- **Alerts and action planning:** Surface higher-risk wards and provide suggested follow-up actions.
- **Long-range outlook:** Explore a seasonal forecast for 2026–2027.
- **Bilingual assistant:** Ask Dengue Watch questions in English or Bangla.

## Dashboard

<p align="center">
  <img src="docs/screenshots/risk-map.png" alt="Dengue Watch ward risk overview" width="100%">
</p>

<p align="center">
  <img src="docs/screenshots/forecasts.png" alt="Dengue case forecasts" width="49%">
  <img src="docs/screenshots/ward-explorer.png" alt="Ward explorer" width="49%">
</p>

<p align="center">
  <img src="docs/screenshots/alerts.png" alt="Risk alerts" width="49%">
  <img src="docs/screenshots/action-plan.png" alt="Suggested action plan" width="49%">
</p>

<p align="center">
  <img src="docs/screenshots/model-accuracy.png" alt="Model evaluation" width="49%">
  <img src="docs/screenshots/ask-dengue-watch.png" alt="Bilingual Dengue Watch assistant" width="49%">
</p>

<p align="center">
  <img src="docs/screenshots/model-and-data.png" alt="Model and dataset information" width="75%">
</p>

*The risk-map view is a schematic network, not a geographic map. The dataset does not contain ward coordinates or boundary geometries.*

## Phase 2: Operations Command (onsite final)

Phase 2 extends the forecasting dashboard into an **operational resource-optimisation, intervention-simulation
and dispatch system** for ward commissioners, their secretaries, field teams, hospital managers and a regional
super admin. Open **`/ops/`** (or the "Operations (Phase 2)" link in the dashboard sidebar).

| # | Requirement | Where |
|---|---|---|
| 1 | **Constrained resource allocation**: saline bags, diagnostic kits, hospital beds and spraying crews under live scarcity sliders (regional stock 30-100%, total crews), prioritising high-risk, high-density wards, with live critical-deficit warnings | Regional command > Allocation · `GET /api/alloc` |
| 2 | **Hospital surge & intra-city overflow routing**: net ward deficit, headroom, city-wide utilisation, transfer list, city-surge alerts | Regional command > Hospital overflow · Hospital portal · `GET /api/overflow` |
| 3 | **Model-driven what-if vector control simulator**: weeks +2 to +4 reduction in cases, bed load and saline, ROI ranking (cases prevented per crew), greedy recommendation | Regional command > Simulator · `GET/POST /api/simulate` |
| 4 | **Multi-channel dispatch**: SMS (single + multi-part), WhatsApp, printable A4 HTML / PDF commissioner briefs, in English and Bangla | Commissioner page · `GET /api/dispatch/<ward>` · [`exports/`](exports/) |
| 5 | **Offline resilience & deterministic fallback**: 100% local; kill-switch demo; seasonal fallback forecast; service worker; offline action queue | [docs/OFFLINE.md](docs/OFFLINE.md) · `GET /api/ops/health` |

Extras: role-based platform (super admin, commissioner, secretary, saline / spraying / bed teams, hospital),
task lifecycle with idempotent auto plan and manual overrides (reason logged), progress % per ward / city / team,
escalation of unacknowledged or overdue tasks, audit log, equity guard, before/after scarcity comparison,
stock replenishment requests per city, forecast uncertainty (± held-out MAE), CSV / JSON exports, "print all
briefs" bundle, EN / বাংলা toggle, mobile layout for field teams, installable PWA.

<p align="center">
  <img src="docs/screenshots/ops-allocation.png" alt="Constrained allocation at 30% stock with deficit warnings" width="49%">
  <img src="docs/screenshots/ops-simulator.png" alt="Model-driven vector control simulator with ROI ranking" width="49%">
</p>
<p align="center">
  <img src="docs/screenshots/ops-overflow.png" alt="Intra-city hospital overflow routing" width="49%">
  <img src="docs/screenshots/ops-commissioner-bn.png" alt="Ward commissioner dashboard in Bangla" width="49%">
</p>
<p align="center">
  <img src="docs/screenshots/ops-operations.png" alt="Region-wide plan, progress and outbox" width="49%">
  <img src="docs/screenshots/ops-hospital.png" alt="Hospital portal: transfers and capacity" width="49%">
</p>
<p align="center">
  <img src="docs/screenshots/ops-team-mobile.png" alt="Spraying team panel on a phone, ordered by risk" width="24%">
  <img src="docs/screenshots/ops-team-offline.png" alt="Team panel in offline kill-switch mode" width="24%">
</p>

### How the numbers are made (short)

- **Supply rule** verified on all 31,320 onsite rows: `round_half_up(2.385 / 1.164 / 0.298 x cases)` for saline / kits / beds
  (`python scripts/verify_onsite_dataset.py`).
- **Allocation**: priority = risk weight x (cases + 0.5) x sqrt(density / median); equity floor for Critical / High, then greedy
  fill (optimal for this equal-cost problem). 100% stock = peak-week demand of the next 4 weeks.
- **Overflow**: bed capacity is an **assumed, editable baseline** (the dataset has none): city pool = P99 of the city's weekly
  total bed requirement (covers all but the worst 1% of weeks), split by population density. Patients go to the lowest-utilisation ward in the same city.
- **Simulator**: crews raise coverage, which scales the ward's recent breeding-rainfall and transmission inputs; the
  2/3/4-week ML models are re-run on those inputs.
- Full details and assumptions: [ARCHITECTURE.md](ARCHITECTURE.md#phase-2-onsite-final-operations-command-system), [docs/OFFLINE.md](docs/OFFLINE.md),
  Q&A prep: [docs/QA_CHEATSHEET.md](docs/QA_CHEATSHEET.md).

### Demo logins (DEMO ONLY)

> These seeded accounts exist only for the demo. Set `ADMIN_PASSWORD`, `DEMO_PASSWORD` and `OPS_SECRET`
> environment variables before the first start in any real deployment. Phone numbers in the seed are fake placeholders.

| Role | Username | Password |
|---|---|---|
| Super admin (regional officer) | `admin` | `admin1234` |
| Ward commissioner | `comm_<city><ward>`, e.g. `comm_dncc03`, `comm_ccc01` | `demo1234` |
| Commissioner's secretary | `sec_<city><ward>`, e.g. `sec_dncc03` | `demo1234` |
| Saline / spraying / bed team | `saline_<city>`, `spray_<city>`, `beds_<city>`, e.g. `spray_dncc` | `demo1234` |
| Hospital manager | `hosp_<city>`, e.g. `hosp_dncc` | `demo1234` |

City codes: `dncc` Dhaka North, `dscc` Dhaka South, `ccc` Chattogram, `gcc` Gazipur, `ncc` Narayanganj.

### Offline demo (kill-switch)

1. `python -m pytest tests/test_offline.py -q`: all sockets and DNS blocked; the full pipeline still runs with zero network attempts.
2. Open `/api/ops/health`: `offline_capable: true`, `external_calls: []`, `llm_used: false`.
3. Log in once, then turn Wi-Fi off (or tick **Offline kill-switch demo** in the sidebar). Pages keep the last synced plan,
   show an offline banner, and team actions queue and sync automatically on reconnect.
4. Regional command > Settings > **Model kill-switch**: all engines switch to the deterministic seasonal fallback forecast.

### Optional live delivery (env vars)

Nothing below is required; without it, notices are delivered in-app, offered as `wa.me` / `sms:` click-to-send links
and written to `exports/runtime/`.

| Channel | Env vars |
|---|---|
| WhatsApp Cloud API | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` |
| SMS via Twilio | `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM` |
| Telegram ops group (mirror) | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Email ops mailbox (mirror) | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO` |
| Other | `OPS_DB` (SQLite path, default `data/ops.db`), `OPS_ORIGIN` (default planning week), `OPS_FORCE_FALLBACK=1` |

Optional: `pip install reportlab` enables real PDF briefs; without it the printable HTML brief (Print > Save as PDF) is used.

## Dataset

The project uses `data/bangladesh_dengue_large_dataset.csv`, containing:

| Attribute | Description |
|---|---|
| Coverage | 60 wards across five cities |
| Cities | Dhaka North, Dhaka South, Chattogram, Gazipur, and Narayanganj |
| Period | 2016–2025 |
| Records | 31,320 weekly ward records |
| Target | Weekly dengue case count |
| Predictors | Weather variables and ward-level profile features |

The dataset contains a high proportion of zero-case records. Its regular patterns and fixed ward profiles suggest that it may be partly or wholly simulated. Therefore, the reported performance should be interpreted as performance on this dataset—not as evidence of real-world outbreak prediction accuracy.

## Methodology

The forecasting pipeline builds horizon-specific features from weather history, seasonal signals, ward profiles, and (for horizons greater than zero) historical case counts.

Candidate models include:

- Poisson Generalized Linear Model
- Random Forest
- Gradient Boosting with Poisson loss
- A Gradient Boosting–Random Forest ensemble
- Seasonal-average and persistence baselines

Models are evaluated using a chronological split: training on data before 2023 and testing on 2023–2025. Hyperparameter tuning uses earlier time-based folds. The saved serving models are subsequently refit on the full dataset.

All time-varying inputs are shifted according to the forecast horizon to avoid using future information when generating a prediction.

## Evaluation

Selected held-out test results are shown below. MAE is measured in cases per ward per week.

| Forecast horizon | MAE | R² | Outbreak AUC |
|---|---:|---:|---:|
| Weather-only nowcast | 0.87 | 0.85 | 0.98 |
| 3 weeks ahead | 1.10 | 0.77 | 0.96 |
| 12 weeks ahead | 1.35 | 0.64 | 0.93 |

At three weeks ahead, using 10 or more cases in a ward-week as the outbreak threshold, the reported alarm precision is 67.9%, recall is 55.7%, and F1 is 61.2%.

**How to interpret these results:** Short-range forecasts outperform the seasonal-average baseline in this dataset. At 12 weeks, performance is approximately equal to the seasonal average. Errors are higher during the June–October peak season. The system is more useful for exploring near-term patterns than for predicting the exact timing or magnitude of a future outbreak.

## Long-range outlook

The project also generates a 2026–2027 seasonal outlook. Beyond the 12-week model horizon, historical weather patterns are used to estimate expected seasonal values and an 80% range.

This is a scenario-based seasonal view, not a year-specific weather forecast. Since the available data does not distinguish future weather conditions for 2026 from 2027, their projections are similar by design.

## Technology Stack

| Area | Tools |
|---|---|
| Language | Python |
| Data processing | pandas, NumPy |
| Machine learning | scikit-learn |
| Model persistence | joblib |
| Backend | Python standard-library HTTP server |
| Frontend | HTML, CSS, JavaScript, SVG |
| Testing | pytest |
| Deployment | Render |

The application does not require Node.js or an external AI API. The Ask Dengue Watch assistant uses a project knowledge base and model outputs; it is not a generative-AI diagnostic system.

## Getting Started

### Requirements

- Python 3.10+
- pip

The saved models require the pinned scikit-learn version in `requirements.txt`.

### Installation

```bash
git clone https://github.com/Syed-Md-Abdud-Dayan/Solarix.git
cd Solarix

python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

### Run the application

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser. The long-range forecast page is available at `/future.html`.

## Useful Commands

| Task | Command |
|---|---|
| Run tests | `pip install -r requirements-dev.txt && python -m pytest tests -q` |
| Verify API | `python verify_api.py` |
| Retrain forecasting models | `python scripts/train_dengue.py` |
| Export future forecast | `python scripts/forecast_future.py --end 2027-12-31` |
| Run long-range backtest | `python scripts/backtest_future.py` |
| Verify onsite dataset + supply rule | `python scripts/verify_onsite_dataset.py` |
| Smoke-test Phase 2 engines | `python verify_ops.py` |
| Regenerate `/exports` samples | `python scripts/export_samples.py` |

## API

The application exposes the following endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Service health check |
| GET | `/api/dashboard` | Dashboard summary data |
| GET | `/api/risk` | Ward-level risk information |
| GET | `/api/map` | Schematic ward network data |
| GET | `/api/ward/<id>` | Details for a ward |
| GET | `/api/future` | Long-range forecast |
| GET | `/api/chat/suggestions` | Assistant prompt suggestions |
| POST | `/api/chat` | Ask the bilingual assistant |
| GET | `/api/ops/health` | Offline self-check (`offline_capable`, `external_calls`) |
| GET | `/api/ops/forecast` | Ward forecasts +1..+4 weeks with upcoming-week High/Medium/Low |
| GET | `/api/alloc` | Constrained allocation (`stock_pct` 30-100, `crews`, `buffer`, `horizon`, `equity`) |
| GET | `/api/overflow` | Intra-city hospital overflow routing |
| GET / POST | `/api/simulate` | Recommended crew deployment + ROI ranking / simulate a chosen deployment |
| GET | `/api/dispatch/<ward>` | Dispatch notices (`lang=en\|bn`, `format=json\|sms\|whatsapp\|html\|pdf`) |
| POST | `/api/ops/login`, `/api/ops/logout` | Session login / logout |
| GET / POST | `/api/ops/plan`, `/api/ops/plan/generate` | Scoped weekly plan / generate tasks (idempotent) |
| GET / POST | `/api/ops/tasks`, `/api/ops/tasks/<id>` | List, create, update, override, reassign tasks |
| GET | `/api/ops/progress`, `/api/ops/inbox`, `/api/ops/hospital`, `/api/ops/audit` | Progress, team inbox, hospital view, audit log |
| POST | `/api/ops/capacity`, `/api/ops/transfers/<id>`, `/api/ops/notify/retry`, `/api/ops/batch` | Capacity edits, transfer decisions, retry queued notices, offline replay |
| GET | `/api/ops/export/<allocation\|overflow\|tasks\|dispatch>.<csv\|json>`, `/api/ops/briefs` | Exports and all-briefs bundle |

## Repository Structure

```text
Solarix/
├── app.py                       # HTTP server and API routes
├── data/                        # Source dengue dataset
├── artifacts/                   # Trained models, metrics and forecasts
├── src/dengue_watch/             # Features, training, evaluation and assistant
├── src/dengue_watch/ops/          # Phase 2: allocation, overflow, simulator, dispatch, roles
├── web/ops/                       # Phase 2 operations pages (admin, commissioner, team, hospital)
├── scripts/                     # Training and forecast scripts
├── web/                         # Dashboard frontend
├── docs/screenshots/             # README dashboard screenshots
├── docs/OFFLINE.md, docs/QA_CHEATSHEET.md  # Phase 2 math defense and Q&A prep
├── exports/                      # Phase 2 sample SMS / WhatsApp / printable briefs
├── tests/                        # Automated tests
├── ARCHITECTURE.md               # System and model architecture
├── plan.md                       # Project plan
├── requirements.txt
└── pyproject.toml
```

## Limitations

- The dataset may be simulated and has not been independently validated against official surveillance data.
- Ward coordinates, geographic boundaries, and population denominators are unavailable; the map is therefore schematic and incidence rates cannot be calculated.
- Risk bands are fixed thresholds on predicted case counts, not calibrated probabilities.
- Feature importance and what-if controls indicate associations, not causal effects.
- The deployed models are refit on all available years. Historical in-app predictions should not be confused with the held-out test results.
- Forecast uncertainty and accuracy deteriorate at longer horizons.

## Future Work

- Validate and retrain with verified, regularly updated surveillance data.
- Integrate operational weather forecasts and ward-level geographic boundaries.
- Add population-normalized incidence estimates.
- Add calibrated outbreak probabilities and ward-level explanations.
- Introduce scheduled retraining, model monitoring, and configurable notifications.

## Responsible Use

Dengue Watch provides exploratory forecasts and general educational information. It does not diagnose dengue, replace medical advice, or issue official public-health alerts. Any public deployment should include validation by epidemiologists and review of health guidance and hotline information by qualified professionals.

---

## Acknowledgement

This project was developed with AI-assisted support for planning, code review, and documentation. The team is responsible for reviewing the implementation and reported results.

