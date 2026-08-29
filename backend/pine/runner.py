"""Glue: parse Pine source, run the interpreter over OHLCV, build results JSON."""
from __future__ import annotations

from .parser import parse
from .interp import Context


def _apply_overrides(b, initial_capital, qty_type, qty_value, commission_pct, slippage):
    if initial_capital:
        b.cfg["initial_capital"] = float(initial_capital)
        if not b.trades and not b.lots:
            b.cash = b.cfg["initial_capital"]
    if qty_type:
        b.cfg["qty_type"] = qty_type
    if qty_value is not None:
        b.cfg["qty_value"] = float(qty_value)
    if commission_pct is not None:
        b.cfg["commission_type"] = "percent"
        b.cfg["commission_value"] = float(commission_pct)
    if slippage is not None:
        b.cfg["slippage"] = float(slippage)


def run_core(program, df, tf, *, initial_capital=None, qty_type=None, qty_value=None,
             commission_pct=None, slippage=None, mintick=0.01, overrides=None,
             progress=None):
    O = df["open"].astype(float).tolist()
    H = df["high"].astype(float).tolist()
    L = df["low"].astype(float).tolist()
    C = df["close"].astype(float).tolist()
    V = df["volume"].astype(float).tolist()
    T = df["open_time"].astype("int64").tolist()

    ctx = Context(O, H, L, C, V, T, mintick=mintick)
    ctx.param_overrides = overrides or {}
    b = ctx.broker
    _apply_overrides(b, initial_capital, qty_type, qty_value, commission_pct, slippage)

    _orig = b.configure

    def configure(kw, pos):
        _orig(kw, pos)
        _apply_overrides(b, initial_capital, qty_type, qty_value, commission_pct, slippage)

    b.configure = configure
    equity = ctx.run(program, progress=progress)
    return ctx, equity, (O, H, L, C, V, T)


def _agg_candles(O, H, L, C, V, T, target=3000):
    n = len(C)
    if n <= target:
        return [{"time": T[i] // 1000, "open": O[i], "high": H[i], "low": L[i],
                 "close": C[i]} for i in range(n)], \
               [{"time": T[i] // 1000, "value": V[i]} for i in range(n)]
    step = n // target + 1
    cnd, vol = [], []
    for s in range(0, n, step):
        e = min(s + step, n)
        cnd.append({"time": T[s] // 1000, "open": O[s], "high": max(H[s:e]),
                    "low": min(L[s:e]), "close": C[e - 1]})
        vol.append({"time": T[s] // 1000, "value": sum(V[s:e])})
    return cnd, vol


def run_backtest(code, df, tf, *, initial_capital=None, qty_type=None, qty_value=None,
                 commission_pct=None, slippage=None, mintick=0.01, overrides=None,
                 progress=None):
    from .. import stats as stats_mod

    program = parse(code)
    ctx, equity, (O, H, L, C, V, T) = run_core(
        program, df, tf, initial_capital=initial_capital, qty_type=qty_type,
        qty_value=qty_value, commission_pct=commission_pct, slippage=slippage,
        mintick=mintick, overrides=overrides, progress=progress)
    b = ctx.broker
    trades = b.trades

    st = stats_mod.compute(equity, trades, C, T, tf, b.cfg["initial_capital"],
                           bars_in_market=b.bars_in_market)
    st["commission_paid"] = b.commission_paid
    monthly = st.pop("_monthly")

    dd = stats_mod.drawdown_curve(equity)
    init = b.cfg["initial_capital"]
    bh0 = C[0]
    step = max(1, len(equity) // 3000)
    eq_pts = []
    for i in range(0, len(equity), step):
        eq_pts.append({"t": T[i] // 1000, "equity": equity[i], "dd": dd[i],
                       "bh": init * C[i] / bh0})
    if eq_pts and eq_pts[-1]["t"] != T[-1] // 1000:
        eq_pts.append({"t": T[-1] // 1000, "equity": equity[-1], "dd": dd[-1],
                       "bh": init * C[-1] / bh0})

    candles, vol = _agg_candles(O, H, L, C, V, T)
    markers = []
    for tr in trades:
        markers.append({"time": tr["entry_time"] // 1000,
                        "position": "belowBar" if tr["dir"] > 0 else "aboveBar",
                        "color": "#3fb950" if tr["dir"] > 0 else "#f85149",
                        "shape": "arrowUp" if tr["dir"] > 0 else "arrowDown",
                        "text": ("L" if tr["dir"] > 0 else "S")})
        markers.append({"time": tr["exit_time"] // 1000,
                        "position": "aboveBar" if tr["dir"] > 0 else "belowBar",
                        "color": "#8b949e", "shape": "circle",
                        "text": f'{tr["pnl_pct"]:+.1f}%'})
    markers.sort(key=lambda m: m["time"])
    # dedupe identical timestamps (lightweight-charts requires unique asc times)
    seen = set()
    umark = []
    for m in markers:
        if m["time"] in seen:
            continue
        seen.add(m["time"])
        umark.append(m)

    plots = []
    for p in ctx.plots.values():
        d = p["data"]
        pts = [{"time": T[i] // 1000, "value": d[i]}
               for i in range(0, len(d), step) if d[i] is not None]
        if pts:
            plots.append({"title": p["title"], "data": pts})

    trade_rows = [{
        "n": i + 1, "id": t["id"], "side": "long" if t["dir"] > 0 else "short",
        "entry_time": t["entry_time"], "exit_time": t["exit_time"],
        "entry_price": t["entry_price"], "exit_price": t["exit_price"],
        "qty": t["qty"], "bars": t["bars"], "pnl": t["pnl"], "pnl_pct": t["pnl_pct"],
        "reason": t["reason"], "mae": t["mae"], "mfe": t["mfe"],
        "cum_pnl": 0.0,
    } for i, t in enumerate(trades)]
    run = 0.0
    for r in trade_rows:
        run += r["pnl"]
        r["cum_pnl"] = run

    return {
        "stats": st,
        "equity": eq_pts,
        "candles": candles,
        "volume": vol,
        "markers": umark,
        "plots": plots,
        "trades": trade_rows[:5000],
        "trade_count": len(trade_rows),
        "monthly": monthly,
        "inputs": list(ctx.inputs.values()),
        "warnings": ctx.warnings,
        "config": {
            "initial_capital": b.cfg["initial_capital"],
            "qty_type": b.cfg["qty_type"],
            "qty_value": b.cfg["qty_value"],
            "commission_type": b.cfg["commission_type"],
            "commission_value": b.cfg["commission_value"],
            "slippage": b.cfg["slippage"],
            "pyramiding": b.cfg["pyramiding"],
            "process_on_close": b.cfg["process_on_close"],
        },
        "bars": len(C),
        "first_time": T[0],
        "last_time": T[-1],
    }
