import time
import requests
from datetime import datetime
from config import WATCHLIST, DISPLAY_SYMBOLS

_cache: dict = {}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_BASE2 = "https://query2.finance.yahoo.com/v8/finance/chart"

SECTORS = {
    "Technology": ["AAPL", "NVDA", "MSFT", "GOOGL", "META", "AMZN"],
    "Finance": ["JPM", "GS", "BAC"],
    "Index ETF": ["SPY", "QQQ"],
    "Crypto": ["BTC-USD", "ETH-USD"],
}

_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "1d": "1d", "1wk": "1wk",
}

_RANGE_MAP = {
    "1d": "1d", "5d": "5d", "1mo": "1mo", "3mo": "3mo",
    "6mo": "6mo", "1y": "1y", "2y": "2y", "5y": "5y",
}


def _chart(symbol: str, interval: str = "1d", period: str = "5d") -> dict | None:
    interval = _INTERVAL_MAP.get(interval, interval)
    period = _RANGE_MAP.get(period, period)
    for base in (_BASE, _BASE2):
        try:
            r = requests.get(
                f"{base}/{symbol}?interval={interval}&range={period}",
                headers=_HEADERS, timeout=12
            )
            if r.status_code == 429:
                time.sleep(2)
                r = requests.get(
                    f"{base}/{symbol}?interval={interval}&range={period}",
                    headers=_HEADERS, timeout=12
                )
            r.raise_for_status()
            result = r.json().get("chart", {}).get("result")
            if result:
                return result[0]
        except Exception:
            continue
    return None


def fetch_quotes(symbols: list[str] = None) -> dict:
    symbols = symbols or WATCHLIST
    results = {}
    for sym in symbols:
        try:
            time.sleep(0.3)
            data = _chart(sym, "1d", "5d")
            if not data:
                continue
            meta = data["meta"]
            price = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
            prev = float(meta.get("previousClose") or price)
            if prev == 0:
                prev = price
            change = price - prev
            change_pct = (change / prev * 100) if prev else 0
            results[sym] = {
                "symbol": sym,
                "name": DISPLAY_SYMBOLS.get(sym, sym),
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "prev_close": round(prev, 2),
                "updated": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            print(f"[Market] Quote failed for {sym}: {e}")
    return results


def fetch_history(symbol: str, period: str = "5d", interval: str = "30m") -> list[dict]:
    try:
        data = _chart(symbol, interval, period)
        if not data:
            return []
        timestamps = data.get("timestamp", [])
        quote = data.get("indicators", {}).get("quote", [{}])[0]
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])
        records = []
        for i, ts in enumerate(timestamps):
            if i >= len(closes) or closes[i] is None:
                continue
            dt = datetime.utcfromtimestamp(ts).isoformat() + "Z"
            records.append({
                "time": dt,
                "open": round(float(opens[i] or closes[i]), 2),
                "high": round(float(highs[i] or closes[i]), 2),
                "low": round(float(lows[i] or closes[i]), 2),
                "close": round(float(closes[i]), 2),
                "volume": int(volumes[i] or 0) if i < len(volumes) else 0,
            })
        return records
    except Exception as e:
        print(f"[Market] History failed for {symbol}: {e}")
        return []


def get_sector_snapshot(quotes: dict) -> list[dict]:
    rows = []
    for sector, syms in SECTORS.items():
        for sym in syms:
            q = quotes.get(sym)
            if q:
                rows.append({
                    "sector": sector,
                    "symbol": sym,
                    "name": q["name"],
                    "change_pct": q["change_pct"],
                })
    return rows


def calculate_portfolio_value(holdings: list[dict], quotes: dict) -> dict:
    total_value = 0.0
    total_cost = 0.0
    positions = []
    for h in holdings:
        sym = h["symbol"]
        shares = float(h.get("shares", 0))
        avg_cost = float(h.get("avg_cost", 0))
        q = quotes.get(sym, {})
        price = q.get("price", avg_cost)
        value = shares * price
        cost = shares * avg_cost
        pnl = value - cost
        pnl_pct = (pnl / cost * 100) if cost else 0
        total_value += value
        total_cost += cost
        positions.append({
            "symbol": sym,
            "name": DISPLAY_SYMBOLS.get(sym, sym),
            "shares": shares,
            "avg_cost": avg_cost,
            "price": price,
            "value": round(value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "change_pct": q.get("change_pct", 0),
        })
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "positions": positions,
    }
