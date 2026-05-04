# yeehee — Personal XAU/USD Signal Platform

Multi-agent AI signal engine untuk XAU/USD dengan analisis institusional-grade. Zero-cost stack.

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env             # isi opsional
streamlit run dashboard/app.py
```

## Arsitektur

- **`data/`** — Fetcher: yfinance (XAU/DXY/yields), ForexFactory calendar, CFTC COT
- **`features/`** — Technical, SMC (liquidity/FVG/OB), regime, session, intermarket
- **`strategies/`** — Scalper (M5), Intraday (M15-H1), Swing (H4-D1)
- **`ai_agent/`** — 4-agent debate (Technical/Macro/OrderFlow/DevilsAdvocate)
- **`risk/`** — Lot sizing, Kelly fractional, news blackout
- **`backtest/`** — Bar-by-bar engine + 100k Monte Carlo + walk-forward
- **`dashboard/`** — Streamlit live signals + backtest viewer + risk calc

## Realistic targets

- Win rate 55–65% (institutional-grade, bukan janji 90%+)
- R:R 1.5–2.5
- Max DD target <15%
- Backtest selalu out-of-sample + walk-forward + Monte Carlo

## Disclaimer

Tools ini buat keperluan pribadi, bukan financial advice. Trading XAU berisiko tinggi. Past performance ≠ future result.
