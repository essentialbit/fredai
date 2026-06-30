import os
from dotenv import load_dotenv

load_dotenv()

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
X_CONSUMER_KEY = os.getenv("X_CONSUMER_KEY")
X_CONSUMER_SECRET = os.getenv("X_CONSUMER_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "sentinel_fi_secret")
PORT = int(os.getenv("PORT", 8080))

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "sentinel.db")

# ── AI PROVIDER ───────────────────────────────────────────────────────────────
# "auto"       → Anthropic API if key set, else Ollama, else degraded mode
# "anthropic"  → Force Anthropic API (ANTHROPIC_API_KEY required)
# "ollama"     → Force local Ollama (free, on-device, no data leaves machine)
# NOTE: Claude Pro / claude.ai subscriptions are web-UI-only and cannot be used
# by third-party applications. Use ANTHROPIC_API_KEY for API access, or Ollama
# (free, local) as a zero-cost alternative that keeps all data on-device.
AI_PROVIDER = os.getenv("AI_PROVIDER", "auto")

# Ollama settings (https://ollama.com — free, runs locally)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")  # or mistral, gemma2, etc.

# Smart model routing — when using Anthropic API, use cheaper models for
# high-frequency tasks to extend API credits ~8x
ANTHROPIC_MODEL_SUMMARY = os.getenv("ANTHROPIC_MODEL_SUMMARY", "claude-haiku-4-5-20251001")  # 4h cycle
ANTHROPIC_MODEL_CHAT = os.getenv("ANTHROPIC_MODEL_CHAT", "claude-sonnet-4-6")               # user chat
ANTHROPIC_MODEL_RND = os.getenv("ANTHROPIC_MODEL_RND", "claude-opus-4-8")                   # R&D agent

# ── PRIVACY & DATA GOVERNANCE ─────────────────────────────────────────────────
# GDPR (EU) · Australian Privacy Act · US CCPA compliance
# All user data lives in SQLite on this device. Nothing is transmitted to
# external services except: (a) public ticker symbols to yfinance/Nasdaq,
# (b) anonymized market + signal context to Claude API when PRIVACY_MODE=true.
PRIVACY_MODE = os.getenv("PRIVACY_MODE", "true").lower() == "true"
STRIP_PORTFOLIO_FROM_AI = os.getenv("STRIP_PORTFOLIO_FROM_AI", "true").lower() == "true"
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "90"))
PRIVACY_POLICY_VERSION = "1.0"  # bump when policy changes to re-prompt consent

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
