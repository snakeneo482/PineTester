"""Bar-by-bar interpreter for the Pine subset AST."""
from __future__ import annotations
import math

from .builtins import build_registry, isna, num
from .broker import Broker

NAN = float("nan")

CONSTS = {
    "strategy.long": 1, "strategy.short": -1,
    "strategy.percent_of_equity": "pct", "strategy.cash": "cash",
    "strategy.fixed": "fixed",
    "strategy.commission.percent": "percent",
    "strategy.commission.cash_per_order": "cpo",
    "strategy.commission.cash_per_contract": "cpc",
    "strategy.direction.all": "all", "strategy.direction.long": "long",
    "strategy.direction.short": "short",
    "strategy.oca.none": "none", "strategy.oca.cancel": "cancel", "strategy.oca.reduce": "reduce",
    "true": True, "false": False,
}

NAMESPACES = ("color", "plot", "location", "shape", "size", "text", "xloc", "yloc",
              "barmerge", "display", "format", "scale", "hline", "label", "line",
              "table", "box", "alert", "session", "adjustment", "extend",
              "font", "dayofweek", "currency", "math", "position", "order",
              "barstate", "chart", "earnings", "dividends", "splits")


_MISS = object()
_SPECIAL = {
    "bar_index": lambda c: c.i,
    "last_bar_index": lambda c: c.n - 1,
    "na": lambda c: NAN,
    "hl2": lambda c: (c.cur("high") + c.cur("low")) / 2,
    "hlc3": lambda c: (c.cur("high") + c.cur("low") + c.cur("close")) / 3,
    "ohlc4": lambda c: (c.cur("open") + c.cur("high") + c.cur("low") + c.cur("close")) / 4,
    "hlcc4": lambda c: (c.cur("high") + c.cur("low") + 2 * c.cur("close")) / 4,
}


class Series:
    __slots__ = ("v", "s")

    def __init__(self, n):
        self.v = [NAN] * n
        self.s = bytearray(n)

    def setc(self, i, val):
        self.v[i] = val
        self.s[i] = 1

    def get(self, i, off=0):
        k = i - off
        if k < 0 or k >= len(self.v):
            return NAN
        if off == 0 and not self.s[i]:
            return self.v[i - 1] if i > 0 else NAN
        return self.v[k]

    def carry(self, i):
        if not self.s[i]:
            self.v[i] = self.v[i - 1] if i > 0 else NAN
            self.s[i] = 1


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class Context:
    def __init__(self, O, H, L, C, V, T, mintick=0.01):
        self.O, self.H, self.L, self.C, self.V, self.T = O, H, L, C, V, T
        self.n = len(C)
        self.i = 0
        self.series = {}
        self.funcs = {}
        self.state = {}
        self._var_inited = set()
        self._icache = {}
        self.inputs = {}
        self.plots = {}
        self.param_overrides = {}
        self.warnings = []
        self.broker = Broker()
        self.broker.cfg["mintick"] = mintick
        self.reg = build_registry()
        self._init_series()

    def _init_series(self):
        for nm, arr in (("open", self.O), ("high", self.H), ("low", self.L),
                        ("close", self.C), ("volume", self.V), ("time", self.T)):
            s = Series(self.n)
            s.v = list(arr)
            s.s = bytearray([1]) * self.n
            self.series[nm] = s

    def st(self, cs):
        return self.state.setdefault(cs, {})

    def warn(self, m):
        if m not in self.warnings:
            self.warnings.append(m)

    def cur(self, name):
        s = self.series.get(name)
        return s.get(self.i) if s else NAN

    def truthy(self, x):
        if x is None:
            return False
        if isinstance(x, bool):
            return x
        if isinstance(x, str):
            return len(x) > 0
        if isinstance(x, (int, float)):
            return not (isinstance(x, float) and math.isnan(x)) and x != 0
        return bool(x)

    # ---- name resolution ----
    def resolve(self, name, scope):
        if scope is not None and name in scope:
            return scope[name]
        s = self.series.get(name)
        if s is not None:
            return s.get(self.i)
        v = CONSTS.get(name, _MISS)
        if v is not _MISS:
            return v
        f = _SPECIAL.get(name)
        if f is not None:
            return f(self)
        if "." in name:
            head = name[:name.index(".")]
            if name.startswith("strategy."):
                return self._strat_read(name)
            if head in NAMESPACES:
                return None
            if head in ("syminfo", "timeframe", "chart", "ticker"):
                return "" if name != "syminfo.mintick" else self.broker.cfg["mintick"]
        self.warn(f"unknown identifier '{name}' -> na")
        return NAN

    def _strat_read(self, name):
        b = self.broker
        if name == "strategy.position_size":
            return b.pos_qty
        if name == "strategy.position_avg_price":
            return b.pos_avg
        if name == "strategy.equity":
            return b.equity(self.cur("close"))
        if name == "strategy.initial_capital":
            return b.cfg["initial_capital"]
        if name == "strategy.opentrades":
            return len(b.lots)
        if name == "strategy.closedtrades":
            return len(b.trades)
        if name == "strategy.wintrades":
            return sum(1 for t in b.trades if t["pnl"] > 0)
        if name == "strategy.losstrades":
            return sum(1 for t in b.trades if t["pnl"] < 0)
        if name in ("strategy.openprofit", "strategy.netprofit"):
            unreal = b.pos_qty * self.cur("close") - sum(l["dir"] * l["qty"] * l["price"] for l in b.lots)
            if name == "strategy.openprofit":
                return unreal
            return b.equity(self.cur("close")) - b.cfg["initial_capital"] - unreal
        return NAN

    # ---- expression eval ----
    def ev(self, e, scope=None):
        t = e["t"]
        if t == "num":
            return e["v"]
        if t == "str":
            return e["v"]
        if t == "bool":
            return e["v"]
        if t == "na":
            return NAN
        if t == "list":
            return [self.ev(x, scope) for x in e["items"]]
        if t == "name":
            return self.resolve(e["v"], scope)
        if t == "member":
            return self.resolve(self._dotted(e), scope)
        if t == "un":
            v = self.ev(e["e"], scope)
            if e["op"] == "not":
                return not self.truthy(v)
            if e["op"] == "-":
                return -num(v)
            return num(v)
        if t == "bin":
            return self._bin(e, scope)
        if t == "tern":
            return self.ev(e["a"], scope) if self.truthy(self.ev(e["c"], scope)) else self.ev(e["b"], scope)
        if t == "index":
            return self._index(e, scope)
        if t == "call":
            return self._call(e, scope)
        if t == "switch":
            return self._switch(e, scope)
        if t == "ifexpr":
            return self._ifexpr(e, scope)
        raise RuntimeError(f"cannot eval node {t}")

    def _dotted(self, e):
        if e["t"] == "name":
            return e["v"]
        if e["t"] == "member":
            return self._dotted(e["e"]) + "." + e["name"]
        return None

    def _bin(self, e, scope):
        op = e["op"]
        if op == "and":
            return self.truthy(self.ev(e["l"], scope)) and self.truthy(self.ev(e["r"], scope))
        if op == "or":
            return self.truthy(self.ev(e["l"], scope)) or self.truthy(self.ev(e["r"], scope))
        a = self.ev(e["l"], scope)
        b = self.ev(e["r"], scope)
        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                return f"{a}{b}"
            return num(a) + num(b)
        if op == "-":
            return num(a) - num(b)
        if op == "*":
            return num(a) * num(b)
        if op == "/":
            db = num(b)
            return num(a) / db if db != 0 else NAN
        if op == "%":
            db = num(b)
            return math.fmod(num(a), db) if db != 0 else NAN
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        na, nb = num(a), num(b)
        if math.isnan(na) or math.isnan(nb):
            return False
        return {"<": na < nb, ">": na > nb, "<=": na <= nb, ">=": na >= nb}[op]

    def _has_call(self, e):
        if isinstance(e, dict):
            if e.get("t") == "call":
                return True
            return any(self._has_call(v) for v in e.values())
        if isinstance(e, (list, tuple)):
            return any(self._has_call(v) for v in e)
        return False

    def _index(self, e, scope):
        off = int(num(self.ev(e["i"], scope), 0))
        base = e["e"]
        if base["t"] == "name":
            nm = base["v"]
            if scope and nm in scope:
                return scope[nm] if off == 0 else NAN
            if nm in self.series:
                return self.series[nm].get(self.i, off)
            if nm == "bar_index":
                return self.i - off
        if base["t"] == "call":
            cur = self.ev(base, scope)
            if off == 0:
                return cur
            buf = self.state.get(base.get("cs"), {}).get("__out", [])
            j = len(buf) - 1 - off
            return buf[j] if 0 <= j < len(buf) else NAN
        if off == 0:
            return self.ev(base, scope)
        if self._has_call(base):
            self.warn("history of an expression containing a call is unsupported -> na")
            return NAN
        if self.i - off < 0:
            return NAN
        save = self.i
        self.i -= off
        try:
            return self.ev(base, scope)
        finally:
            self.i = save

    def _switch(self, e, scope):
        subj = self.ev(e["subj"], scope) if e["subj"] else None
        for cond, res in e["cases"]:
            if cond is None:
                return self.ev(res, scope)
            cv = self.ev(cond, scope)
            if (subj is not None and cv == subj) or (e["subj"] is None and self.truthy(cv)):
                return self.ev(res, scope)
        return NAN

    def _ifexpr(self, e, scope):
        if self.truthy(self.ev(e["cond"], scope)):
            return self._block_value(e["then"], scope)
        for c, b in e["elifs"]:
            if self.truthy(self.ev(c, scope)):
                return self._block_value(b, scope)
        if e["els"] is not None:
            return self._block_value(e["els"], scope)
        return NAN

    def _block_value(self, stmts, scope):
        val = NAN
        for s in stmts:
            val = self.run_stmt(s, scope, capture=True)
        return val

    # ---- calls ----
    def _call(self, e, scope):
        name = e["name"]
        args = []
        kw = {}
        for nm, ax in e["args"]:
            v = self.ev(ax, scope)
            if nm is None:
                args.append(v)
            else:
                kw[nm] = v
        if name in self.funcs:
            return self._call_user(self.funcs[name], args, kw)
        if name and (name == "input" or name.startswith("input.")):
            return self._input(e, name, args, kw)
        if name and (name == "strategy" or name.startswith("strategy.")):
            return self._strategy(name, args, kw, e)
        if name == "plot":
            self._plot(e, args, kw)
            return None
        if name in ("request.security", "security"):
            # approximation: evaluate the expression on the current timeframe
            self.warn("request.security is approximated on the chart timeframe")
            return args[2] if len(args) > 2 else NAN
        fn = self.reg.get(name)
        if fn is None:
            self.warn(f"unimplemented function '{name}()' -> na")
            return NAN
        try:
            res = fn(self, e["cs"], args, kw)
        except Exception as ex:  # keep the backtest alive
            self.warn(f"{name}() error: {ex}")
            res = NAN
        # keep an output history so `f(...)[k]` works on stateful calls
        stt = self.st(e["cs"])
        buf = stt.setdefault("__out", [])
        if stt.get("__bar") == self.i and buf:
            buf[-1] = res
        else:
            buf.append(res)
            stt["__bar"] = self.i
        return res

    def _call_user(self, fn, args, kw):
        scope = {}
        for idx, (pnm, dflt) in enumerate(fn["params"]):
            if idx < len(args):
                scope[pnm] = args[idx]
            elif pnm in kw:
                scope[pnm] = kw[pnm]
            elif dflt is not None:
                scope[pnm] = self.ev(dflt, {})
            else:
                scope[pnm] = NAN
        if fn["single"]:
            return self.ev(fn["body"], scope)
        return self._block_value(fn["body"], scope)

    def _plot(self, e, args, kw):
        if len(self.plots) >= 8 and f"p{e['cs']}" not in self.plots:
            return
        key = f"p{e['cs']}"
        title = kw.get("title") or (args[1] if len(args) > 1 and isinstance(args[1], str) else f"plot {len(self.plots) + 1}")
        rec = self.plots.setdefault(key, {"title": title, "color": kw.get("color"), "data": [None] * self.n})
        v = args[0] if args else None
        rec["data"][self.i] = None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)

    def _input(self, e, name, args, kw):
        cs = e["cs"]
        if cs in self._icache:
            return self._icache[cs]
        key = e.get("_lhs") or f"input_{cs}"
        default = kw.get("defval", args[0] if args else 0)
        title = kw.get("title") or (args[1] if len(args) > 1 and isinstance(args[1], str) else key)
        typ = name.split(".")[1] if "." in name else "generic"
        rec = self.inputs.setdefault(key, {
            "name": key, "title": title, "type": typ, "default": default,
            "min": kw.get("minval"), "max": kw.get("maxval"), "step": kw.get("step"),
            "options": kw.get("options"),
        })
        val = rec["default"]
        if key in self.param_overrides:
            ov = self.param_overrides[key]
            try:
                if isinstance(default, bool):
                    val = ov.strip().lower() in ("true", "1", "yes") if isinstance(ov, str) else bool(ov)
                elif isinstance(default, (int, float)):
                    val = float(ov)
                else:
                    val = ov
            except (TypeError, ValueError):
                val = default
        self._icache[cs] = val
        return val

    def _strategy(self, name, args, kw, e):
        b = self.broker
        if name == "strategy":
            kw2 = dict(kw)
            b.configure(kw2, args)
            return None
        when = kw.get("when", True)
        if not self.truthy(when):
            return None
        if name == "strategy.entry":
            oid = args[0] if args else "e"
            direction = kw.get("direction", args[1] if len(args) > 1 else 1)
            qty = kw.get("qty", args[2] if len(args) > 2 else NAN)
            b.entry(oid, direction, qty, kw.get("limit", NAN), kw.get("stop", NAN))
        elif name == "strategy.order":
            oid = args[0] if args else "o"
            direction = kw.get("direction", args[1] if len(args) > 1 else 1)
            qty = kw.get("qty", args[2] if len(args) > 2 else NAN)
            b.entry(oid, direction, qty, kw.get("limit", NAN), kw.get("stop", NAN))
        elif name == "strategy.exit":
            oid = args[0] if args else "x"
            b.exit(oid, kw.get("from_entry", args[1] if len(args) > 1 else None),
                   kw.get("profit", NAN), kw.get("loss", NAN),
                   kw.get("stop", NAN), kw.get("limit", NAN),
                   kw.get("trail_points", NAN), kw.get("trail_offset", NAN),
                   kw.get("qty_percent", 100.0))
        elif name == "strategy.close":
            b.close(args[0] if args else None, kw.get("qty_percent", 100.0))
        elif name == "strategy.close_all":
            b.close_all()
        elif name in ("strategy.cancel", "strategy.cancel_all"):
            b.cancel_all()
        return None

    # ---- statements ----
    def run_stmt(self, s, scope, capture=False):
        t = s["t"]
        if t == "noop":
            return NAN
        if t == "assign":
            if s.get("var") and s["name"] in self._var_inited:
                return self.series[s["name"]].get(self.i)
            expr = s["expr"]
            if expr["t"] == "call" and expr.get("name", "").startswith("input"):
                expr["_lhs"] = s["name"]
            v = self.ev(expr, scope)
            if scope is not None and not s.get("var"):
                # plain assignment inside a function/loop body stays local
                if s["name"] in scope or (scope and s["name"] not in self.series):
                    scope[s["name"]] = v
                    return v
            self._set_series(s["name"], v, s.get("var"))
            if s.get("var"):
                self._var_inited.add(s["name"])
            return v
        if t == "reassign":
            v = self.ev(s["expr"], scope)
            if scope is not None and s["name"] in scope:
                scope[s["name"]] = v
                return v
            self._set_series(s["name"], v, False)
            return v
        if t == "massign":
            v = self.ev(s["expr"], scope)
            seq = v if isinstance(v, (list, tuple)) else [v]
            for idx, nm in enumerate(s["names"]):
                val = seq[idx] if idx < len(seq) else NAN
                if scope is not None and nm in scope:
                    scope[nm] = val
                else:
                    self._set_series(nm, val, s.get("var"))
            return NAN
        if t == "exprstmt":
            return self.ev(s["expr"], scope)
        if t == "func":
            self.funcs[s["name"]] = s
            return NAN
        if t == "if":
            if self.truthy(self.ev(s["cond"], scope)):
                return self._run_block(s["then"], scope, capture)
            for c, b in s["elifs"]:
                if self.truthy(self.ev(c, scope)):
                    return self._run_block(b, scope, capture)
            if s["els"]:
                return self._run_block(s["els"], scope, capture)
            return NAN
        if t == "for":
            frm = int(num(self.ev(s["frm"], scope), 0))
            to = int(num(self.ev(s["to"], scope), 0))
            by = int(num(self.ev(s["by"], scope), 1)) if s["by"] else 1
            by = by or 1
            lscope = dict(scope) if scope is not None else {}
            rng = range(frm, to + 1, by) if by > 0 else range(frm, to - 1, by)
            guard = 0
            for k in rng:
                guard += 1
                if guard > 100000:
                    break
                lscope[s["var"]] = k
                try:
                    self._run_block(s["body"], lscope, False)
                except _Break:
                    break
                except _Continue:
                    continue
            return NAN
        if t == "while":
            lscope = dict(scope) if scope is not None else {}
            guard = 0
            while self.truthy(self.ev(s["cond"], lscope)):
                guard += 1
                if guard > 100000:
                    break
                try:
                    self._run_block(s["body"], lscope, False)
                except _Break:
                    break
                except _Continue:
                    continue
            return NAN
        if t == "break":
            raise _Break()
        if t == "continue":
            raise _Continue()
        raise RuntimeError(f"unknown stmt {t}")

    def _run_block(self, stmts, scope, capture):
        val = NAN
        for s in stmts:
            val = self.run_stmt(s, scope, capture)
        return val

    def _set_series(self, name, v, is_var):
        s = self.series.get(name)
        if s is None:
            s = Series(self.n)
            self.series[name] = s
        s.setc(self.i, v)

    # ---- top level run ----
    def run(self, program, progress=None):
        self.broker.start()
        equity = []
        self._program = program
        poc = self.broker.cfg.get("process_on_close")
        for i in range(self.n):
            self.i = i
            o, h, l, c = self.O[i], self.H[i], self.L[i], self.C[i]
            tm = self.T[i]
            if not poc:
                self.broker.on_bar_open(i, o, h, l, c, tm)
            for s in program:
                try:
                    self.run_stmt(s, None)
                except (_Break, _Continue):
                    pass
            if poc:
                self.broker.process_close(i, o, h, l, c, tm)
            self.broker.on_bar_close(i, o, h, l, c, tm)
            for name, ser in self.series.items():
                ser.carry(i)
            equity.append(self.broker.equity(c))
            if progress and i % 5000 == 0:
                progress(i, self.n)
        self.broker.finish(self.n - 1, self.C[-1], self.T[-1])
        equity[-1] = self.broker.equity(self.C[-1])
        return equity
