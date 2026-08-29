"""Historical kline downloader for data.binance.vision with a local CSV cache.

Cache is gzip CSV (no pyarrow dependency) so the app stays slim enough to run
on serverless platforms. On Vercel/Lambda the cache lives under /tmp and is
reused only while the instance stays warm.
"""
from __future__ import annotations
import io
import os
import zipfile
import datetime as dt
from typing import Optional

import pandas as pd
import requests


def _default_data_dir() -> str:
    env = os.environ.get("PINETESTER_DATA")
    if env:
        return os.path.abspath(env)
    # writable temp on serverless, local ./data otherwise
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return "/tmp/pinetester-data"
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))


BASE = "https://data.binance.vision/data"
DATA_DIR = _default_data_dir()
MAX_BARS = int(os.environ.get("PINETESTER_MAX_BARS", "60000"))

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "NEARUSDT",
    "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT", "TIAUSDT", "SEIUSDT",
    "RUNEUSDT", "FILUSDT", "ETCUSDT", "MATICUSDT", "PEPEUSDT", "WIFUSDT",
]
TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
MARKETS = ["spot", "futures"]

COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]

_session = requests.Session()
_session.headers.update({"User-Agent": "pinetester/2.0"})


def _seg(market: str) -> str:
    return "spot" if market == "spot" else "futures/um"


def _month_iter(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _norm_time(v: int) -> int:
    return v // 1000 if v > 1_000_000_000_000_000 else v


def _read_zip(content: bytes) -> pd.DataFrame:
    zf = zipfile.ZipFile(io.BytesIO(content))
    raw = zf.read(zf.namelist()[0]).decode("utf-8", "replace")
    first = raw.split("\n", 1)[0]
    header = 0 if first and not first.split(",")[0].replace(".", "").isdigit() else None
    df = pd.read_csv(io.StringIO(raw), header=header,
                     names=None if header == 0 else COLS)
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = df["open_time"].astype("int64").map(_norm_time)
    return df.dropna()


def _fetch(url: str) -> Optional[bytes]:
    r = _session.get(url, timeout=45)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


def _download_month(market, symbol, tf, y, m, log) -> Optional[pd.DataFrame]:
    seg = _seg(market)
    murl = f"{BASE}/{seg}/monthly/klines/{symbol}/{tf}/{symbol}-{tf}-{y:04d}-{m:02d}.zip"
    c = _fetch(murl)
    if c is not None:
        log(f"downloaded {symbol}-{tf}-{y:04d}-{m:02d} (monthly)")
        return _read_zip(c)
    parts = []
    d = dt.date(y, m, 1)
    while d.month == m and d <= dt.date.today():
        durl = f"{BASE}/{seg}/daily/klines/{symbol}/{tf}/{symbol}-{tf}-{d:%Y-%m-%d}.zip"
        c = _fetch(durl)
        if c is not None:
            parts.append(_read_zip(c))
        d += dt.timedelta(days=1)
    if parts:
        log(f"downloaded {symbol}-{tf}-{y:04d}-{m:02d} ({len(parts)} daily files)")
        return pd.concat(parts, ignore_index=True)
    return None


def _cache_path(market, symbol, tf) -> str:
    d = os.path.join(DATA_DIR, market)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{symbol}-{tf}.csv.gz")


def estimate_bars(tf: str, start: str, end: str) -> int:
    secs = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
            "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400}.get(tf, 3600)
    span = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days * 86400
    return max(0, span // secs)


def load_klines(market, symbol, tf, start, end, log=print) -> pd.DataFrame:
    symbol = symbol.upper()
    if market not in MARKETS:
        raise ValueError("market must be 'spot' or 'futures'")
    if tf not in TIMEFRAMES:
        raise ValueError(f"unsupported timeframe '{tf}'")
    sd = dt.date.fromisoformat(start)
    ed = dt.date.fromisoformat(end)
    if ed <= sd:
        raise ValueError("end date must be after start date")

    est = estimate_bars(tf, start, end)
    if est > MAX_BARS:
        raise RuntimeError(
            f"~{est:,} bars requested — over the {MAX_BARS:,} limit. "
            f"Use a higher timeframe or a shorter date range.")

    path = _cache_path(market, symbol, tf)
    cache = pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
    if os.path.exists(path):
        try:
            cache = pd.read_csv(path)
        except Exception:
            cache = cache

    have = set()
    if len(cache):
        for t in pd.to_datetime(cache["open_time"], unit="ms", utc=True):
            have.add((t.year, t.month))

    today = dt.date.today()
    new_parts = []
    for (y, m) in _month_iter(sd, ed):
        is_current = (y, m) >= (today.year, today.month)
        if (y, m) in have and not is_current:
            continue
        df = _download_month(market, symbol, tf, y, m, log)
        if df is not None and len(df):
            new_parts.append(df)

    if new_parts:
        cache = pd.concat([cache] + new_parts, ignore_index=True)
        cache = cache.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
        try:
            cache.to_csv(path, index=False, compression="gzip")
        except Exception as e:  # read-only FS is fine, just skip caching
            log(f"cache write skipped: {e}")

    if not len(cache):
        raise RuntimeError(f"no data available for {market} {symbol} {tf} in that range")

    lo = int(pd.Timestamp(sd, tz="UTC").timestamp() * 1000)
    hi = int((pd.Timestamp(ed, tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000)
    out = cache[(cache["open_time"] >= lo) & (cache["open_time"] < hi)].reset_index(drop=True)
    if not len(out):
        raise RuntimeError("no bars in the requested window")
    log(f"{len(out):,} bars loaded")
    return out
