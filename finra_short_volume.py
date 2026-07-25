"""FINRA Reg SHO daily short-volume ratio -- fast-moving market-microstructure
signal distinct from Finviz's short_interest snapshot (finviz_client.py),
which is a slow structural read updated roughly bi-weekly. This is a daily
flow indicator (ShortVolume / TotalVolume per trading day), useful for
spotting short-selling pressure building ahead of or around a catalyst.

Source: FINRA's public Reg SHO daily short sale volume files
(cdn.finra.org/equity/regsho/daily/CNMSshvol<date>.txt), pipe-delimited,
no signup or API key required. Same read-only public market-data trust
boundary as the existing yfinance/Finviz integrations.
"""
import statistics
from datetime import datetime, timedelta

import requests

from memory_store import insert_short_volume, get_short_volume_series

_BASE_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
_LOOKBACK_DAYS = 6  # walk back through weekends/holidays for the latest published file


def _fetch_file(date_str: str) -> str | None:
    try:
        resp = requests.get(_BASE_URL.format(date=date_str), timeout=15)
        if resp.status_code == 200 and resp.content:
            return resp.text
    except requests.RequestException:
        pass
    return None


def fetch_latest_short_volume_file() -> tuple[str, dict[str, dict]] | None:
    """Walk back from yesterday (FINRA publishes T+1) to find the latest
    available Reg SHO file. Returns (trade_date, {symbol: {short_volume,
    total_volume, short_volume_pct}}) covering every symbol in the file,
    or None if nothing published within the lookback window."""
    day = datetime.utcnow().date() - timedelta(days=1)
    for _ in range(_LOOKBACK_DAYS):
        date_str = day.strftime("%Y%m%d")
        text = _fetch_file(date_str)
        if text:
            rows = {}
            for line in text.splitlines()[1:]:  # skip "Date|Symbol|..." header
                parts = line.split("|")
                if len(parts) < 5:
                    continue
                _, symbol, short_vol, _, total_vol = parts[:5]
                try:
                    sv, tv = float(short_vol), float(total_vol)
                except ValueError:
                    continue
                if tv <= 0:
                    continue
                rows[symbol] = {
                    "short_volume": sv,
                    "total_volume": tv,
                    "short_volume_pct": round(sv / tv * 100, 2),
                }
            if rows:
                return date_str, rows
        day -= timedelta(days=1)
    return None


def refresh_short_volume(tickers: list[str]) -> int:
    """Downloads the latest published Reg SHO file once (it covers every
    NMS-listed symbol) and stores rows for whichever requested tickers are
    present in it. Returns the count matched/attempted -- a same-day re-run
    matches the same count again since insert_short_volume is idempotent
    per (symbol, trade_date), it just won't duplicate the row."""
    result = fetch_latest_short_volume_file()
    if not result:
        return 0
    trade_date, rows = result
    wanted = set(tickers)
    stored = 0
    for symbol, data in rows.items():
        if symbol not in wanted:
            continue
        insert_short_volume(symbol, trade_date, data["short_volume"], data["total_volume"], data["short_volume_pct"])
        stored += 1
    return stored


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/direction against the trailing window
    (excluding the latest point, so the z-score isn't self-referential).
    Same shape as copper_gold_ratio.py's _trend() helper -- kept as a local
    copy since bitcoin_onchain_client.py (where this pattern originates) and
    volume_anomaly.py (which shares the shape) aren't merged to main yet."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "rising"
    elif z < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def compute_short_volume_signal(symbol: str) -> dict | None:
    """{"symbol", "short_volume_pct", "trade_date", "trend": {...}} for a
    ticker with at least 8 stored daily readings, else None (not
    "insufficient_history" filler -- callers should treat None as no signal
    yet, same as short_interest before its first fetch)."""
    series = get_short_volume_series(symbol, limit=30)
    if not series:
        return None
    trend = _trend([r["short_volume_pct"] for r in series])
    latest = series[-1]
    return {
        "symbol": symbol,
        "short_volume_pct": latest["short_volume_pct"],
        "trade_date": latest["trade_date"],
        "trend": trend,
    }
