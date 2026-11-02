# Action Network — Implied Chance Lab

A self-contained Streamlit research dashboard for comparing Kalshi and Polymarket election prices, inspecting their historical movements, and validating an Action Network composite probability. It uses **public read-only data** and does **not** require an API key.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Upload this whole folder to a GitHub repository (put `app.py` at the repository root, or select its path).
2. In Streamlit Community Cloud, choose **Create app** → the GitHub repository → main file `app.py` → Deploy.
3. Choose one of the election races from the sidebar.
4. In **Match contracts**, enter/find the Kalshi event ticker and corresponding Polymarket Global event slug. Select individual candidate YES contracts, inspect resolution rules, and approve the matching YES propositions. Suggestions are **not** validated mappings.
5. In **Live comparison**, click **Refresh prices & 9-day history** to fetch the selected contracts. The app displays actual observed quotes, not guessed values. Export the graphic and timestamped CSV from the interface.
6. Optional: upload matched **resolved** elections CSV to enable backtesting and possibly accuracy-adjusted weights.

The app does not persist user state after restart. Download mapping JSON / snapshot CSV in **Exports & methodology** and restore mapping JSON later. It never creates historical records automatically. A data-collection service is needed for truly long-run automatic capture.

## Data accuracy

- Market matching is manually reviewed and required. Kalshi party-winner markets can have different outcomes from Polymarket candidate-winner contracts. If no equivalent pair exists, DO NOT combine them.
- Kalshi: use bid/ask midpoint when the market is quoted with spread <= 15 percentage points; otherwise use most recent traded price where available, and identify it as such. A stale last trade should not be published without further review.
- Polymarket: uses Global Gamma discovery/markets and CLOB historical prices. **Polymarket US** has a separate API; this prototype does not claim to collect Polymarket US prices.
- Some binary YES contracts might expose no CLOB YES token or a nonbinary outcome; these cannot be mapped automatically.
- Historical 24-hour/7-day changes require actual historical observations close to the specified reference time. If the source is missing, the app shows *unavailable*.
- AN composite default = `0.5 * Kalshi + 0.5 * Polymarket` for one verified matching YES outcome. This is a transparent blend, **not** a claim of a superior forecast.
- Accuracy-adjusted weights are estimated from earlier resolved matched election outcomes at the *same snapshot horizon*; the operator must explicitly confirm that current prices are being observed at a comparable pre-election horizon before those weights are applied; Brier scores on later (held-out) elections gate whether a new weight can replace the baseline. If inadequate history or failed holdout, 50/50 is retained.
- Full historical backfill is not built in because blindly pairing resolved markets risks data leakage and settlement mismatches. Prepare a trusted matched historical dataset separately. The data requirements are below.
- The sample CSV data in the interface is **synthetic and only illustrates the schema**.

## Import resolved historical elections CSV

| Column | Meaning |
|---|---|
| `race_id` | Unique election/proposition identifier; one row per proposition per horizon |
| `election_date` | Election date in parseable ISO8601 timestamp |
| `asof_utc` | UTC timestamp at which both exchange prices were observed, before the event |
| `horizon_hours` | `24`, `168` (7 days), or `720` (30 days) |
| `kalshi_probability` | Historical YES price/quote between 0 and 1 |
| `polymarket_probability` | Historical YES price/quote between 0 and 1 |
| `outcome` | Certified or verified resolved YES result: 1 or 0 |

**Crucial:** Historical prices must be known at an equal point in time **before** the result. The app enforces snapshot-to-event time gaps of 24h ±12h, 168h ±36h, or 720h ±72h. Never enter the final settled price as a historical forecast. Do not include multiple highly correlated candidate contracts from the same underlying election under different race IDs without a sampling strategy. A minimum 30 unique elections for the chosen horizon, at least 10 later-date holdout elections, and both YES/NO outcomes are required. This is a minimum technical safeguard, not enough to guarantee statistical certainty. The selected weights are capped between 30% and 70%, shrunk toward 50%, and use a 730-day exponential historical half-life as an explicit research assumption (not a published validated constant). The holdout gate requires at least a 0.002 Brier improvement over equal-weight and no more than a 0.03 Brier gap relative to the strongest individual exchange in the holdout. These are conservative operational heuristics, not proof of predictive skill.

## Run tests

```bash
pytest -q
```

## API documentation and research

- Kalshi public market endpoints: https://docs.kalshi.com/api-reference/market/get-markets
- Kalshi market history: https://docs.kalshi.com/api-reference/market/get-market-candlesticks
- Polymarket market discovery: https://docs.polymarket.com/market-data/discover-markets
- Polymarket CLOB price history: https://institute.polymarket.com/data

## Status / limitations

This project has unit tests for parsing, weighting, safety gating, and errors. The development container had no internet DNS access to the exchanges, so API responses could not be tested live during the build. The URLs and API response field names were checked against the platforms' published docs. Expect to verify event tickers and search results after deploying, as these can change or be unavailable by jurisdiction. The research model has **not** been trained or validated on historical election records supplied by the user; no superior predictive performance is claimed.
