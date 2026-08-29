"""Offline smoke test: synthetic random-walk data, no network. Run: python selftest.py"""
import re
import numpy as np
import pandas as pd

from backend.pine import run_backtest
from backend.pine.parser import parse

np.random.seed(1)
n = 6000
px = 20000 + np.cumsum(np.random.randn(n) * 40)
open_ = np.r_[px[0], px[:-1]]
high = np.maximum(open_, px) + np.random.rand(n) * 20
low = np.minimum(open_, px) - np.random.rand(n) * 20
df = pd.DataFrame({
    "open_time": 1_600_000_000_000 + np.arange(n) * 3600_000,
    "open": open_, "high": high, "low": low, "close": px,
    "volume": np.random.rand(n) * 10,
})

# every bundled preset must at least parse
presets = re.findall(r"`([^`]*)`", open("frontend/presets.js", encoding="utf-8").read())
for i, code in enumerate(presets):
    parse(code)
print(f"parsed {len(presets)} presets OK")

CODE = presets[0]  # EMA crossover
res = run_backtest(CODE, df, "1h", initial_capital=10000)
s = res["stats"]
assert s["total_trades"] > 0
assert res["equity"] and res["candles"] and res["markers"]
assert not res["warnings"], res["warnings"]
print("trades:", s["total_trades"], "win%:", round(s["win_rate"], 1),
      "net:", round(s["net_profit"], 2), "PF:", round(s["profit_factor"], 2),
      "sharpe:", round(s["sharpe"], 2), "maxDD%:", round(s["max_drawdown_pct"], 1))

res2 = run_backtest(CODE, df, "1h", initial_capital=10000,
                    overrides={"fastLen": "10", "slowLen": "30"})
assert res2["stats"]["total_trades"] != s["total_trades"]
print("override changed trade count:", res2["stats"]["total_trades"])

# indicator-heavy script exercising many builtins + history-of-call
BIG = """//@version=5
strategy("kitchen sink", initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=50)
r = ta.rsi(close, 14)
[m, sg, h] = ta.macd(close, 12, 26, 9)
[st, dir] = ta.supertrend(3, 10)
k = ta.stoch(close, high, low, 14)
hh = ta.highest(high, 20)[1]
a = ta.atr(14)
cc = ta.cci(close, 20)
sar = ta.sar(0.02, 0.02, 0.2)
if ta.crossover(close, hh) and dir < 0
    strategy.entry("L", strategy.long)
strategy.exit("x", "L", stop=close - 2*a, profit=300)
if r > 75
    strategy.close("L")
"""
res3 = run_backtest(BIG, df, "1h", initial_capital=10000)
assert not res3["warnings"], res3["warnings"]
print("kitchen-sink trades:", res3["stats"]["total_trades"])
print("OK")
