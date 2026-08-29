"""FastAPI server for PineTester."""
from __future__ import annotations
import os
import traceback

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import data as datamod
from . import optimizer as optmod
from .pine import run_backtest

HERE = os.path.dirname(__file__)
FRONTEND = os.path.abspath(os.path.join(HERE, "..", "frontend"))

app = FastAPI(title="PineTester", docs_url="/api/docs")


class BacktestReq(BaseModel):
    code: str
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    market: str = "spot"
    start: str = "2022-01-01"
    end: str = "2024-01-01"
    initial_capital: float | None = None
    qty_type: str | None = None
    qty_value: float | None = None
    commission_pct: float | None = None
    slippage: float | None = None
    mintick: float = 0.01
    overrides: dict = {}


class OptimizeReq(BacktestReq):
    params: list[dict] = []
    metric: str = "net_profit"


class CompareReq(BacktestReq):
    symbols: list[str] = []


@app.get("/api/config")
def config():
    return {
        "symbols": datamod.SYMBOLS,
        "timeframes": datamod.TIMEFRAMES,
        "markets": datamod.MARKETS,
        "metrics": optmod.METRICS,
        "max_bars": datamod.MAX_BARS,
    }


@app.get("/api/estimate")
def estimate(timeframe: str, start: str, end: str):
    try:
        return {"bars": datamod.estimate_bars(timeframe, start, end),
                "max_bars": datamod.MAX_BARS}
    except Exception as e:
        return {"bars": None, "error": str(e)}


def _err(e, logs):
    return JSONResponse(status_code=400, content={
        "error": str(e), "trace": traceback.format_exc(), "logs": logs})


@app.post("/api/backtest")
def backtest(req: BacktestReq):
    logs: list[str] = []
    try:
        df = datamod.load_klines(req.market, req.symbol, req.timeframe,
                                 req.start, req.end, log=logs.append)
        res = run_backtest(
            req.code, df, req.timeframe,
            initial_capital=req.initial_capital, qty_type=req.qty_type,
            qty_value=req.qty_value, commission_pct=req.commission_pct,
            slippage=req.slippage, mintick=req.mintick, overrides=req.overrides)
        res["logs"] = logs
        return res
    except Exception as e:
        return _err(e, logs)


@app.post("/api/optimize")
def optimize(req: OptimizeReq):
    logs: list[str] = []
    try:
        df = datamod.load_klines(req.market, req.symbol, req.timeframe,
                                 req.start, req.end, log=logs.append)
        base = dict(initial_capital=req.initial_capital, qty_type=req.qty_type,
                    qty_value=req.qty_value, commission_pct=req.commission_pct,
                    slippage=req.slippage, mintick=req.mintick, overrides=req.overrides)
        res = optmod.optimize(req.code, df, req.timeframe, req.params, req.metric, base)
        res["logs"] = logs
        return res
    except Exception as e:
        return _err(e, logs)


@app.post("/api/compare")
def compare(req: CompareReq):
    logs: list[str] = []
    syms = req.symbols or [req.symbol]
    out = []
    try:
        for sym in syms[:12]:
            try:
                df = datamod.load_klines(req.market, sym, req.timeframe,
                                         req.start, req.end, log=logs.append)
                r = run_backtest(
                    req.code, df, req.timeframe,
                    initial_capital=req.initial_capital, qty_type=req.qty_type,
                    qty_value=req.qty_value, commission_pct=req.commission_pct,
                    slippage=req.slippage, mintick=req.mintick, overrides=req.overrides)
                s = r["stats"]
                out.append({"symbol": sym, "ok": True, "net_profit": s["net_profit"],
                            "net_profit_pct": s["net_profit_pct"], "win_rate": s["win_rate"],
                            "profit_factor": s["profit_factor"], "trades": s["total_trades"],
                            "max_dd_pct": s["max_drawdown_pct"], "sharpe": s["sharpe"],
                            "buy_hold_pct": s["buy_hold_pct"]})
            except Exception as e:
                out.append({"symbol": sym, "ok": False, "error": str(e)})
        return {"rows": out, "logs": logs}
    except Exception as e:
        return _err(e, logs)


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))


@app.get("/static/{fname}")
def static_file(fname: str):
    if fname not in ("app.js", "presets.js", "index.html"):
        return JSONResponse(status_code=404, content={"error": "not found"})
    media = "text/javascript" if fname.endswith(".js") else "text/html"
    return FileResponse(os.path.join(FRONTEND, fname), media_type=media)


@app.get("/favicon.ico")
def favicon():
    return JSONResponse(status_code=204, content=None)
