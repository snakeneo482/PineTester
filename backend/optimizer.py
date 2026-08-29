"""Grid-search parameter optimization over detected strategy inputs."""
from __future__ import annotations

from .pine.parser import parse
from .pine.runner import run_core
from . import stats as stats_mod

METRICS = {
    "net_profit": "Net profit $",
    "net_profit_pct": "Net profit %",
    "profit_factor": "Profit factor",
    "win_rate": "Win rate %",
    "sharpe": "Sharpe",
    "sortino": "Sortino",
    "max_drawdown_pct": "Max drawdown % (min)",
    "total_trades": "Total trades",
    "calmar": "Calmar",
}
MAX_COMBOS = 240


def _axis(spec):
    a, b, step = float(spec["start"]), float(spec["stop"]), float(spec["step"] or 1)
    if step <= 0:
        step = 1
    vals = []
    v = a
    while v <= b + 1e-9:
        vals.append(round(v, 6))
        v += step
    return vals or [a]


def optimize(code, df, tf, params, metric, base):
    if metric not in METRICS:
        metric = "net_profit"
    program = parse(code)
    params = [p for p in params if p.get("name")][:2]
    if not params:
        raise RuntimeError("pick at least one input to optimize")

    axes = [_axis(p) for p in params]
    combos = 1
    for ax in axes:
        combos *= len(ax)
    if combos > MAX_COMBOS:
        raise RuntimeError(f"{combos} combinations exceeds the {MAX_COMBOS} cap — "
                           f"widen the step or narrow the range")

    names = [p["name"] for p in params]
    a1 = axes[0]
    a2 = axes[1] if len(axes) > 1 else [None]
    rows = []
    best = None
    minimize = metric == "max_drawdown_pct"

    for v2 in a2:
        row = []
        for v1 in a1:
            ov = dict(base.get("overrides") or {})
            ov[names[0]] = v1
            if v2 is not None:
                ov[names[1]] = v2
            ctx, equity, (O, H, L, C, T, TT) = run_core(
                program, df, tf,
                initial_capital=base.get("initial_capital"),
                qty_type=base.get("qty_type"), qty_value=base.get("qty_value"),
                commission_pct=base.get("commission_pct"), slippage=base.get("slippage"),
                mintick=base.get("mintick", 0.01), overrides=ov)
            b = ctx.broker
            st = stats_mod.compute(equity, b.trades, C, TT, tf,
                                   b.cfg["initial_capital"], b.bars_in_market)
            val = st.get(metric, 0.0)
            cell = {"v1": v1, "v2": v2, "value": val,
                    "net": st["net_profit"], "trades": st["total_trades"],
                    "win_rate": st["win_rate"], "dd": st["max_drawdown_pct"]}
            row.append(cell)
            if best is None or (val < best["value"] if minimize else val > best["value"]):
                best = cell
        rows.append(row)

    return {
        "metric": metric, "metric_label": METRICS[metric],
        "params": names,
        "axis1": a1, "axis2": [x for x in a2 if x is not None],
        "grid": rows, "best": best, "combos": combos,
    }
