import yfinance as yf
import pandas as pd
from datetime import datetime
from config import WATCHLIST, DISPLAY_SYMBOLS

_cache: dict = {}

SECTORS = {
    "Technology": ["AAPL", "NVDA", "MSFT", "GOOGL", "META", "AMZN"],
    "Finance": ["JPM", "GS", "BAC"],
    "Index ETF": ["SPY", "QQQ"],
    "Crypto": ["BTC-USD", "ETH-USD"],
}


def fetch_quotes(symbols: list[str] = None) -> dict:
    symbols = symbols or WATCHLIST
    results = {}
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                t = tickers.tickers.get(sym)
                if t is None:
                    continue
                info = t.fast_info
                price = float(getattr(info, "last_price", 0) or 0)
                prev = float(getattr(info, "previous_close", price) or price)
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
            except Exception:
                pass
    except Exception as e:
        print(f"[Market] Batch fetch failed: {e}")
    return results


def fetch_history(symbol: str, period: str = "5d", interval: str = "30m") -> list[dict]:
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval=interval)
        if df.empty:
            return []
        df = df.reset_index()
        records = []
        for _, row in df.iterrows():
            ts = row.get("Datetime") or row.get("Date")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            else:
                ts = str(ts)
            records.append({
                "time": ts,
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row.get("Volume", 0)),
            })
        return records
    except Exception as e:
        print(f"[Market] History fetch failed for {symbol}: {e}")
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
