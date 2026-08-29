# PineTester

**Backtest TradingView Pine v5 (subset) strategies against real Binance history — in your browser.**

Paste a Pine strategy, pick a pair / timeframe / date range, hit **Run**, and get win rate,
profit factor, drawdown, Sharpe, an interactive candlestick chart with trade markers, an
equity curve vs buy & hold, a monthly-returns heatmap, a full trade list, a **parameter
optimizer**, and a **multi-pair comparison** — all from OHLCV pulled straight from
<https://data.binance.vision/>.

![CI](https://github.com/snakeneo482/PineTester/actions/workflows/ci.yml/badge.svg)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.12-blue)

---

## Run it locally

```bash
git clone https://github.com/snakeneo482/PineTester
cd PineTester
pip install -r requirements.txt
python run.py
# open http://localhost:8000
```

The first run for a given symbol+timeframe downloads monthly kline archives and caches
them under `./data/` as gzipped CSV. Subsequent runs are instant.

`python selftest.py` runs the engine on synthetic data with no network — handy for hacking
on the interpreter.

## Deploy to Vercel

The repo is Vercel-ready (`vercel.json` + `api/index.py`). Import the GitHub repo in Vercel
and deploy — no configuration needed. Because serverless functions are ephemeral and
time-limited:

- The data cache lives in `/tmp` and only survives while an instance stays warm.
- Runs are capped (`PINETESTER_MAX_BARS`, default 60k bars) — prefer `1h`/`4h`/`1d` over
  long `1m` ranges. Heavy sweeps are better run locally.
- `maxDuration` is set to 60s.

## Features

| | |
|---|---|
| **Data** | spot + USD-M futures, ~27 top USDT pairs, `1m`–`1d` |
| **Chart** | candlesticks, entry/exit markers, `plot()` overlays, volume |
| **Equity** | strategy equity vs buy & hold, drawdown curve |
| **Stats** | net P/L, win rate, profit factor, expectancy, Sharpe, Sortino, Calmar, CAGR, max drawdown, exposure, payoff, Kelly, consecutive win/loss streaks, MAE/MFE, commission — ~30 metrics |
| **Trades** | sortable table, cumulative P/L, CSV export |
| **Monthly** | year × month returns heatmap with yearly totals |
| **Optimize** | grid-search 1–2 inputs, heatmap of any metric, click a cell to apply |
| **Compare** | run the same strategy across many pairs, ranked table |
| **Inputs** | `input.*` calls become editable fields — tweak and re-run without editing code |
| **UX** | strategy presets, date-range chips, capital chips ($1k–$1M), `Ctrl`/`Cmd`+`Enter`, settings persisted locally |

## Pine coverage

**Language:** `//@version=5`, `strategy(...)`, `var`/`varip`, `:=`, `if/else`, `for`,
`while`, `switch`, ternary, user functions (`f(x) => ...`), tuple unpack (`[a,b] = ...`),
series history (`close[1]`, and `f(...)[1]` for stateful calls).

**Indicators (`ta.*`):** sma, ema, rma, wma, vwma, hma, stdev, variance, dev, highest,
lowest, change, mom, roc, cum, sum, rsi, tr, atr, crossover, crossunder, cross, macd, bb,
barssince, valuewhen, rising, falling, pivothigh, pivotlow, linreg, cci, stoch, wpr, cmo,
tsi, percentrank, median, supertrend, sar.

**Broker (`strategy.*`):** entry, order, exit (stop / limit / profit / loss / trailing),
close, close_all, cancel_all; reads `position_size`, `position_avg_price`, `equity`,
`netprofit`, `opentrades`, `closedtrades`, `wintrades`, `losstrades`. Honours
`initial_capital`, `default_qty_type` (`percent_of_equity` / `cash` / `fixed`),
`commission_type`/`commission_value`, `slippage`, `pyramiding`,
`process_orders_on_close`. UI fields override `strategy()` args.

**Execution model:** market orders fill at the **next bar open** (or the current close with
`process_orders_on_close=true`); protective stop/limit exits are checked intrabar against
each bar's high/low. Cash accounting with implicit leverage. No look-ahead.

### Known limits

- `plot*` beyond `plot()`, `label.*`, `line.*`, `alertcondition`, drawings — parsed and ignored.
- `request.security` / MTF, arrays / matrices / maps, `type` objects, and many niche
  built-ins are not implemented; unknown calls return `na` and are listed under **warnings**.
- A stateful `ta.*` call inside a conditionally-executed branch or reused across call sites
  may drift from TradingView — call them unconditionally.
- Numbers won't match TradingView to the cent; behaviour and edge are representative.

## Project layout

```
api/index.py           Vercel ASGI entrypoint
backend/
  data.py              Binance Vision downloader + CSV cache
  stats.py             performance metrics
  optimizer.py         grid-search optimizer
  app.py               FastAPI endpoints
  pine/
    lexer.py           indentation-aware tokenizer
    parser.py          recursive-descent -> dict AST
    interp.py          bar-by-bar interpreter
    builtins.py        ta.* / math.* implementations
    broker.py          strategy.* order/position engine
    runner.py          parse -> run -> results JSON
frontend/              single-page UI (CodeMirror + lightweight-charts + Chart.js)
selftest.py            offline engine test
```

## Disclaimer

For research and education only. Backtest results are not indicative of future performance.
Nothing here is financial advice. Not affiliated with TradingView or Binance.

## License

MIT — see [LICENSE](LICENSE).
