"""Performance statistics from an equity curve + closed trade list."""
from __future__ import annotations
import datetime as dt
import math

TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400,
}
YEAR = 365.25 * 86400


def _div(a, b):
    return a / b if b else 0.0


def _streaks(trades):
    mw = ml = cw = cl = 0
    for t in trades:
        if t["pnl"] > 0:
            cw += 1
            cl = 0
        elif t["pnl"] < 0:
            cl += 1
            cw = 0
        mw = max(mw, cw)
        ml = max(ml, cl)
    return mw, ml


def drawdown_curve(equity):
    peak = -1e18
    out = []
    for e in equity:
        peak = max(peak, e)
        out.append(_div(e - peak, peak) * 100 if peak > 0 else 0.0)
    return out


def compute(equity, trades, closes, times, tf, initial_capital, bars_in_market=0):
    bars = len(equity)
    bps = YEAR / TF_SECONDS.get(tf, 3600)
    years = _div(bars, bps)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = sum(t["pnl"] for t in losses)
    net = sum(t["pnl"] for t in trades)
    n = len(trades)

    peak = -1e18
    max_dd = max_dd_pct = 0.0
    trough = 1e18
    max_ru = 0.0
    for e in equity:
        peak = max(peak, e)
        dd = peak - e
        max_dd = max(max_dd, dd)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, dd / peak)
        trough = min(trough, e)
        max_ru = max(max_ru, e - trough)

    rets = [(equity[i] - equity[i - 1]) / equity[i - 1]
            for i in range(1, len(equity)) if equity[i - 1]]
    sharpe = sortino = vol = 0.0
    if len(rets) > 2:
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))
        dn = [r for r in rets if r < 0]
        dsd = math.sqrt(sum(r * r for r in dn) / len(dn)) if dn else 0.0
        vol = sd * math.sqrt(bps) * 100
        if sd:
            sharpe = mean / sd * math.sqrt(bps)
        if dsd:
            sortino = mean / dsd * math.sqrt(bps)

    final_eq = equity[-1] if equity else initial_capital
    cagr = ((final_eq / initial_capital) ** (1 / years) - 1) if years > 0 and final_eq > 0 else 0.0
    bh = _div(closes[-1] - closes[0], closes[0]) * 100 if len(closes) > 1 else 0.0

    avg_win = _div(gross_profit, len(wins))
    avg_loss = _div(gross_loss, len(losses))
    win_rate = _div(len(wins), n)
    mw, ml = _streaks(trades)
    pf = _div(gross_profit, -gross_loss)
    payoff = _div(avg_win, -avg_loss)
    kelly = (win_rate - (1 - win_rate) / payoff) if payoff else 0.0

    monthly = monthly_returns(equity, times)
    mret = [m["return_pct"] for m in monthly]

    return {
        "net_profit": net,
        "net_profit_pct": _div(net, initial_capital) * 100,
        "final_equity": final_eq,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": pf,
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": win_rate * 100,
        "avg_trade": _div(net, n),
        "avg_trade_pct": _div(sum(t["pnl_pct"] for t in trades), n),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff,
        "win_loss_ratio": payoff,
        "kelly_pct": kelly * 100,
        "largest_win": max((t["pnl"] for t in trades), default=0.0),
        "largest_loss": min((t["pnl"] for t in trades), default=0.0),
        "avg_bars_in_trade": _div(sum(t["bars"] for t in trades), n),
        "max_consec_wins": mw,
        "max_consec_losses": ml,
        "expectancy": _div(net, n),
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct * 100,
        "max_runup": max_ru,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": _div(cagr * 100, max_dd_pct * 100),
        "recovery_factor": _div(net, max_dd),
        "volatility_pct": vol,
        "cagr_pct": cagr * 100,
        "buy_hold_pct": bh,
        "exposure_pct": _div(bars_in_market, bars) * 100,
        "best_month_pct": max(mret) if mret else 0.0,
        "worst_month_pct": min(mret) if mret else 0.0,
        "positive_months_pct": _div(sum(1 for r in mret if r > 0), len(mret)) * 100,
        "commission_paid": 0.0,
        "years": years,
        "bars": bars,
        "_monthly": monthly,
    }


def monthly_returns(equity, times):
    if not times:
        return []
    buckets = {}
    for e, t in zip(equity, times):
        d = dt.datetime.utcfromtimestamp(t / 1000)
        key = (d.year, d.month)
        b = buckets.setdefault(key, [e, e])
        b[1] = e
    out = []
    for (y, m) in sorted(buckets):
        a, z = buckets[(y, m)]
        out.append({"year": y, "month": m, "label": f"{y}-{m:02d}",
                    "return_pct": _div(z - a, a) * 100})
    return out
