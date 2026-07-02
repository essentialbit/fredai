"""Resolve a ticker to its company HQ and primary exchange coordinates.

Used to draw per-story HQ-to-exchange arcs on the dashboard globe (issue #48,
Phase 1) — mirrors the Google Studio concept's resolveTickerMetadata pattern,
reimplemented in Python against a small hand-maintained dictionary plus a
stable hash-based fallback for anything not explicitly listed.
"""

# (hq_lat, hq_lon, city, country, exchange, exchange_lat, exchange_lon)
TICKER_HQ_EXCHANGE = {
    "AAPL": (37.3229, -122.0322, "Cupertino", "USA", "NASDAQ", 40.7580, -73.9855),
    "MSFT": (47.6740, -122.1215, "Redmond", "USA", "NASDAQ", 40.7580, -73.9855),
    "NVDA": (37.3541, -121.9552, "Santa Clara", "USA", "NASDAQ", 40.7580, -73.9855),
    "TSLA": (30.2672, -97.7431, "Austin", "USA", "NASDAQ", 40.7580, -73.9855),
    "AMZN": (47.6062, -122.3321, "Seattle", "USA", "NASDAQ", 40.7580, -73.9855),
    "GOOGL": (37.4220, -122.0841, "Mountain View", "USA", "NASDAQ", 40.7580, -73.9855),
    "GOOG": (37.4220, -122.0841, "Mountain View", "USA", "NASDAQ", 40.7580, -73.9855),
    "META": (37.4530, -122.1817, "Menlo Park", "USA", "NASDAQ", 40.7580, -73.9855),
    "BAC": (35.2271, -80.8431, "Charlotte", "USA", "NYSE", 40.7069, -74.0113),
    "JPM": (40.7549, -73.9840, "New York", "USA", "NYSE", 40.7069, -74.0113),
    "GS": (40.7141, -74.0087, "New York", "USA", "NYSE", 40.7069, -74.0113),
    "SPY": (40.7069, -74.0113, "New York", "USA", "NYSE", 40.7069, -74.0113),
    "QQQ": (40.7580, -73.9855, "New York", "USA", "NASDAQ", 40.7580, -73.9855),
    "BTC-USD": (37.7749, -122.4194, "San Francisco", "USA", "Crypto", 37.7749, -122.4194),
    "ETH-USD": (37.7749, -122.4194, "San Francisco", "USA", "Crypto", 37.7749, -122.4194),
    "TSM": (24.78, 120.97, "Hsinchu", "Taiwan", "TWSE", 25.0330, 121.5654),
    "ASML": (51.40, 5.40, "Veldhoven", "Netherlands", "Euronext", 48.8686, 2.3421),
    "INTC": (37.3541, -121.9552, "Santa Clara", "USA", "NASDAQ", 40.7580, -73.9855),
    "AMD": (37.3541, -121.9552, "Santa Clara", "USA", "NASDAQ", 40.7580, -73.9855),
    "AZN": (52.2053, 0.1218, "Cambridge", "United Kingdom", "LSE", 51.5151, -0.0984),
    "BHP.AX": (-37.81, 144.96, "Melbourne", "Australia", "ASX", -33.8678, 151.2073),
    "CPU.AX": (-37.81, 144.96, "Melbourne", "Australia", "ASX", -33.8678, 151.2073),
    "REA.AX": (-33.8688, 151.2093, "Sydney", "Australia", "ASX", -33.8678, 151.2073),
    "PLS.AX": (-31.9505, 115.8605, "Perth", "Australia", "ASX", -33.8678, 151.2073),
}

_ANCHOR_CITIES = [
    ("New York", "USA", 40.7128, -74.0060, "NYSE", 40.7069, -74.0113),
    ("London", "United Kingdom", 51.5074, -0.1278, "LSE", 51.5151, -0.0984),
    ("Tokyo", "Japan", 35.6895, 139.6917, "TSE", 35.6824, 139.7781),
    ("Singapore", "Singapore", 1.3521, 103.8198, "SGX", 1.2789, 103.8504),
    ("Frankfurt", "Germany", 50.1107, 8.6821, "FSX", 50.1109, 8.6821),
    ("Sydney", "Australia", -33.8688, 151.2093, "ASX", -33.8678, 151.2073),
]


def resolve_ticker_location(ticker: str) -> dict:
    """Return HQ + exchange coordinates for a ticker, falling back to a stable
    hash-jittered anchor city for anything not in the explicit dictionary."""
    upper = (ticker or "").upper().strip()
    if upper in TICKER_HQ_EXCHANGE:
        lat, lon, city, country, exchange, ex_lat, ex_lon = TICKER_HQ_EXCHANGE[upper]
        return {
            "lat": lat, "lon": lon, "city": city, "country": country,
            "exchange": exchange, "exchange_lat": ex_lat, "exchange_lon": ex_lon,
        }

    h = 0
    for ch in upper:
        h = (ord(ch) + ((h << 5) - h)) & 0xFFFFFFFF
    h = abs(h if h < 2**31 else h - 2**32)
    city, country, lat, lon, exchange, ex_lat, ex_lon = _ANCHOR_CITIES[h % len(_ANCHOR_CITIES)]
    lat_jitter = ((h % 40) - 20) / 4.0
    lon_jitter = (((h >> 3) % 40) - 20) / 4.0
    return {
        "lat": lat + lat_jitter, "lon": lon + lon_jitter,
        "city": f"HQ Node - {city} Sector", "country": country,
        "exchange": exchange, "exchange_lat": ex_lat, "exchange_lon": ex_lon,
    }
