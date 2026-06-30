import os
from dotenv import load_dotenv

load_dotenv()

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
X_CONSUMER_KEY = os.getenv("X_CONSUMER_KEY")
X_CONSUMER_SECRET = os.getenv("X_CONSUMER_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", "sentinel_fi_secret")
PORT = int(os.getenv("PORT", 8080))

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "sentinel.db")

WATCHLIST = [
    "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "META", "GOOGL",
    "JPM", "GS", "BAC",
    "SPY", "QQQ",
    "BTC-USD", "ETH-USD",
]

DISPLAY_SYMBOLS = {
    "AAPL": "Apple", "TSLA": "Tesla", "NVDA": "NVIDIA", "MSFT": "Microsoft",
    "AMZN": "Amazon", "META": "Meta", "GOOGL": "Alphabet",
    "JPM": "JPMorgan", "GS": "Goldman Sachs", "BAC": "Bank of America",
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq ETF",
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
}

X_SEARCH_QUERIES = [
    "$AAPL OR $TSLA OR $NVDA OR $MSFT OR $AMZN OR $META OR $GOOGL",
    "$SPY OR $QQQ OR $BTC OR $ETH OR #bitcoin OR #crypto",
    "#stocks OR #investing OR #trading lang:en",
    "federal reserve OR \"interest rate\" OR inflation OR \"earnings\" lang:en",
]

NASDAQ_API_KEY = os.getenv("NASDAQ_API_KEY", "")

SCAN_INTERVAL_HOURS = 4
MARKET_REFRESH_SECONDS = 60
SIGNAL_FETCH_LIMIT = 100
