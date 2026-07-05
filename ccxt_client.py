"""
Cross-exchange crypto spread — real order-book-adjacent signal CoinGecko's
blended spot price (market_data.py::_fetch_crypto) can't show: how much a
coin's price actually diverges across exchanges right now. A quant desk
watches this; almost no retail platform surfaces it at all.

Public ticker endpoints only -- no API key, no auth, no trading. Read-only
market-data signal, not an execution feature.
"""
import ccxt

_EXCHANGES = {
    "binance": "binance",
    "coinbase": "coinbase",
    "kraken": "kraken",
}

# Each exchange quotes majors against a different stable/fiat pair by default.
_SYMBOL_MAP = {
    "BTC-USD": {"binance": "BTC/USDT", "coinbase": "BTC/USD", "kraken": "BTC/USD"},
    "ETH-USD": {"binance": "ETH/USDT", "coinbase": "ETH/USD", "kraken": "ETH/USD"},
}


def get_cross_exchange_spread(symbol: str) -> dict | None:
    """Fetch the same coin's price from 3 major exchanges' public tickers and
    compute the spread. Returns None if the symbol isn't supported or every
    exchange fails (never partial/fabricated data)."""
    pairs = _SYMBOL_MAP.get(symbol)
    if not pairs:
        return None

    prices = {}
    for name, exchange_id in _EXCHANGES.items():
        try:
            exchange = getattr(ccxt, exchange_id)()
            ticker = exchange.fetch_ticker(pairs[name])
            price = ticker.get("last")
            if price:
                prices[name] = round(float(price), 2)
        except Exception:
            continue

    if len(prices) < 2:
        return None

    lo, hi = min(prices.values()), max(prices.values())
    return {
        "symbol": symbol,
        "exchanges": prices,
        "min": lo,
        "max": hi,
        "spread_pct": round((hi - lo) / lo * 100, 3) if lo else 0.0,
    }
