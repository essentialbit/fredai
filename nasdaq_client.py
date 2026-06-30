"""Nasdaq Data Link integration — real-time and historical financial data.

Docs: https://docs.data.nasdaq.com/docs/streaming-api
Free tier: limited datasets; premium datasets require subscription.

Provides:
- Treasury yield curves (FRED/USTREASURY)
- Commodities (CHRIS futures)
- Macro indicators
- Streaming WebSocket for real-time quotes (requires Nasdaq premium)
"""
import os
import json
import threading
import requests
from datetime import datetime, timedelta
from config import DB_PATH

NASDAQ_API_KEY = os.getenv("NASDAQ_API_KEY", "")
NASDAQ_BASE = "https://data.nasdaq.com/api/v3"

# Free datasets available without premium
FREE_DATASETS = {
    "US_TREASURY_YIELD_10Y": ("FRED", "DGS10", "10Y Treasury Yield"),
    "US_TREASURY_YIELD_2Y": ("FRED", "DGS2", "2Y Treasury Yield"),
    "VIX": ("CBOE", "VIX", "CBOE VIX Fear Index"),
    "GOLD": ("LBMA", "GOLD", "Gold Spot Price"),
    "OIL_WTI": ("CHRIS", "CME_CL1", "WTI Crude Oil Futures"),
    "SP500_PE": ("MULTPL", "SP500_PE_RATIO_MONTH", "S&P 500 P/E Ratio"),
}

_cache: dict = {}
_cache_expiry: dict = {}
CACHE_TTL_SECONDS = 3600  # 1h for macro data


def _headers() -> dict:
    return {"Accept": "application/json"}


def _params(extra: dict = None) -> dict:
    p = {"api_key": NASDAQ_API_KEY} if NASDAQ_API_KEY else {}
    if extra:
        p.update(extra)
    return p


def fetch_dataset(database: str, dataset: str, rows: int = 1) -> dict | None:
    """Fetch latest data from a Nasdaq dataset."""
    cache_key = f"{database}/{dataset}"
    if cache_key in _cache and _cache_expiry.get(cache_key, 0) > datetime.utcnow().timestamp():
        return _cache[cache_key]

    url = f"{NASDAQ_BASE}/datasets/{database}/{dataset}/data.json"
    try:
        r = requests.get(url, headers=_headers(), params=_params({"rows": rows, "order": "desc"}), timeout=10)
        if r.status_code == 403:
            return None  # Not subscribed
        if r.status_code != 200:
            print(f"[Nasdaq] {database}/{dataset}: HTTP {r.status_code}")
            return None
        data = r.json().get("dataset_data", {})
        _cache[cache_key] = data
        _cache_expiry[cache_key] = datetime.utcnow().timestamp() + CACHE_TTL_SECONDS
        return data
    except Exception as e:
        print(f"[Nasdaq] fetch error {database}/{dataset}: {e}")
        return None


def get_macro_snapshot() -> dict:
    """Fetch key macro indicators from free Nasdaq datasets."""
    snapshot = {}
    for key, (db, ds, label) in FREE_DATASETS.items():
        data = fetch_dataset(db, ds, rows=2)
        if not data:
            continue
        rows = data.get("data", [])
        col_names = data.get("column_names", [])
        if not rows or not col_names:
            continue
        try:
            latest = dict(zip(col_names, rows[0]))
            prev = dict(zip(col_names, rows[1])) if len(rows) > 1 else {}
            date_col = col_names[0]
            val_col = col_names[1] if len(col_names) > 1 else col_names[0]
            val = latest.get(val_col)
            prev_val = prev.get(val_col)
            snapshot[key] = {
                "label": label,
                "value": val,
                "prev": prev_val,
                "change": round(float(val) - float(prev_val), 4) if val and prev_val else None,
                "date": latest.get(date_col),
            }
        except Exception:
            continue
    return snapshot


class NasdaqStreamClient:
    """
    WebSocket streaming client for Nasdaq real-time data.
    Requires a Nasdaq Data Link subscription with streaming access.

    Connects to: wss://ws.data.nasdaq.com/

    Usage:
        client = NasdaqStreamClient(api_key=NASDAQ_API_KEY, on_tick=callback)
        client.subscribe(["XNAS/AAPL", "XNAS/NVDA"])
        client.start()
    """

    WS_URL = "wss://ws.data.nasdaq.com/"

    def __init__(self, api_key: str, on_tick=None, on_error=None):
        self.api_key = api_key
        self.on_tick = on_tick
        self.on_error = on_error
        self._ws = None
        self._thread = None
        self._subscriptions: list[str] = []
        self._running = False

    def subscribe(self, tickers: list[str]):
        """Add tickers to subscription list (format: 'EXCHANGE/SYMBOL')."""
        self._subscriptions.extend(tickers)

    def start(self):
        """Start the streaming connection in a background thread."""
        if not self.api_key:
            print("[Nasdaq Stream] No API key — streaming disabled")
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()

    def _connect(self):
        try:
            import websocket
        except ImportError:
            print("[Nasdaq Stream] websocket-client not installed. Run: pip install websocket-client")
            return

        def on_open(ws):
            print("[Nasdaq Stream] Connected")
            # Authenticate
            ws.send(json.dumps({"action": "auth", "params": self.api_key}))
            # Subscribe to tickers
            for ticker in self._subscriptions:
                ws.send(json.dumps({"action": "subscribe", "params": ticker}))

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if self.on_tick:
                    self.on_tick(data)
            except Exception as e:
                print(f"[Nasdaq Stream] Parse error: {e}")

        def on_error(ws, error):
            print(f"[Nasdaq Stream] Error: {error}")
            if self.on_error:
                self.on_error(error)

        def on_close(ws, code, msg):
            print(f"[Nasdaq Stream] Closed: {code} {msg}")
            if self._running:
                import time; time.sleep(5)
                self._connect()  # Reconnect

        ws = websocket.WebSocketApp(
            self.WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        ws.run_forever()
