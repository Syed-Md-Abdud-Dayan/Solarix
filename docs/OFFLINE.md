# Offline resilience and math defense (1 page)

**Claim:** every forecast, allocation, overflow route, what-if simulation and dispatch notice is
computed on the local machine from local files. Wi-Fi, DNS, LLM APIs and SMS gateways can all be
down and the system still works. Live SMS/WhatsApp delivery is the only optional online feature;
when it is unavailable, notices are kept in the outbox, shown in-app and written to `exports/runtime/`.

## What runs where

| Step | Inputs (all local) | Deterministic? | If something fails |
|---|---|---|---|
| Forecast | CSV + 13 `joblib` models | yes (fixed trees) | per-horizon fallback: `0.6 x same-week-of-year mean + 0.4 x mean(last 4 weeks)`, flagged `"source": "fallback"` |
| Allocation | forecast + `config.py` + sliders | yes (ties by ward_id) | n/a (pure arithmetic) |
| Overflow | bed demand + capacity (SQLite) | yes (ties by ward_id) | default assumed capacity if DB is empty |
| Simulator | same horizon models, perturbed inputs | yes | fallback efficacy curve on the seasonal baseline |
| Dispatch | string templates (EN/BN) | yes (stable `dispatch_id` hash) | HTML brief if `reportlab` is missing |
| Notifications | SQLite outbox | yes | stay `queued`; in-app delivery always works |

## The formulas

1. **Supply rule (verified on all 31,320 rows):** `saline = round_half_up(2.385 x cases)`,
   `kits = round_half_up(1.164 x cases)`, `beds = round_half_up(0.298 x cases)`.
2. **Priority:** `w_risk x (cases + 0.5) x (density / median)^0.5`, w = 4/3/2/1 for Critical/High/Medium/Low.
3. **Stock:** `available = floor(full_stock x slider%)`, full_stock = peak-week demand of the next 4 weeks.
4. **Allocation:** equity floor (Critical 60%, High 40% of own demand), then greedy fill by priority.
   *Optimality:* maximise `sum priority_w x units_w` subject to `sum units <= stock`, `units_w <= demand_w`.
   All units cost the same, so this is a fractional knapsack: sorting by value per unit (= priority) is optimal.
   Monotone: more stock never gives any ward less (tested 30% to 100% in 5% steps).
5. **Deficit flags:** fulfilment = min over supplies of allocated / required; < 100% WARNING, < 60% CRITICAL.
6. **Crews:** `need = min(4, ceil(base_risk x density_factor))`, base 3/2/1/0; assigned in strict risk order.
7. **Overflow:** deficit = max(0, demand - (capacity - occupied)); each surplus patient goes to the
   same-city ward with the lowest post-transfer utilisation (water-filling). Conservation:
   sent = received. A city with no headroom raises CITY SURGE (no cross-city routing, by design and test).
8. **Simulator:** `coverage = 1 - exp(-0.6 x crews / density_factor)` (diminishing returns);
   rain x (1 - 0.6 coverage), case history x (1 - 0.4 coverage) for the ward's last 4 weeks;
   re-run h = 2, 3, 4 models; prevented = baseline - counterfactual, clipped >= 0 and made
   non-decreasing in crews (isotonic guard against tree-step noise). ROI = prevented / crews.
   Recommendation = greedy by marginal cases prevented per extra crew.

## Why these choices

- **Greedy, not an LP solver:** the problem is separable per supply with unit costs, so greedy is
  exactly optimal, needs no solver dependency, is instant (<0.1 s for 60 wards) and is easy to explain.
- **Equity floor:** pure greedy can starve a High ward in favour of a huge Critical one; the floor
  guarantees every Critical / High ward something before anyone is topped up.
- **Same-city routing only:** ambulance time and city health-administration boundaries (brief requirement).
- **Model-driven simulator:** the effect comes from the trained models' learned lag structure,
  so it differs by ward, horizon and crew count. The efficacy constants are planning parameters
  and are clearly labelled as assumptions.

## How to prove it live (kill-switch)

1. `python -m pytest tests/test_offline.py -q` blocks `socket.connect`, `create_connection` and DNS, then runs
   forecast -> allocation -> overflow -> simulate -> dispatch -> task generation -> outbox and asserts zero network attempts.
2. `GET /api/ops/health` returns `offline_capable: true`, `external_calls: []`, `llm_used: false`.
3. In the UI: turn Wi-Fi off (or tick "Offline kill-switch demo" in the sidebar). Pages keep showing
   the last synced plan with an "Offline mode" banner; team status changes queue and replay on reconnect.
4. Admin > Settings > "Model kill-switch": every engine switches to the seasonal fallback forecast
   and keeps working; outputs are labelled "fallback".
5. `grep -rE "(src|href)=\"https?://" web/` returns nothing: no CDN, fonts are self-hosted.
