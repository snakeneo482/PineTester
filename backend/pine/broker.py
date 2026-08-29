"""Minimal strategy broker emulating TradingView strategy.* semantics.

Model: next-bar-open fills for market orders; intrabar high/low checks for
protective stop/limit exits. Cash accounting with implicit leverage.
"""
from __future__ import annotations
import math

NAN = float("nan")


def _n(x, d=NAN):
    try:
        if x is None:
            return d
        x = float(x)
        return d if math.isnan(x) else x
    except (TypeError, ValueError):
        return d


class Broker:
    def __init__(self):
        self.cfg = dict(
            initial_capital=1_000_000.0,
            qty_type="fixed",       # fixed | pct | cash
            qty_value=1.0,
            commission_type="none",  # none | percent | cpo | cpc
            commission_value=0.0,
            slippage=0.0,            # ticks
            pyramiding=1,
            mintick=0.01,
            process_on_close=False,
        )
        self.cash = None
        self.lots = []          # open entry lots (all same direction)
        self.q_market = []      # queued market entry orders -> fill next open
        self.q_exit = []        # queued market exits -> fill next open
        self.pending = []       # stop/limit entry orders
        self.exits = []         # protective exit specs
        self.trades = []
        self.commission_paid = 0.0
        self.bars_in_market = 0
        self.log = []

    # ---- lifecycle ----
    def start(self):
        self.cash = self.cfg["initial_capital"]

    def configure(self, kw, pos):
        c = self.cfg
        if pos:
            pass
        c["initial_capital"] = _n(kw.get("initial_capital"), c["initial_capital"])
        qt = kw.get("default_qty_type")
        if qt == "pct":
            c["qty_type"] = "pct"
        elif qt == "cash":
            c["qty_type"] = "cash"
        elif qt == "fixed":
            c["qty_type"] = "fixed"
        c["qty_value"] = _n(kw.get("default_qty_value"), c["qty_value"])
        ct = kw.get("commission_type")
        if ct in ("percent", "cpo", "cpc"):
            c["commission_type"] = ct
        c["commission_value"] = _n(kw.get("commission_value"), c["commission_value"])
        c["slippage"] = _n(kw.get("slippage"), c["slippage"])
        p = kw.get("pyramiding")
        if p is not None and not (isinstance(p, float) and math.isnan(p)):
            c["pyramiding"] = max(1, int(p))
        if kw.get("process_orders_on_close"):
            c["process_on_close"] = True
        if not self.trades and not self.lots:
            self.cash = c["initial_capital"]

    # ---- helpers ----
    @property
    def pos_qty(self):
        return sum(l["qty"] * l["dir"] for l in self.lots)

    @property
    def pos_dir(self):
        return 0 if not self.lots else self.lots[0]["dir"]

    @property
    def pos_avg(self):
        tq = sum(l["qty"] for l in self.lots)
        if tq == 0:
            return NAN
        return sum(l["qty"] * l["price"] for l in self.lots) / tq

    def equity(self, px):
        return self.cash + self.pos_qty * px

    def _commission(self, notional, qty):
        c = self.cfg
        t = c["commission_type"]
        v = c["commission_value"]
        if t == "percent":
            return notional * v / 100.0
        if t == "cpo":
            return v
        if t == "cpc":
            return v * qty
        return 0.0

    def _slip(self, px, side):
        s = self.cfg["slippage"] * self.cfg["mintick"]
        return px + s if side > 0 else px - s

    def _size(self, px, explicit):
        e = _n(explicit)
        if not math.isnan(e):
            return abs(e)
        c = self.cfg
        eq = self.equity(px)
        if c["qty_type"] == "pct":
            return max(0.0, eq * c["qty_value"] / 100.0 / px)
        if c["qty_type"] == "cash":
            return max(0.0, c["qty_value"] / px)
        return max(0.0, c["qty_value"])

    # ---- order intake (called from interp) ----
    def entry(self, oid, direction, qty=NAN, limit=NAN, stop=NAN):
        direction = 1 if direction in (1, "long", True) else -1
        o = dict(id=oid, dir=direction, qty=qty,
                 limit=_n(limit), stop=_n(stop))
        if math.isnan(o["limit"]) and math.isnan(o["stop"]):
            self.q_market.append(o)
        else:
            self.pending.append(o)

    def exit(self, oid, from_entry=None, profit=NAN, loss=NAN, stop=NAN, limit=NAN,
             trail_points=NAN, trail_offset=NAN, qty_percent=100.0):
        self.exits.append(dict(id=oid, from_entry=from_entry,
                               profit=_n(profit), loss=_n(loss),
                               stop=_n(stop), limit=_n(limit),
                               trail_points=_n(trail_points), trail_offset=_n(trail_offset),
                               qty_percent=_n(qty_percent, 100.0), peak=None))

    def close(self, oid, qty_percent=100.0):
        self.q_exit.append(dict(id=oid, qty_percent=_n(qty_percent, 100.0)))

    def close_all(self):
        self.q_exit.append(dict(id=None, qty_percent=100.0))

    def cancel_all(self):
        self.pending.clear()

    # ---- fills ----
    def _open_lot(self, o, px, bar, time):
        px = self._slip(px, o["dir"])
        # reverse if opposite position exists
        if self.lots and self.lots[0]["dir"] != o["dir"]:
            self._close_lots(self.lots[:], px, bar, time, "reverse")
        if self.lots and len(self.lots) >= self.cfg["pyramiding"]:
            return
        qty = self._size(px, o["qty"])
        if qty <= 0:
            return
        notional = qty * px
        fee = self._commission(notional, qty)
        self.cash -= o["dir"] * notional
        self.cash -= fee
        self.commission_paid += fee
        self.lots.append(dict(id=o["id"], dir=o["dir"], qty=qty, price=px,
                              bar=bar, time=time, fee=fee, mae=0.0, mfe=0.0))

    def _close_lots(self, lots, px, bar, time, reason):
        for lot in lots:
            if lot not in self.lots:
                continue
            self.lots.remove(lot)
            xpx = self._slip(px, -lot["dir"])
            notional = lot["qty"] * xpx
            fee = self._commission(notional, lot["qty"])
            self.cash += lot["dir"] * notional
            self.cash -= fee
            self.commission_paid += fee
            pnl = lot["dir"] * (xpx - lot["price"]) * lot["qty"] - lot["fee"] - fee
            self.trades.append(dict(
                id=lot["id"], dir=lot["dir"], qty=lot["qty"],
                entry_bar=lot["bar"], entry_time=lot["time"], entry_price=lot["price"],
                exit_bar=bar, exit_time=time, exit_price=xpx,
                bars=bar - lot["bar"], pnl=pnl,
                pnl_pct=pnl / (lot["price"] * lot["qty"]) * 100.0,
                reason=reason,
                mae=lot["mae"], mfe=lot["mfe"],
            ))
        if not self.lots:
            self.exits.clear()

    # ---- per-bar processing ----
    def on_bar_open(self, bar, o, h, l, c, time):
        for order in self.q_exit:
            targets = list(self.lots) if order["id"] is None else [x for x in self.lots if x["id"] == order["id"]]
            self._close_lots(targets, o, bar, time, "close")
        self.q_exit.clear()
        for order in self.q_market:
            self._open_lot(order, o, bar, time)
        self.q_market.clear()
        # pending stop/limit entries
        still = []
        for order in self.pending:
            fpx = self._pending_fill(order, o, h, l)
            if fpx is None:
                still.append(order)
            else:
                self._open_lot(order, fpx, bar, time)
        self.pending = still
        self._check_protective(bar, o, h, l, time)

    def process_close(self, bar, o, h, l, c, time):
        """process_orders_on_close mode: fill queued market orders at this bar's close."""
        self._check_protective(bar, o, h, l, time)
        for order in self.q_exit:
            targets = list(self.lots) if order["id"] is None else [x for x in self.lots if x["id"] == order["id"]]
            self._close_lots(targets, c, bar, time, "close")
        self.q_exit.clear()
        for order in self.q_market:
            self._open_lot(order, c, bar, time)
        self.q_market.clear()
        still = []
        for order in self.pending:
            fpx = self._pending_fill(order, o, h, l)
            if fpx is None:
                still.append(order)
            else:
                self._open_lot(order, fpx, bar, time)
        self.pending = still

    def _pending_fill(self, order, o, h, l):
        st, li, d = order["stop"], order["limit"], order["dir"]
        if not math.isnan(st):
            if d > 0 and h >= st:
                return max(o, st)
            if d < 0 and l <= st:
                return min(o, st)
        if not math.isnan(li):
            if d > 0 and l <= li:
                return min(o, li)
            if d < 0 and h >= li:
                return max(o, li)
        return None

    def _check_protective(self, bar, o, h, l, time):
        if not self.lots:
            return
        d = self.pos_dir
        avg = self.pos_avg
        tick = self.cfg["mintick"]
        for ex in list(self.exits):
            sl = ex["stop"]
            tp = ex["limit"]
            if not math.isnan(ex["profit"]):
                tp = avg + d * ex["profit"] * tick
            if not math.isnan(ex["loss"]):
                sl = avg - d * ex["loss"] * tick
            if not math.isnan(ex["trail_points"]):
                trig = avg + d * ex["trail_points"] * tick
                if (d > 0 and h >= trig) or (d < 0 and l <= trig):
                    ex["peak"] = (h if d > 0 else l) if ex["peak"] is None else (
                        max(ex["peak"], h) if d > 0 else min(ex["peak"], l))
                if ex["peak"] is not None:
                    off = 0.0 if math.isnan(ex["trail_offset"]) else ex["trail_offset"] * tick
                    sl = ex["peak"] - d * off
            targets = list(self.lots) if not ex["from_entry"] else [x for x in self.lots if x["id"] == ex["from_entry"]]
            if not targets:
                continue
            if sl is not None and not (isinstance(sl, float) and math.isnan(sl)):
                if (d > 0 and l <= sl) or (d < 0 and h >= sl):
                    fpx = sl if (d > 0 and o > sl) or (d < 0 and o < sl) else o
                    self._close_lots(targets, fpx, bar, time, "stop")
                    continue
            if tp is not None and not (isinstance(tp, float) and math.isnan(tp)):
                if (d > 0 and h >= tp) or (d < 0 and l <= tp):
                    fpx = tp if (d > 0 and o < tp) or (d < 0 and o > tp) else o
                    self._close_lots(targets, fpx, bar, time, "target")

    def on_bar_close(self, bar, o, h, l, c, time):
        if self.lots:
            self.bars_in_market += 1
        d = self.pos_dir
        for lot in self.lots:
            adverse = (l - lot["price"]) if d > 0 else (lot["price"] - h)
            favor = (h - lot["price"]) if d > 0 else (lot["price"] - l)
            lot["mae"] = min(lot["mae"], adverse * lot["qty"])
            lot["mfe"] = max(lot["mfe"], favor * lot["qty"])

    def finish(self, bar, close_px, time):
        if self.lots:
            self._close_lots(list(self.lots), close_px, bar, time, "eod")
