"""Scratch verification for causal_attribution.py -- run against a copy of the
real sentinel.db (never the live file) to confirm each catalyst source fires
on real or synthetic data and the no-catalyst fallback never fabricates."""
import os
import shutil
import sys
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

SCRATCH_DB = "/tmp/causal_attribution_verify.db"
LIVE_DB = os.path.join(PROJECT_ROOT, "data", "sentinel.db")
shutil.copy(LIVE_DB, SCRATCH_DB)

import memory_store
memory_store.DB_PATH = SCRATCH_DB
memory_store.init_db()

import causal_attribution

print("=== Test 1: no-catalyst fallback (fake symbol, no data) ===")
result = causal_attribution.attribute_move("ZZZFAKE", "price_move", 4.2, {})
assert result["catalysts"] == [], result
assert result["summary"] == "No clear catalyst found in tracked sources."
print("PASS:", result["summary"])

print("=== Test 2: earnings catalyst (synthetic calendar event) ===")
today = datetime.utcnow().date()
memory_store.upsert_calendar_events([{
    "event_key": "test_earnings_1", "event_type": "earnings",
    "title": "Test Corp Earnings (Q2)", "symbol": "TESTCO",
    "event_date": (today - timedelta(days=1)).isoformat(), "event_time": "16:30",
    "description": "After close", "eps_forecast": "1.20", "eps_actual": None,
    "importance": "HIGH", "source": "TEST",
}])
result = causal_attribution.attribute_move("TESTCO", "price_move", -6.0, {})
sources = [c["source"] for c in result["catalysts"]]
assert "earnings_calendar" in sources, result
print("PASS:", result["summary"])

print("=== Test 3: macro catalyst (synthetic FOMC event, symbol-agnostic) ===")
memory_store.upsert_calendar_events([{
    "event_key": "test_fomc_1", "event_type": "fomc",
    "title": "FOMC Meeting (Test)", "symbol": None,
    "event_date": today.isoformat(), "event_time": "14:00",
    "description": "Rate decision", "eps_forecast": None, "eps_actual": None,
    "importance": "HIGH", "source": "Federal Reserve",
}])
result = causal_attribution.attribute_move("ANYTICKER", "price_move", 3.5, {})
sources = [c["source"] for c in result["catalysts"]]
assert "macro_calendar" in sources, result
print("PASS:", result["summary"])

print("=== Test 4: insider Form 4 catalyst (synthetic transactions) ===")
memory_store.insert_insider_transactions([
    {"ticker": "INSCO", "owner_name": "Jane Exec", "owner_title": "CEO",
     "transaction_date": (today - timedelta(days=2)).isoformat(),
     "transaction_code": "P", "is_signal_code": True, "signal_type": "bullish",
     "shares": 10000, "price_per_share": 50.0, "acquired_disposed": "A"},
    {"ticker": "INSCO", "owner_name": "John Officer", "owner_title": "CFO",
     "transaction_date": (today - timedelta(days=1)).isoformat(),
     "transaction_code": "P", "is_signal_code": True, "signal_type": "bullish",
     "shares": 5000, "price_per_share": 51.0, "acquired_disposed": "A"},
])
result = causal_attribution.attribute_move("INSCO", "price_move", 4.0, {})
sources = [c["source"] for c in result["catalysts"]]
assert "insider_form4" in sources, result
print("PASS:", result["summary"])

print("=== Test 5: news catalyst (synthetic high-sentiment headlines) ===")
memory_store.upsert_news_items([
    {"guid": "test-news-1", "title": "NewsCo surges on blowout guidance",
     "summary": "", "url": "http://x", "source": "TestWire", "category": "market",
     "tickers": "NEWSCO", "sentiment_score": 0.8, "sentiment_model": "vader",
     "published_at": datetime.utcnow().isoformat()},
    {"guid": "test-news-2", "title": "NewsCo raises full-year outlook",
     "summary": "", "url": "http://x2", "source": "TestWire", "category": "market",
     "tickers": "NEWSCO", "sentiment_score": 0.7, "sentiment_model": "vader",
     "published_at": datetime.utcnow().isoformat()},
])
result = causal_attribution.attribute_move("NEWSCO", "price_move", 5.0, {})
sources = [c["source"] for c in result["catalysts"]]
assert "news" in sources, result
print("PASS:", result["summary"])

print("=== Test 6: correlation catalyst (synthetic matrix + live-shaped quotes) ===")
memory_store.store_correlation_matrix(
    [{"symbol_a": "CORRA", "symbol_b": "CORRB", "correlation": 0.85}], window_days=30
)
quotes = {"CORRA": {"change_pct": 5.0}, "CORRB": {"change_pct": 4.5}}
result = causal_attribution.attribute_move("CORRA", "price_move", 5.0, quotes)
sources = [c["source"] for c in result["catalysts"]]
assert "correlation" in sources, result
print("PASS:", result["summary"])

print("=== Test 7: ranking -- earnings (0.75) should outrank news (<=0.6) when both present ===")
memory_store.upsert_calendar_events([{
    "event_key": "test_earnings_2", "event_type": "earnings",
    "title": "NewsCo Earnings (Q2)", "symbol": "NEWSCO",
    "event_date": (today - timedelta(days=1)).isoformat(), "event_time": "16:30",
    "description": "After close", "eps_forecast": "1.00", "eps_actual": None,
    "importance": "HIGH", "source": "TEST",
}])
result = causal_attribution.attribute_move("NEWSCO", "price_move", 5.0, {})
assert result["catalysts"][0]["source"] == "earnings_calendar", result["catalysts"]
print("PASS: top catalyst is", result["catalysts"][0]["source"])

print("\nAll causal_attribution tests passed.")
os.remove(SCRATCH_DB)
