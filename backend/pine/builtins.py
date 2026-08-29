"""Built-in Pine functions (ta.*, math.*, strategy.*, misc). Best-effort subset."""
from __future__ import annotations
import math

NAN = float("nan")


def isna(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def num(x, d=NAN):
    if isna(x):
        return d
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _buf(ctx, cs, key, val):
    b = ctx.st(cs).setdefault(key, [])
    b.append(val)
    return b


def _win(b, n):
    if n <= 0 or len(b) < n:
        return None
    w = b[-n:]
    if any(isna(x) for x in w):
        return None
    return w


def _mean(w):
    return sum(w) / len(w)


def _sma(ctx, cs, src, n, key="s"):
    b = _buf(ctx, cs, key, src)
    w = _win(b, int(n))
    return _mean(w) if w else NAN


def _ema(ctx, cs, src, n, key="e"):
    s = ctx.st(cs)
    n = int(n)
    k = 2.0 / (n + 1.0)
    prev = s.get(key)
    if isna(src):
        return prev if prev is not None else NAN
    if prev is None:
        s[key] = src
    else:
        s[key] = src * k + prev * (1 - k)
    return s[key]


def _rma(ctx, cs, src, n, key="r"):
    s = ctx.st(cs)
    n = int(n)
    b = s.setdefault(key + "b", [])
    b.append(src)
    prev = s.get(key)
    if prev is None:
        w = _win(b, n)
        if not w:
            return NAN
        s[key] = _mean(w)
        return s[key]
    if isna(src):
        return prev
    a = 1.0 / n
    s[key] = a * src + (1 - a) * prev
    return s[key]


def _stdev(ctx, cs, src, n, key="sd"):
    b = _buf(ctx, cs, key, src)
    w = _win(b, int(n))
    if not w:
        return NAN
    m = _mean(w)
    return math.sqrt(sum((x - m) ** 2 for x in w) / len(w))


def _wma(ctx, cs, src, n, key="w"):
    b = _buf(ctx, cs, key, src)
    n = int(n)
    w = _win(b, n)
    if not w:
        return NAN
    wsum = n * (n + 1) / 2
    return sum(v * (i + 1) for i, v in enumerate(w)) / wsum


# ---- ta.* ----
def ta_sma(ctx, cs, a, kw):
    return _sma(ctx, cs, num(a[0]), a[1])


def ta_ema(ctx, cs, a, kw):
    return _ema(ctx, cs, num(a[0]), a[1])


def ta_rma(ctx, cs, a, kw):
    return _rma(ctx, cs, num(a[0]), a[1])


def ta_wma(ctx, cs, a, kw):
    return _wma(ctx, cs, num(a[0]), a[1])


def ta_vwma(ctx, cs, a, kw):
    src, n = num(a[0]), a[1]
    v = ctx.cur("volume")
    p = _sma(ctx, cs, src * v, n, "p")
    q = _sma(ctx, cs, v, n, "q")
    return p / q if q else NAN


def ta_hma(ctx, cs, a, kw):
    src, n = num(a[0]), int(a[1])
    w1 = _wma(ctx, cs, src, n // 2, "h1")
    w2 = _wma(ctx, cs, src, n, "h2")
    raw = 2 * w1 - w2 if not (isna(w1) or isna(w2)) else NAN
    return _wma(ctx, cs, raw, int(math.sqrt(n)), "h3")


def ta_stdev(ctx, cs, a, kw):
    return _stdev(ctx, cs, num(a[0]), a[1])


def ta_variance(ctx, cs, a, kw):
    s = _stdev(ctx, cs, num(a[0]), a[1])
    return s * s if not isna(s) else NAN


def ta_dev(ctx, cs, a, kw):
    b = _buf(ctx, cs, "d", num(a[0]))
    w = _win(b, int(a[1]))
    if not w:
        return NAN
    m = _mean(w)
    return sum(abs(x - m) for x in w) / len(w)


def ta_highest(ctx, cs, a, kw):
    if len(a) == 1:
        src, n = ctx.cur("high"), a[0]
    else:
        src, n = num(a[0]), a[1]
    b = _buf(ctx, cs, "h", src)
    n = int(n)
    if len(b) < 1:
        return NAN
    w = [x for x in b[-n:] if not isna(x)]
    return max(w) if w else NAN


def ta_lowest(ctx, cs, a, kw):
    if len(a) == 1:
        src, n = ctx.cur("low"), a[0]
    else:
        src, n = num(a[0]), a[1]
    b = _buf(ctx, cs, "l", src)
    n = int(n)
    w = [x for x in b[-n:] if not isna(x)]
    return min(w) if w else NAN


def _change(ctx, cs, src, n=1, key="c"):
    b = _buf(ctx, cs, key, src)
    n = int(n)
    if len(b) <= n or isna(b[-1]) or isna(b[-1 - n]):
        return NAN
    return b[-1] - b[-1 - n]


def ta_change(ctx, cs, a, kw):
    return _change(ctx, cs, num(a[0]), a[1] if len(a) > 1 else 1)


def ta_mom(ctx, cs, a, kw):
    return _change(ctx, cs, num(a[0]), a[1] if len(a) > 1 else 1)


def ta_roc(ctx, cs, a, kw):
    b = _buf(ctx, cs, "roc", num(a[0]))
    n = int(a[1])
    if len(b) <= n or isna(b[-1 - n]) or b[-1 - n] == 0:
        return NAN
    return 100.0 * (b[-1] - b[-1 - n]) / b[-1 - n]


def ta_cum(ctx, cs, a, kw):
    s = ctx.st(cs)
    v = num(a[0], 0.0)
    s["c"] = s.get("c", 0.0) + (0.0 if isna(v) else v)
    return s["c"]


def ta_sum(ctx, cs, a, kw):
    b = _buf(ctx, cs, "s", num(a[0], 0.0))
    w = b[-int(a[1]):]
    return sum(x for x in w if not isna(x))


def ta_rsi(ctx, cs, a, kw):
    src, n = num(a[0]), int(a[1])
    s = ctx.st(cs)
    prev = s.get("prev")
    s["prev"] = src
    if prev is None or isna(src):
        chg = NAN
    else:
        chg = src - prev
    up = max(chg, 0.0) if not isna(chg) else NAN
    dn = -min(chg, 0.0) if not isna(chg) else NAN
    au = _rma(ctx, cs, up, n, "au")
    ad = _rma(ctx, cs, dn, n, "ad")
    if isna(au) or isna(ad):
        return NAN
    if ad == 0:
        return 100.0
    rs = au / ad
    return 100.0 - 100.0 / (1.0 + rs)


def _tr(ctx):
    i = ctx.i
    h, l = ctx.H[i], ctx.L[i]
    c1 = ctx.C[i - 1] if i > 0 else NAN
    if isna(c1):
        return h - l
    return max(h - l, abs(h - c1), abs(l - c1))


def ta_tr(ctx, cs, a, kw):
    return _tr(ctx)


def ta_atr(ctx, cs, a, kw):
    return _rma(ctx, cs, _tr(ctx), int(a[0]), "atr")


def ta_crossover(ctx, cs, a, kw):
    x, y = num(a[0]), num(a[1])
    s = ctx.st(cs)
    pa, pb = s.get("a"), s.get("b")
    s["a"], s["b"] = x, y
    if pa is None or isna(pa) or isna(pb) or isna(x) or isna(y):
        return False
    return pa <= pb and x > y


def ta_crossunder(ctx, cs, a, kw):
    x, y = num(a[0]), num(a[1])
    s = ctx.st(cs)
    pa, pb = s.get("a"), s.get("b")
    s["a"], s["b"] = x, y
    if pa is None or isna(pa) or isna(pb) or isna(x) or isna(y):
        return False
    return pa >= pb and x < y


def ta_cross(ctx, cs, a, kw):
    x, y = num(a[0]), num(a[1])
    s = ctx.st(cs)
    pa, pb = s.get("a"), s.get("b")
    s["a"], s["b"] = x, y
    if pa is None or isna(pa) or isna(pb):
        return False
    return (pa <= pb and x > y) or (pa >= pb and x < y)


def ta_macd(ctx, cs, a, kw):
    src = num(a[0])
    f, sl, sig = int(a[1]), int(a[2]), int(a[3])
    ef = _ema(ctx, cs, src, f, "f")
    es = _ema(ctx, cs, src, sl, "s")
    macd = ef - es if not (isna(ef) or isna(es)) else NAN
    signal = _ema(ctx, cs, macd, sig, "sig")
    hist = macd - signal if not (isna(macd) or isna(signal)) else NAN
    return (macd, signal, hist)


def ta_bb(ctx, cs, a, kw):
    src, n, mult = num(a[0]), int(a[1]), num(a[2])
    basis = _sma(ctx, cs, src, n, "b")
    dev = mult * _stdev(ctx, cs, src, n, "d")
    return (basis, basis + dev, basis - dev)


def ta_barssince(ctx, cs, a, kw):
    s = ctx.st(cs)
    if ctx.truthy(a[0]):
        s["c"] = 0
    elif "c" in s:
        s["c"] += 1
    return s.get("c", NAN)


def ta_valuewhen(ctx, cs, a, kw):
    s = ctx.st(cs)
    hist = s.setdefault("h", [])
    occ = int(a[2]) if len(a) > 2 else 0
    if ctx.truthy(a[0]):
        hist.insert(0, num(a[1]))
    return hist[occ] if len(hist) > occ else NAN


def ta_rising(ctx, cs, a, kw):
    b = _buf(ctx, cs, "r", num(a[0]))
    n = int(a[1])
    w = _win(b, n + 1)
    return bool(w) and all(w[i] < w[i + 1] for i in range(n))


def ta_falling(ctx, cs, a, kw):
    b = _buf(ctx, cs, "f", num(a[0]))
    n = int(a[1])
    w = _win(b, n + 1)
    return bool(w) and all(w[i] > w[i + 1] for i in range(n))


def ta_pivothigh(ctx, cs, a, kw):
    if len(a) == 3:
        src, lb, rb = num(a[0]), int(a[1]), int(a[2])
    else:
        src, lb, rb = ctx.cur("high"), int(a[0]), int(a[1])
    b = _buf(ctx, cs, "p", src)
    if len(b) < lb + rb + 1:
        return NAN
    piv = b[-(rb + 1)]
    seg = b[-(lb + rb + 1):]
    if any(isna(x) for x in seg):
        return NAN
    return piv if all(piv >= x for x in seg) and seg.count(piv) == 1 else NAN


def ta_pivotlow(ctx, cs, a, kw):
    if len(a) == 3:
        src, lb, rb = num(a[0]), int(a[1]), int(a[2])
    else:
        src, lb, rb = ctx.cur("low"), int(a[0]), int(a[1])
    b = _buf(ctx, cs, "p", src)
    if len(b) < lb + rb + 1:
        return NAN
    piv = b[-(rb + 1)]
    seg = b[-(lb + rb + 1):]
    if any(isna(x) for x in seg):
        return NAN
    return piv if all(piv <= x for x in seg) and seg.count(piv) == 1 else NAN


def ta_linreg(ctx, cs, a, kw):
    b = _buf(ctx, cs, "lr", num(a[0]))
    n = int(a[1])
    off = int(a[2]) if len(a) > 2 else 0
    w = _win(b, n)
    if not w:
        return NAN
    xs = list(range(n))
    mx = _mean(xs)
    my = _mean(w)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return NAN
    slope = sum((xs[i] - mx) * (w[i] - my) for i in range(n)) / den
    intercept = my - slope * mx
    return intercept + slope * (n - 1 - off)


def ta_cci(ctx, cs, a, kw):
    tp = (ctx.cur("high") + ctx.cur("low") + ctx.cur("close")) / 3.0
    n = int(a[1]) if len(a) > 1 else int(a[0])
    src = num(a[0]) if len(a) > 1 else tp
    ma = _sma(ctx, cs, src, n, "m")
    md = ta_dev(ctx, cs, [src, n], {})
    if isna(ma) or isna(md) or md == 0:
        return NAN
    return (src - ma) / (0.015 * md)


def ta_stoch(ctx, cs, a, kw):
    src, hi, lo, n = num(a[0]), num(a[1]), num(a[2]), int(a[3])
    bh = _buf(ctx, cs, "h", hi)
    bl = _buf(ctx, cs, "l", lo)
    if len(bh) < n:
        return NAN
    hh = max(bh[-n:])
    ll = min(bl[-n:])
    return 100.0 * (src - ll) / (hh - ll) if hh != ll else NAN


def ta_wpr(ctx, cs, a, kw):
    n = int(a[0])
    bh = _buf(ctx, cs, "h", ctx.cur("high"))
    bl = _buf(ctx, cs, "l", ctx.cur("low"))
    if len(bh) < n:
        return NAN
    hh = max(bh[-n:])
    ll = min(bl[-n:])
    return -100.0 * (hh - ctx.cur("close")) / (hh - ll) if hh != ll else NAN


def ta_cmo(ctx, cs, a, kw):
    src, n = num(a[0]), int(a[1])
    s = ctx.st(cs)
    prev = s.get("p")
    s["p"] = src
    d = NAN if prev is None else src - prev
    up = _buf(ctx, cs, "u", max(d, 0.0) if not isna(d) else 0.0)
    dn = _buf(ctx, cs, "d", -min(d, 0.0) if not isna(d) else 0.0)
    if len(up) < n + 1:
        return NAN
    su, sd = sum(up[-n:]), sum(dn[-n:])
    return 100.0 * (su - sd) / (su + sd) if (su + sd) else NAN


def ta_tsi(ctx, cs, a, kw):
    src, short, long = num(a[0]), int(a[1]), int(a[2])
    s = ctx.st(cs)
    prev = s.get("p")
    s["p"] = src
    m = NAN if prev is None else src - prev
    e1 = _ema(ctx, cs, m, long, "e1")
    e2 = _ema(ctx, cs, e1, short, "e2")
    a1 = _ema(ctx, cs, abs(m) if not isna(m) else NAN, long, "a1")
    a2 = _ema(ctx, cs, a1, short, "a2")
    return 100.0 * e2 / a2 if a2 else NAN


def ta_percentrank(ctx, cs, a, kw):
    src, n = num(a[0]), int(a[1])
    b = _buf(ctx, cs, "b", src)
    if len(b) < n + 1:
        return NAN
    w = b[-n - 1:-1]
    return 100.0 * sum(1 for x in w if x <= src) / len(w)


def ta_median(ctx, cs, a, kw):
    src, n = num(a[0]), int(a[1])
    b = _buf(ctx, cs, "b", src)
    w = _win(b, n)
    if not w:
        return NAN
    sw = sorted(w)
    m = len(sw) // 2
    return sw[m] if len(sw) % 2 else (sw[m - 1] + sw[m]) / 2


def ta_supertrend(ctx, cs, a, kw):
    factor, period = num(a[0]), int(a[1])
    s = ctx.st(cs)
    atr = _rma(ctx, cs, _tr(ctx), period, "atr")
    if isna(atr):
        return (NAN, NAN)
    src = (ctx.cur("high") + ctx.cur("low")) / 2.0
    i = ctx.i
    c1 = ctx.C[i - 1] if i > 0 else ctx.C[i]
    close = ctx.cur("close")
    up = src - factor * atr
    dn = src + factor * atr
    up1 = s.get("up", up)
    dn1 = s.get("dn", dn)
    up = max(up, up1) if c1 > up1 else up
    dn = min(dn, dn1) if c1 < dn1 else dn
    tr = s.get("trend", 1)
    if tr == -1 and close > dn1:
        tr = 1
    elif tr == 1 and close < up1:
        tr = -1
    s["up"], s["dn"], s["trend"] = up, dn, tr
    st = up if tr == 1 else dn
    return (st, -tr)  # TV: negative direction == uptrend


def ta_sar(ctx, cs, a, kw):
    start = num(a[0]) if a else 0.02
    inc = num(a[1]) if len(a) > 1 else 0.02
    mx = num(a[2]) if len(a) > 2 else 0.2
    s = ctx.st(cs)
    h, l = ctx.cur("high"), ctx.cur("low")
    if "sar" not in s:
        s.update(sar=l, ep=h, af=start, long=True)
        return s["sar"]
    sar, ep, af, long = s["sar"], s["ep"], s["af"], s["long"]
    sar = sar + af * (ep - sar)
    if long:
        if l < sar:
            long = False
            sar = ep
            ep = l
            af = start
        else:
            if h > ep:
                ep = h
                af = min(af + inc, mx)
    else:
        if h > sar:
            long = True
            sar = ep
            ep = h
            af = start
        else:
            if l < ep:
                ep = l
                af = min(af + inc, mx)
    s.update(sar=sar, ep=ep, af=af, long=long)
    return sar


TA = {
    "ta.sma": ta_sma, "ta.ema": ta_ema, "ta.rma": ta_rma, "ta.wma": ta_wma,
    "ta.vwma": ta_vwma, "ta.hma": ta_hma, "ta.swma": ta_wma,
    "ta.stdev": ta_stdev, "ta.variance": ta_variance, "ta.dev": ta_dev,
    "ta.highest": ta_highest, "ta.lowest": ta_lowest,
    "ta.change": ta_change, "ta.mom": ta_mom, "ta.roc": ta_roc,
    "ta.cum": ta_cum, "ta.sum": ta_sum, "ta.rsi": ta_rsi,
    "ta.tr": ta_tr, "ta.atr": ta_atr,
    "ta.crossover": ta_crossover, "ta.crossunder": ta_crossunder, "ta.cross": ta_cross,
    "ta.macd": ta_macd, "ta.bb": ta_bb,
    "ta.barssince": ta_barssince, "ta.valuewhen": ta_valuewhen,
    "ta.rising": ta_rising, "ta.falling": ta_falling,
    "ta.pivothigh": ta_pivothigh, "ta.pivotlow": ta_pivotlow,
    "ta.linreg": ta_linreg, "ta.cci": ta_cci,
    "ta.stoch": ta_stoch, "ta.wpr": ta_wpr, "ta.cmo": ta_cmo, "ta.tsi": ta_tsi,
    "ta.percentrank": ta_percentrank, "ta.median": ta_median,
    "ta.supertrend": ta_supertrend, "ta.sar": ta_sar,
}


# ---- math.* ----
def _variadic(a):
    out = []
    for x in a:
        if isinstance(x, (list, tuple)):
            out.extend(x)
        else:
            out.append(x)
    return [num(v) for v in out]


MATH = {
    "math.abs": lambda c, cs, a, kw: abs(num(a[0])),
    "math.max": lambda c, cs, a, kw: max(_variadic(a)),
    "math.min": lambda c, cs, a, kw: min(_variadic(a)),
    "math.pow": lambda c, cs, a, kw: num(a[0]) ** num(a[1]),
    "math.sqrt": lambda c, cs, a, kw: math.sqrt(num(a[0])) if num(a[0]) >= 0 else NAN,
    "math.exp": lambda c, cs, a, kw: math.exp(num(a[0])),
    "math.log": lambda c, cs, a, kw: math.log(num(a[0])) if num(a[0]) > 0 else NAN,
    "math.log10": lambda c, cs, a, kw: math.log10(num(a[0])) if num(a[0]) > 0 else NAN,
    "math.sign": lambda c, cs, a, kw: (0.0 if num(a[0]) == 0 else math.copysign(1.0, num(a[0]))),
    "math.floor": lambda c, cs, a, kw: math.floor(num(a[0])),
    "math.ceil": lambda c, cs, a, kw: math.ceil(num(a[0])),
    "math.round": lambda c, cs, a, kw: round(num(a[0]), int(a[1]) if len(a) > 1 else 0),
    "math.avg": lambda c, cs, a, kw: _mean(_variadic(a)),
    "math.sum": lambda c, cs, a, kw: sum(_variadic(a)),
    "math.todegrees": lambda c, cs, a, kw: math.degrees(num(a[0])),
    "math.toradians": lambda c, cs, a, kw: math.radians(num(a[0])),
    "math.sin": lambda c, cs, a, kw: math.sin(num(a[0])),
    "math.cos": lambda c, cs, a, kw: math.cos(num(a[0])),
    "math.tan": lambda c, cs, a, kw: math.tan(num(a[0])),
    "math.round_to_mintick": lambda c, cs, a, kw: round(num(a[0]) / c.broker.cfg["mintick"]) * c.broker.cfg["mintick"],
}


# ---- misc ----
def b_nz(ctx, cs, a, kw):
    x = a[0]
    d = a[1] if len(a) > 1 else 0.0
    return d if isna(x) else x


def b_na(ctx, cs, a, kw):
    return isna(a[0])


def b_fixnan(ctx, cs, a, kw):
    s = ctx.st(cs)
    if not isna(a[0]):
        s["v"] = a[0]
    return s.get("v", NAN)


MISC = {
    "nz": b_nz, "na": b_na, "fixnan": b_fixnan,
    "math.random": lambda c, cs, a, kw: __import__("random").random(),
    "str.tostring": lambda c, cs, a, kw: ("" if isna(a[0]) else str(a[0])),
    "str.format": lambda c, cs, a, kw: str(a[0]) if a else "",
    "str.length": lambda c, cs, a, kw: len(str(a[0])),
    "timestamp": lambda c, cs, a, kw: 0.0,
    "color.new": lambda c, cs, a, kw: None,
    "color.rgb": lambda c, cs, a, kw: None,
}


# no-op sinks (drawing / plotting / alerts)
NOOP_NAMES = {
    "plot", "plotshape", "plotchar", "plotarrow", "plotcandle", "plotbar",
    "hline", "fill", "bgcolor", "barcolor", "line.new", "line.delete",
    "label.new", "label.delete", "label.set_text", "box.new", "table.new",
    "table.cell", "alertcondition", "alert", "log.info", "log.warning",
    "log.error", "indicator", "study", "library", "runtime.error",
}


def build_registry():
    reg = {}
    reg.update(TA)
    reg.update(MATH)
    reg.update(MISC)
    for nm in NOOP_NAMES:
        reg[nm] = lambda c, cs, a, kw: None
    return reg
