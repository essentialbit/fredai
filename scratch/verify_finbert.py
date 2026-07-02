"""Verification script for capability-gated FinBERT integration."""
import os
import sqlite3
import sys

# Add root folder to sys.path to resolve local imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory_store import init_db, get_conn
import finbert_sentiment
import twitter_client
import news_client

def test_db_migration():
    print("[Test] Initializing DB to trigger schema migrations...")
    init_db()
    
    # Check if sentiment_model exists in signals and news_items tables
    with get_conn() as conn:
        print("[Test] Verifying signals schema...")
        cursor = conn.execute("PRAGMA table_info(signals)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "sentiment_model" in columns, f"sentiment_model missing from signals columns: {columns}"
        print("  - signals table OK!")
        
        print("[Test] Verifying news_items schema...")
        cursor = conn.execute("PRAGMA table_info(news_items)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "sentiment_model" in columns, f"sentiment_model missing from news_items columns: {columns}"
        print("  - news_items table OK!")

def test_fallback_behavior():
    print("[Test] Verifying sentiment scoring fallback behavior...")
    # Since torch and transformers are not installed, analyze_sentiment should return None (fallback)
    assert not finbert_sentiment.HAS_FINBERT, "Expected HAS_FINBERT to be False (since packages are not installed)"
    
    # Twitter client scoring
    text = "AAPL reports stellar revenue numbers, market reactions bullish!"
    score, stype, model = twitter_client._score(text)
    print(f"  - Twitter client score: {score:.3f}, type: {stype}, model: {model}")
    assert model == "vader", f"Expected model 'vader', got '{model}'"
    
    # News client scoring
    score, model = news_client._score("Market surge", "Tech stocks rise rapidly on strong demand.")
    print(f"  - News client score: {score:.3f}, model: {model}")
    assert model == "vader", f"Expected model 'vader', got '{model}'"
    
    print("[Test] Fallback checks passed successfully!")

if __name__ == "__main__":
    try:
        test_db_migration()
        test_fallback_behavior()
        print("\n[SUCCESS] All FinBERT Phase 1 verification tests passed!")
    except Exception as e:
        print(f"\n[FAILURE] Verification failed: {e}")
        sys.exit(1)
