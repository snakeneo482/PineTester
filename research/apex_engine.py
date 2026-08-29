"""Vectorised re-implementation of the VisionTrade AI APEX v5 engine + a fast
event-driven backtest, for parameter search. Signal logic mirrors
VisionTradeAI_APEX_Strategy.pine so the winning params transfer back to Pine.

~30ms per backtest vs ~7s through the Pine interpreter.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

YEAR = 365.25 * 86400
TF_SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
          "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400}

DEFAULTS = dict(
    fastLen=8, trigLen=21, midLen=50, anchorLen=100, trendLen=200,
    htfMode="Proxy (scaled EMA)", htfMult=6,
    useRsi=True, rsiLen=14, rsiOB=72, rsiOS=28, rsiSmL=3,
    useMacd=True, macdFast=12, macdSlow=26, macdSig=9,
    useAdx=True, adxLen=14, adxSmth=14, adxFullMin=22.0, adxPartMin=18.0,
    useVol=True, volLen=20, volMult=1.15,
    useStr=True, strLen=20,
    useVlt=True, atrLen=14, atrMinPct=0.12, atrMaxPct=6.0,
    useSqz=True, sqzLen=20, bbMult=2.0, kcMult=1.5,
    minScore=72, cooldown=3, reqCross=False,
    tradeDir="Both", slMult=2.0, swBuf=0.5, useWide=True,
    exitMode="Take-profit + stop", tpR=3.0, trailR=1.5, trailAtr=2.5,
    maxBars=48, exitOpp=True,
    commission=0.0005, slip_ticks=2, mintick=0.01,
)


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _rma(s, n):
    """Wilder RMA seeded with SMA(n) — matches TradingView ta.rma / ta.atr / ta.rsi."""
    a = s.to_numpy(float)
    out = np.full(a.shape, np.nan)
    if len(a) < n:
        return pd.Series(out, index=s.index)
    out[n - 1] = np.nanmean(a[:n])
    k = 1.0 / n
    for i in range(n, len(a)):
        x = a[i]
        out[i] = out[i - 1] if np.isnan(x) else k * x + (1 - k) * out[i - 1]
    return pd.Series(out, index=s.index)


def _rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    rs = _rma(up, n) / _rma(dn, n).replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _true_range(h, l, c):
    pc = c.shift()
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def _dmi(h, l, c, n, ns):
    up = h.diff()
    dn = -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    trur = _rma(_true_range(h, l, c), n).replace(0, np.nan)
    plus = 100 * _rma(plus_dm, n) / trur
    minus = 100 * _rma(minus_dm, n) / trur
    dx = 100 * (plus - minus).abs() / (plus + minus).replace(0, np.nan)
    return plus, minus, _rma(dx.fillna(0.0), ns)


def compute_signals(df, p):
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

    fastE = _ema(c, p["fastLen"])
    trigE = _ema(c, p["trigLen"])
    midE = _ema(c, p["midLen"])
    anchE = _ema(c, p["anchorLen"])
    trendE = _ema(c, p["trendLen"])
    atr = _rma(_true_range(h, l, c), p["atrLen"])
    atrPct = atr / c * 100

    rsiRaw = _rsi(c, p["rsiLen"])
    rsiS = _ema(rsiRaw, p["rsiSmL"])

    emaF = _ema(c, p["macdFast"])
    emaSlow = _ema(c, p["macdSlow"])
    macd = emaF - emaSlow
    sigL = _ema(macd, p["macdSig"])
    hist = macd - sigL

    _, _, adx = _dmi(h, l, c, p["adxLen"], p["adxSmth"])
    volSma = c.rolling(1).mean()  # placeholder
    volSma = v.rolling(p["volLen"]).mean()

    # HTF proxy
    if p["htfMode"] == "Off":
        htfBull = pd.Series(True, index=c.index)
        htfBear = pd.Series(True, index=c.index)
    else:
        m = p["htfMult"]
        pT, pF, pS = _ema(c, p["trendLen"] * m), _ema(c, p["fastLen"] * m), _ema(c, p["trigLen"] * m)
        htfBull = (c > pT) & (pF > pS)
        htfBear = (c < pT) & (pF < pS)

    bull_pairs = ((fastE > trigE).astype(int) + (trigE > midE).astype(int)
                  + (midE > anchE).astype(int) + (anchE > trendE).astype(int))
    bear_pairs = ((fastE < trigE).astype(int) + (trigE < midE).astype(int)
                  + (midE < anchE).astype(int) + (anchE < trendE).astype(int))
    emaBullStack = bull_pairs == 4
    emaBearStack = bear_pairs == 4
    emaBullPart = bull_pairs == 3
    emaBearPart = bear_pairs == 3

    trendSlope = trendE - trendE.shift(3)
    priceBull = (c > trendE) & (trendSlope > 0)
    priceBear = (c < trendE) & (trendSlope < 0)

    anchUp = anchE > anchE.shift(3)
    anchDn = anchE < anchE.shift(3)
    anchRespBull = (c > anchE) & anchUp & (l.rolling(5).min() >= anchE - atr * 0.75)
    anchRespBear = (c < anchE) & anchDn & (h.rolling(5).max() <= anchE + atr * 0.75)

    swingHigh = h.rolling(p["strLen"]).max().shift(1)
    swingLow = l.rolling(p["strLen"]).min().shift(1)
    bosUp = (c > swingHigh) & (c.shift(1) <= swingHigh.shift(1))
    bosDown = (c < swingLow) & (c.shift(1) >= swingLow.shift(1))
    structLong = (~p["useStr"]) | bosUp | ((c > trigE) & (c > trigE.shift(1)))
    structShort = (~p["useStr"]) | bosDown | ((c < trigE) & (c < trigE.shift(1)))

    rsiLongOk = (~p["useRsi"]) | ((rsiS > 45) & (rsiS < p["rsiOB"]) & (rsiS > rsiS.shift(2)))
    rsiShortOk = (~p["useRsi"]) | ((rsiS < 55) & (rsiS > p["rsiOS"]) & (rsiS < rsiS.shift(2)))
    macdLongOk = (~p["useMacd"]) | ((macd > sigL) & (hist > hist.shift(1)) & (hist > 0))
    macdShortOk = (~p["useMacd"]) | ((macd < sigL) & (hist < hist.shift(1)) & (hist < 0))

    adxFull = adx >= p["adxFullMin"]
    adxPart = (adx >= p["adxPartMin"]) & (adx < p["adxFullMin"])
    adxOk = (~p["useAdx"]) | (adx >= p["adxPartMin"])
    volRegimeOk = (~p["useVlt"]) | ((atrPct >= p["atrMinPct"]) & (atrPct <= p["atrMaxPct"]))
    volumeOk = (~p["useVol"]) | (v > volSma * p["volMult"])

    basis = c.rolling(p["sqzLen"]).mean()
    dev = p["bbMult"] * c.rolling(p["sqzLen"]).std(ddof=0)
    kcR = _true_range(h, l, c).rolling(p["sqzLen"]).mean()
    sqOn = ((basis - dev) > (basis - p["kcMult"] * kcR)) & ((basis + dev) < (basis + p["kcMult"] * kcR))
    sqOn = sqOn & p["useSqz"]
    sqFired = sqOn.shift(1).fillna(False) & (~sqOn) & p["useSqz"]

    bearDivg = (c > c.shift(2)) & ~(rsiS > rsiS.shift(2))
    bullDivg = (c < c.shift(2)) & ~(rsiS < rsiS.shift(2))

    emaCrossUp = (fastE > trigE) & (fastE.shift(1) <= trigE.shift(1))
    emaCrossDn = (fastE < trigE) & (fastE.shift(1) >= trigE.shift(1))
    pbLong = (c > trigE) & (l <= trigE + atr * 0.30) & (c > o)
    pbShort = (c < trigE) & (h >= trigE - atr * 0.30) & (c < o)
    if p["reqCross"]:
        trigLong, trigShort = emaCrossUp, emaCrossDn
    else:
        trigLong = emaCrossUp | bosUp | pbLong | sqFired
        trigShort = emaCrossDn | bosDown | pbShort | sqFired

    tStackL = np.where(emaBullStack, 14, np.where(emaBullPart, 7, 0))
    tStackS = np.where(emaBearStack, 14, np.where(emaBearPart, 7, 0))
    tScoreL = np.where(priceBull, 12, 0) + tStackL + np.where(htfBull, 9, 0)
    tScoreS = np.where(priceBear, 12, 0) + tStackS + np.where(htfBear, 9, 0)
    adxPts = np.where(adxFull, 9, np.where(adxPart, 4, 0))
    mScoreL = np.where(rsiLongOk, 9, 0) + np.where(macdLongOk, 11, 0) + adxPts + np.where(anchRespBull, 6, 0)
    mScoreS = np.where(rsiShortOk, 9, 0) + np.where(macdShortOk, 11, 0) + adxPts + np.where(anchRespBear, 6, 0)
    sScoreL = np.where(~p["useStr"], 20, np.where(bosUp, 20, np.where(structLong, 10, 0)))
    sScoreS = np.where(~p["useStr"], 20, np.where(bosDown, 20, np.where(structShort, 10, 0)))
    volScore = np.where(~p["useVol"], 5, np.where(volumeOk, 5, 0))
    vrScore = np.where(~p["useVlt"], 5, np.where(volRegimeOk, 5, 0))
    longScore = np.minimum(tScoreL + mScoreL + sScoreL + volScore + vrScore, 100)
    shortScore = np.minimum(tScoreS + mScoreS + sScoreS + volScore + vrScore, 100)

    longSig = (trigLong & priceBull & htfBull & rsiLongOk & macdLongOk & adxOk
               & volumeOk & structLong & volRegimeOk & ~bearDivg
               & (longScore >= p["minScore"])).to_numpy()
    shortSig = (trigShort & priceBear & htfBear & rsiShortOk & macdShortOk & adxOk
                & volumeOk & structShort & volRegimeOk & ~bullDivg
                & (shortScore >= p["minScore"])).to_numpy()

    n = len(c)
    fl = np.zeros(n, bool)
    fs = np.zeros(n, bool)
    last = -10 ** 9
    cd = p["cooldown"]
    ls, ss = np.asarray(longScore), np.asarray(shortScore)
    allowL = p["tradeDir"] != "Short"
    allowS = p["tradeDir"] != "Long"
    for i in range(n):
        if i - last < cd:
            continue
        li, si = longSig[i], shortSig[i]
        if li and (not si or ls[i] > ss[i]):
            if allowL:
                fl[i] = True
            last = i
        elif si and (not li or ss[i] > ls[i]):
            if allowS:
                fs[i] = True
            last = i

    return dict(
        finalLong=fl, finalShort=fs, atr=atr.to_numpy(),
        swingHigh=swingHigh.to_numpy(), swingLow=swingLow.to_numpy(),
        longScore=ls, shortScore=ss,
    )


def backtest(df, p, capital=10_000.0):
    sig = compute_signals(df, p)
    O = df["open"].to_numpy(float)
    H = df["high"].to_numpy(float)
    L = df["low"].to_numpy(float)
    C = df["close"].to_numpy(float)
    T = df["open_time"].to_numpy("int64")
    fl, fs, atr = sig["finalLong"], sig["finalShort"], sig["atr"]
    sh, sl = sig["swingHigh"], sig["swingLow"]
    n = len(C)
    tick = p["mintick"] * p["slip_ticks"]
    fee = p["commission"]
    mode = p["exitMode"]

    equity = np.empty(n)
    cash = capital
    pos = 0
    qty = entry = stop = tp = 0.0
    ebar = 0
    peak_favor = 0.0
    pending = 0
    p_stop = p_tp = p_risk = 0.0
    trades = []

    for i in range(n):
        o, hi, lo, c = O[i], H[i], L[i], C[i]

        # fill pending entry at this bar's open
        if pending != 0 and pos == 0:
            d = pending
            px = o + tick * d
            qty = (cash / px)
            entry = px
            stop = p_stop
            risk = abs(entry - stop)
            tp = entry + risk * p["tpR"] * d
            cash -= cash * fee
            pos = d
            ebar = i
            peak_favor = 0.0
            pending = 0

        # manage open position intrabar
        if pos != 0:
            d = pos
            exit_px = None
            reason = ""
            # trailing stop update
            if mode == "ATR trail":
                fav = (hi - entry) if d > 0 else (entry - lo)
                peak_favor = max(peak_favor, fav)
                risk = abs(entry - p_stop) if p_stop else abs(entry - stop)
                if peak_favor >= p["trailR"] * abs(entry - stop):
                    ts = (entry + peak_favor - p["trailAtr"] * atr[i]) if d > 0 else (entry - peak_favor + p["trailAtr"] * atr[i])
                    stop = max(stop, ts) if d > 0 else min(stop, ts)
            if d > 0:
                if lo <= stop:
                    exit_px = min(o, stop)
                    reason = "stop"
                elif mode == "Take-profit + stop" and hi >= tp:
                    exit_px = o if o > tp else tp
                    reason = "tp"
            else:
                if hi >= stop:
                    exit_px = max(o, stop)
                    reason = "stop"
                elif mode == "Take-profit + stop" and lo <= tp:
                    exit_px = o if o < tp else tp
                    reason = "tp"
            if exit_px is None and mode == "Time stop" and i - ebar >= p["maxBars"]:
                exit_px = o
                reason = "time"
            if exit_px is None and p["exitOpp"] and ((d > 0 and fs[i]) or (d < 0 and fl[i])):
                exit_px = o
                reason = "opp"
            if exit_px is not None:
                exit_px -= tick * d
                pnl = qty * (exit_px - entry) * d
                cash += pnl - abs(qty * exit_px) * fee
                trades.append(dict(dir=d, entry=entry, exit=exit_px, pnl=pnl,
                                   bars=i - ebar, t_in=int(T[ebar]), t_out=int(T[i]),
                                   ret=pnl / capital))
                pos = 0

        # new signal -> queue entry for next bar
        if pos == 0 and pending == 0:
            if fl[i] or fs[i]:
                d = 1 if fl[i] else -1
                if d > 0:
                    a = c - atr[i] * p["slMult"]
                    st = sl[i] - atr[i] * p["swBuf"]
                    p_stop = min(a, st) if p["useWide"] else a
                else:
                    a = c + atr[i] * p["slMult"]
                    st = sh[i] + atr[i] * p["swBuf"]
                    p_stop = max(a, st) if p["useWide"] else a
                if not np.isnan(p_stop) and abs(c - p_stop) > 1e-9:
                    pending = d

        mark = cash if pos == 0 else cash + qty * (c - entry) * pos
        equity[i] = mark

    return equity, trades, T, C


def metrics(equity, trades, C, T, tf, capital=10_000.0):
    bps = YEAR / TF_SEC.get(tf, 3600)
    n = len(equity)
    ret = (equity[-1] / capital - 1) * 100
    peak = -1e18
    dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            dd = max(dd, (peak - e) / peak * 100)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gp = sum(t["pnl"] for t in wins)
    gl = sum(t["pnl"] for t in losses)
    r = np.diff(equity) / equity[:-1]
    r = r[np.isfinite(r)]
    sharpe = (r.mean() / r.std() * np.sqrt(bps)) if len(r) > 2 and r.std() else 0.0
    bh = (C[-1] / C[0] - 1) * 100
    return dict(
        ret=ret, dd=dd, sharpe=sharpe, buy_hold=bh,
        trades=len(trades),
        win_rate=(len(wins) / len(trades) * 100 if trades else 0.0),
        profit_factor=(gp / -gl if gl else (9.9 if gp else 0.0)),
        avg_bars=(np.mean([t["bars"] for t in trades]) if trades else 0.0),
        final_equity=equity[-1],
    )
