"""Re-run a config through the REAL Pine interpreter (the app engine) to get
trustworthy numbers for the shortlisted parameter sets.

Usage:
    python -m research.verify 4h            # verify top picks from grid_4h.json
    python -m research.verify 4h 0 3 7      # verify specific ranks
"""
from __future__ import annotations
import json
import os
import sys

from backend import data
from backend.pine import run_backtest

ROOT = os.path.dirname(os.path.dirname(__file__))
CODE = open(os.path.join(ROOT, "strategies", "VisionTradeAI_APEX_Strategy.pine"),
            encoding="utf-8").read()

WINDOWS = {
    "4h": ("2021-01-01", "2026-08-01"),
    "1h": ("2023-01-01", "2026-08-01"),
}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def verify(tf, pine_params, capital=10_000):
    start, end = WINDOWS[tf]
    rows = []
    agg = dict(ret=[], dd=[], pf=[], tr=[], win=[], sharpe=[], bh=[])
    for sym in SYMBOLS:
        df = data.load_klines("spot", sym, tf, start, end, log=lambda *a: None)
        ov = {k: str(v) for k, v in pine_params.items()}
        r = run_backtest(CODE, df, tf, initial_capital=capital, overrides=ov)
        s = r["stats"]
        rows.append((sym, s))
        agg["ret"].append(s["net_profit_pct"])
        agg["dd"].append(s["max_drawdown_pct"])
        agg["pf"].append(s["profit_factor"])
        agg["tr"].append(s["total_trades"])
        agg["win"].append(s["win_rate"])
        agg["sharpe"].append(s["sharpe"])
        agg["bh"].append(s["buy_hold_pct"])
    return rows, agg


def _print(tf, rank, pine_params, rows, agg):
    mean = lambda x: sum(x) / len(x)
    print(f"\n#{rank}  {pine_params}")
    print(f"   {'sym':8} {'net%':>9} {'B&H%':>8} {'win%':>6} {'PF':>5} {'maxDD%':>7} {'Sharpe':>7} {'trades':>6}")
    for sym, s in rows:
        print(f"   {sym:8} {s['net_profit_pct']:>9.1f} {s['buy_hold_pct']:>8.0f} "
              f"{s['win_rate']:>6.1f} {s['profit_factor']:>5.2f} {s['max_drawdown_pct']:>7.1f} "
              f"{s['sharpe']:>7.2f} {s['total_trades']:>6}")
    print(f"   {'MEAN':8} {mean(agg['ret']):>9.1f} {mean(agg['bh']):>8.0f} "
          f"{mean(agg['win']):>6.1f} {mean(agg['pf']):>5.2f} {mean(agg['dd']):>7.1f} "
          f"{mean(agg['sharpe']):>7.2f} {sum(agg['tr']):>6}")


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "4h"
    ranks = [int(x) for x in sys.argv[2:]] or list(range(6))
    grid = json.load(open(os.path.join(ROOT, "research", f"grid_{tf}.json")))
    results = []
    for rk in ranks:
        pp = grid[rk]["pine_params"]
        rows, agg = verify(tf, pp)
        _print(tf, rk, pp, rows, agg)
        mean = lambda x: sum(x) / len(x)
        results.append(dict(rank=rk, pine_params=pp,
                            mean_ret=mean(agg["ret"]), mean_dd=mean(agg["dd"]),
                            mean_sharpe=mean(agg["sharpe"]), total_trades=sum(agg["tr"]),
                            per=[(s, st["net_profit_pct"], st["max_drawdown_pct"],
                                  st["profit_factor"], st["total_trades"], st["win_rate"],
                                  st["buy_hold_pct"]) for s, st in rows]))
    json.dump(results, open(os.path.join(ROOT, "research", f"verified_{tf}.json"), "w"), indent=1)
    print(f"\nwrote research/verified_{tf}.json")


if __name__ == "__main__":
    main()
