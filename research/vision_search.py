"""Fast parameter search for the VisionTrade AI APEX engine.

Uses the vectorised engine (research/apex_engine.py) to rank configs across
BTC/ETH/SOL with an in-sample / out-of-sample split, then the top picks are
re-verified through the real Pine interpreter (research/verify.py).

Usage:  python -m research.vision_search 4h
        python -m research.vision_search 1h
"""
from __future__ import annotations
import itertools
import json
import os
import sys
import time

from backend import data
from research.apex_engine import backtest, metrics, DEFAULTS

ROOT = os.path.dirname(os.path.dirname(__file__))
CAPITAL = 10_000.0
OOS_FRAC = 0.35
MIN_TRADES = 20

PROFILES = {
    "4h": dict(
        tf="4h", start="2022-01-01", end="2026-08-01",
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        grid=dict(
            tradeDir=["Both", "Long"],
            minScore=[52, 60, 68, 76],
            stop=[("wide", 2.0), ("mech", 1.3), ("mech", 1.8), ("mech", 2.6)],
            exitMode=["Take-profit + stop", "ATR trail", "Opposite signal"],
            tpR=[3.0, 5.0],
            htfMult=[6],
            cooldown=[3],
        ),
    ),
    "1h": dict(
        tf="1h", start="2023-06-01", end="2026-08-01",
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        grid=dict(
            tradeDir=["Both", "Long"],
            minScore=[48, 56, 64, 72],
            stop=[("mech", 1.0), ("mech", 1.5), ("mech", 2.2), ("wide", 2.0)],
            exitMode=["Take-profit + stop", "ATR trail", "Time stop"],
            tpR=[2.0, 3.5],
            htfMult=[4],
            cooldown=[2],
        ),
    ),
}


def seg(equity, trades, t_split):
    e = equity
    tr = trades
    if len(e) < 5:
        return dict(ret=0, dd=0, pf=0, trades=0, win=0)
    ret = (e[-1] / e[0] - 1) * 100 if e[0] else 0
    peak, dd = -1e18, 0.0
    for x in e:
        peak = max(peak, x)
        if peak > 0:
            dd = max(dd, (peak - x) / peak * 100)
    gp = sum(t["pnl"] for t in tr if t["pnl"] > 0)
    gl = sum(t["pnl"] for t in tr if t["pnl"] < 0)
    w = sum(1 for t in tr if t["pnl"] > 0)
    return dict(ret=ret, dd=dd, pf=(gp / -gl if gl else (9.9 if gp else 0)),
                trades=len(tr), win=(w / len(tr) * 100 if tr else 0))


def evaluate(dfs, tf, params):
    per = {}
    for sym, df in dfs.items():
        eq, tr, T, C = backtest(df, params, CAPITAL)
        n = len(eq)
        si = int(n * (1 - OOS_FRAC))
        tsp = int(T[si])
        is_tr = [t for t in tr if t["t_in"] < tsp]
        oos_tr = [t for t in tr if t["t_in"] >= tsp]
        per[sym] = dict(
            full=seg(eq, tr, tsp),
            is_=seg(eq[:si + 1], is_tr, tsp),
            oos=seg(eq[si:], oos_tr, tsp),
            bh=(C[-1] / C[0] - 1) * 100,
        )
    return per


def score(per):
    oos = [p["oos"]["ret"] for p in per.values()]
    isr = [p["is_"]["ret"] for p in per.values()]
    dd = [p["oos"]["dd"] for p in per.values()]
    tot = sum(p["full"]["trades"] for p in per.values())
    if tot < MIN_TRADES:
        return -1e9
    mean_oos = sum(oos) / 3
    worst = min(oos)
    mean_dd = sum(dd) / 3
    consist = 1.0 if all(r > 0 for r in isr) and all(r > 0 for r in oos) else 0.65
    return (0.6 * mean_oos + 0.7 * worst - 0.35 * mean_dd) * consist


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "4h"
    prof = PROFILES[tf]
    print(f"loading {prof['symbols']} {prof['tf']} {prof['start']}..{prof['end']}", flush=True)
    dfs = {s: data.load_klines("spot", s, prof["tf"], prof["start"], prof["end"],
                               log=lambda *a: None) for s in prof["symbols"]}
    for s, d in dfs.items():
        print(f"  {s}: {len(d)} bars", flush=True)

    keys = list(prof["grid"])
    combos = list(itertools.product(*prof["grid"].values()))
    print(f"{len(combos)} combos x 3 symbols", flush=True)

    rows = []
    t0 = time.time()
    for i, vals in enumerate(combos):
        d = dict(zip(keys, vals))
        p = dict(DEFAULTS)
        p.update(tradeDir=d["tradeDir"], minScore=d["minScore"], exitMode=d["exitMode"],
                 tpR=d["tpR"], htfMult=d["htfMult"], cooldown=d["cooldown"])
        p["useWide"] = d["stop"][0] == "wide"
        p["slMult"] = d["stop"][1]
        per = evaluate(dfs, prof["tf"], p)
        sc = score(per)
        rows.append(dict(params={k: (v if not isinstance(v, tuple) else list(v)) for k, v in d.items()},
                         pine_params=dict(tradeDir=d["tradeDir"], minScore=d["minScore"],
                                          exitMode=d["exitMode"], tpR=d["tpR"], htfMult=d["htfMult"],
                                          cooldown=d["cooldown"],
                                          useWide="true" if p["useWide"] else "false",
                                          slMult=p["slMult"]),
                         score=sc, per=per,
                         mean_full=sum(x["full"]["ret"] for x in per.values()) / 3,
                         mean_dd=sum(x["full"]["dd"] for x in per.values()) / 3))
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(combos)}  {time.time()-t0:.0f}s", flush=True)

    rows.sort(key=lambda r: r["score"], reverse=True)
    json.dump(rows, open(os.path.join(ROOT, "research", f"grid_{tf}.json"), "w"), indent=1)

    def line(r):
        p = r["params"]
        return (f"score={r['score']:7.1f}  OOSµ={sum(x['oos']['ret'] for x in r['per'].values())/3:7.1f}  "
                f"fullµ={r['mean_full']:8.1f}  DDµ={r['mean_dd']:5.1f}  "
                f"tr={sum(x['full']['trades'] for x in r['per'].values()):4d}  "
                f"dir={p['tradeDir']:4} score>={p['minScore']} stop={p['stop']} exit={p['exitMode'][:4]} tpR={p['tpR']}")

    print(f"\n=== {tf}  TOP 12 by robust OOS score ===", flush=True)
    for r in rows[:12]:
        print(" ", line(r), flush=True)
    print(f"\n=== {tf}  TOP 8 by raw mean return ===", flush=True)
    for r in sorted(rows, key=lambda r: r["mean_full"], reverse=True)[:8]:
        print(" ", line(r), flush=True)

    bh = {s: (dfs[s]["close"].iloc[-1] / dfs[s]["close"].iloc[0] - 1) * 100 for s in dfs}
    print(f"\nbuy & hold: " + "  ".join(f"{s} {v:.0f}%" for s, v in bh.items()), flush=True)


if __name__ == "__main__":
    main()
