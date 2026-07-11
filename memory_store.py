import sqlite3
import json
import hashlib
import re
from datetime import datetime, timedelta
from contextlib import contextmanager
from werkzeug.security import generate_password_hash, check_password_hash
from config import DB_PATH


def _legacy_sha256(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _is_legacy_hash(pw_hash: str) -> bool:
    # Legacy hashes are raw 64-char hex SHA-256; werkzeug hashes are "method$salt$hash".
    return "$" not in pw_hash


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME,
            preferences TEXT DEFAULT '{}',
            oauth_github_id TEXT,
            oauth_google_sub TEXT
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            UNIQUE(user_id, symbol),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            shares REAL DEFAULT 0,
            avg_cost REAL DEFAULT 0,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, symbol),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS user_interests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            interest_score REAL DEFAULT 1.0,
            view_count INTEGER DEFAULT 0,
            last_viewed DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, symbol),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL,
            asset TEXT,
            content TEXT,
            author TEXT,
            sentiment_score REAL,
            signal_type TEXT,
            sentiment_model TEXT DEFAULT 'vader',
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            period_start DATETIME,
            period_end DATETIME,
            content TEXT,
            key_signals TEXT,
            overall_sentiment REAL,
            risk_level TEXT,
            signal_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            metric TEXT,
            value REAL,
            trend_direction TEXT
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            level TEXT,
            title TEXT,
            message TEXT,
            asset TEXT,
            acknowledged INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS feature_backlog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT DEFAULT 'general',
            implementation_spec TEXT,
            priority INTEGER DEFAULT 3,
            estimated_hours REAL DEFAULT 2,
            impact_score REAL DEFAULT 5.0,
            status TEXT DEFAULT 'proposed',
            proposed_by TEXT DEFAULT 'rnd_cycle',
            implementation_notes TEXT,
            proposed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS consent_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            policy_version TEXT NOT NULL,
            ip_hash TEXT,
            consented_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guid TEXT UNIQUE,
            title TEXT NOT NULL,
            summary TEXT,
            url TEXT,
            source TEXT,
            category TEXT DEFAULT 'market',
            tickers TEXT,
            sentiment_score REAL DEFAULT 0.0,
            sentiment_model TEXT DEFAULT 'vader',
            published_at DATETIME,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT UNIQUE,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            symbol TEXT,
            event_date TEXT NOT NULL,
            event_time TEXT,
            description TEXT,
            eps_forecast TEXT,
            eps_actual TEXT,
            importance TEXT DEFAULT 'medium',
            source TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tech_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            condition TEXT NOT NULL,
            threshold REAL,
            period INTEGER DEFAULT 20,
            enabled INTEGER DEFAULT 1,
            triggered_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS ticker_info (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            sector TEXT,
            industry TEXT,
            description TEXT,
            country TEXT,
            market_cap REAL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS agent_track_record (
            agent TEXT PRIMARY KEY,
            proposals_implemented INTEGER DEFAULT 0,
            proposals_succeeded INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS signal_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT NOT NULL,
            predicted_direction TEXT NOT NULL,
            signal_count INTEGER DEFAULT 0,
            avg_sentiment REAL,
            predicted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            price_at_t0 REAL,
            price_at_4h REAL,
            price_at_24h REAL,
            price_at_72h REAL
        );

        CREATE TABLE IF NOT EXISTS correlation_matrix (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol_a TEXT NOT NULL,
            symbol_b TEXT NOT NULL,
            window_days INTEGER NOT NULL,
            correlation REAL NOT NULL,
            computed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS short_interest (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            short_float_pct REAL,
            short_ratio REAL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS insider_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            owner_name TEXT,
            owner_title TEXT,
            transaction_date TEXT,
            transaction_code TEXT,
            is_signal_code INTEGER DEFAULT 0,
            signal_type TEXT,
            shares REAL,
            price_per_share REAL,
            acquired_disposed TEXT,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, owner_name, transaction_date, transaction_code, shares)
        );

        CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
        CREATE INDEX IF NOT EXISTS idx_outcomes_asset ON signal_outcomes(asset);
        CREATE INDEX IF NOT EXISTS idx_outcomes_predicted_at ON signal_outcomes(predicted_at);
        CREATE INDEX IF NOT EXISTS idx_signals_asset ON signals(asset);
        CREATE INDEX IF NOT EXISTS idx_trends_asset ON trends(asset);
        CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
        CREATE INDEX IF NOT EXISTS idx_portfolio_user ON portfolio(user_id);
        CREATE INDEX IF NOT EXISTS idx_backlog_status ON feature_backlog(status);
        CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at);
        CREATE INDEX IF NOT EXISTS idx_news_category ON news_items(category);
        CREATE INDEX IF NOT EXISTS idx_calendar_date ON calendar_events(event_date);
        CREATE INDEX IF NOT EXISTS idx_techalerts_user ON tech_alerts(user_id);
        CREATE INDEX IF NOT EXISTS idx_correlation_window ON correlation_matrix(window_days, computed_at);
        CREATE INDEX IF NOT EXISTS idx_short_interest_symbol ON short_interest(symbol, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_insider_ticker ON insider_transactions(ticker, transaction_date);
        """)

        # Lightweight migrations for columns added after initial release —
        # CREATE TABLE IF NOT EXISTS above only covers fresh databases.
        for ddl in (
            "ALTER TABLE feature_backlog ADD COLUMN github_issue_number INTEGER",
            "ALTER TABLE users ADD COLUMN oauth_github_id TEXT",
            "ALTER TABLE users ADD COLUMN oauth_google_sub TEXT",
            "ALTER TABLE signals ADD COLUMN sentiment_model TEXT DEFAULT 'vader'",
            "ALTER TABLE news_items ADD COLUMN sentiment_model TEXT DEFAULT 'vader'",
            "ALTER TABLE signal_outcomes ADD COLUMN source TEXT DEFAULT 'aggregate'",
            "ALTER TABLE signal_outcomes ADD COLUMN baseline_direction TEXT",
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oauth_github ON users(oauth_github_id) WHERE oauth_github_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oauth_google ON users(oauth_google_sub) WHERE oauth_google_sub IS NOT NULL;
        """)

        # Seed a default admin user if none exist.
        # Password is randomised on first run — printed to console once.
        # Set FREDAI_ADMIN_PASSWORD in .env to pin a specific initial password.
        existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing == 0:
            import os, secrets as _sec
            env_pw = os.getenv("FREDAI_ADMIN_PASSWORD", "")
            initial_pw = env_pw if env_pw else _sec.token_urlsafe(16)
            pw_hash = generate_password_hash(initial_pw)
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name) VALUES (?,?,?)",
                ("admin", pw_hash, "Admin")
            )
            if not env_pw:
                print(f"\n{'='*60}")
                print(f"[Security] FredAI admin account created.")
                print(f"[Security] Username: admin")
                print(f"[Security] Password: {initial_pw}")
                print(f"[Security] SAVE THIS — it won't be shown again.")
                print(f"[Security] Set FREDAI_ADMIN_PASSWORD in .env to control this.")
                print(f"{'='*60}\n")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── AUTH ──────────────────────────────────────────────────────────────────────
def _normalize_username(username: str) -> str:
    # /register stores usernames lowercased, but login used the raw input in a
    # case-sensitive lookup — mobile keyboards auto-capitalize, so "Fred" never
    # matched "fred" and every re-login failed with "Invalid credentials".
    return (username or "").strip().lower()


def verify_user(username: str, password: str) -> dict | None:
    username = _normalize_username(username)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)
        ).fetchone()
        if not row:
            return None

        stored_hash = row["password_hash"]
        if _is_legacy_hash(stored_hash):
            if stored_hash != _legacy_sha256(password):
                return None
            # Upgrade to a salted hash now that we have the plaintext password.
            conn.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (generate_password_hash(password), row["id"]),
            )
        elif not check_password_hash(stored_hash, password):
            return None

        conn.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        return dict(row)


def create_user(username: str, password: str, display_name: str = None) -> dict | None:
    username = _normalize_username(username)
    pw_hash = generate_password_hash(password)
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name) VALUES (?,?,?)",
                (username, pw_hash, display_name or username)
            )
            row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return dict(row)
    except sqlite3.IntegrityError:
        return None


def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    username = _normalize_username(username)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_oauth(provider: str, provider_id: str) -> dict | None:
    """Look up a user by their stable OAuth provider ID — NEVER by a
    derived username string, which an attacker could pre-register via
    /register to hijack a future victim's OAuth login."""
    column = {"github": "oauth_github_id", "google": "oauth_google_sub"}[provider]
    with get_conn() as conn:
        row = conn.execute(f"SELECT * FROM users WHERE {column}=?", (provider_id,)).fetchone()
    return dict(row) if row else None


def create_oauth_user(provider: str, provider_id: str, username: str, display_name: str) -> dict | None:
    """Create a new account linked to an OAuth provider ID. If the natural
    username is already taken by an unrelated account, falls back to a
    provider-ID-suffixed username that's guaranteed unique — never reuses
    an existing account that wasn't already linked to this provider_id."""
    column = {"github": "oauth_github_id", "google": "oauth_google_sub"}[provider]
    import secrets as _secrets
    pw_hash = generate_password_hash(_secrets.token_urlsafe(32))
    candidates = [username, f"{username}_{provider_id}"]
    with get_conn() as conn:
        for candidate in candidates:
            try:
                conn.execute(
                    f"INSERT INTO users (username, password_hash, display_name, {column}) VALUES (?,?,?,?)",
                    (candidate, pw_hash, display_name, provider_id)
                )
                row = conn.execute("SELECT * FROM users WHERE username=?", (candidate,)).fetchone()
                return dict(row)
            except sqlite3.IntegrityError:
                continue
    return None


# ── WATCHLIST ─────────────────────────────────────────────────────────────────
def get_watchlist(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE user_id=? ORDER BY added_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_to_watchlist(user_id: int, symbol: str, notes: str = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO watchlist (user_id, symbol, notes) VALUES (?,?,?) ON CONFLICT(user_id,symbol) DO NOTHING",
            (user_id, symbol.upper(), notes)
        )
    bump_interest(user_id, symbol, delta=2.0)


def remove_from_watchlist(user_id: int, symbol: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE user_id=? AND symbol=?", (user_id, symbol.upper()))


# ── USER INTERESTS (ML-lite preference learning) ──────────────────────────────
def bump_interest(user_id: int, symbol: str, delta: float = 1.0):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO user_interests (user_id, symbol, interest_score, view_count)
               VALUES (?,?,?,1)
               ON CONFLICT(user_id,symbol) DO UPDATE SET
                 interest_score = MIN(interest_score + ?, 100.0),
                 view_count = view_count + 1,
                 last_viewed = CURRENT_TIMESTAMP""",
            (user_id, symbol.upper(), delta, delta)
        )


def get_user_interests(user_id: int, limit: int = 20) -> list[dict]:
    """Return ranked list of user's interest scores per symbol."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM user_interests WHERE user_id=? ORDER BY interest_score DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def decay_interests(user_id: int, decay: float = 0.98):
    """Apply time decay to interest scores (call periodically)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE user_interests SET interest_score = interest_score * ? WHERE user_id=?",
            (decay, user_id)
        )


# ── PORTFOLIO ─────────────────────────────────────────────────────────────────
def upsert_portfolio(user_id: int, symbol: str, shares: float, avg_cost: float):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO portfolio (user_id, symbol, shares, avg_cost) VALUES (?,?,?,?)
               ON CONFLICT(user_id,symbol) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost""",
            (user_id, symbol.upper(), shares, avg_cost)
        )
    bump_interest(user_id, symbol, delta=3.0)


def get_portfolio(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio WHERE user_id=? AND shares > 0", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── SIGNALS ───────────────────────────────────────────────────────────────────
def insert_signal(source, content, asset=None, author=None, sentiment_score=0.0, signal_type="neutral", sentiment_model="vader", metadata=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO signals (source, asset, content, author, sentiment_score, signal_type, sentiment_model, metadata) VALUES (?,?,?,?,?,?,?,?)",
            (source, asset, content, author, sentiment_score, signal_type, sentiment_model, json.dumps(metadata or {}))
        )


def get_signals(hours=4, asset=None, limit=200) -> list[dict]:
    # Space-separated to match signals.timestamp's CURRENT_TIMESTAMP default --
    # .isoformat() produces a 'T' separator, and since space (0x20) sorts below
    # 'T' (0x54) lexicographically, a same-day T-separated cutoff always
    # compares "greater than" a space-separated column value regardless of
    # actual time, silently matching zero rows (same bug class as get_news's
    # published_at fix -- see that docstring).
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        if asset:
            rows = conn.execute(
                "SELECT * FROM signals WHERE timestamp > ? AND asset = ? ORDER BY timestamp DESC LIMIT ?",
                (since, asset, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signals WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
                (since, limit)
            ).fetchall()
    return [dict(r) for r in rows]


def get_trending_assets(hours: int = 4, limit: int = 20) -> list[dict]:
    """Return assets ranked by signal volume and sentiment shift in last N hours."""
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT asset,
                COUNT(*) as signal_count,
                AVG(sentiment_score) as avg_sentiment,
                SUM(CASE WHEN signal_type='bullish' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as bullish_pct,
                MAX(timestamp) as latest
               FROM signals
               WHERE timestamp > ? AND asset IS NOT NULL
               GROUP BY asset
               ORDER BY signal_count DESC
               LIMIT ?""",
            (since, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_news_as_signals(hours: int = 4, asset: str = None, limit: int = 200) -> list[dict]:
    """Derive signal-shaped records from news_items (RSS feeds -- free, no
    paywall, already sentiment-scored via FinBERT/VADER) for use when
    X/Twitter signal volume is too sparse to be meaningful (e.g. an invalid/
    expired X bearer token). news_items can reference multiple tickers via a
    comma-separated `tickers` field; each (item, ticker) pair becomes one
    signal-shaped record here so downstream code (compute_sentiment_stats,
    trending aggregation) can treat this exactly like a real signals row."""
    items = get_news(hours=hours, limit=limit)
    results = []
    for item in items:
        tickers = [t.strip() for t in (item.get("tickers") or "").split(",") if t.strip()]
        if asset:
            if asset not in tickers:
                continue
            tickers = [asset]
        score = item.get("sentiment_score") or 0.0
        sig_type = "bullish" if score >= 0.05 else "bearish" if score <= -0.05 else "neutral"
        for t in tickers:
            results.append({
                "timestamp": item.get("published_at"),
                "source": f"news:{item.get('source') or 'unknown'}",
                "asset": t,
                "content": item.get("title"),
                "author": item.get("source"),
                "sentiment_score": score,
                "signal_type": sig_type,
                "sentiment_model": item.get("sentiment_model", "vader"),
            })
    return results[:limit]


def get_signals_with_fallback(hours: int = 4, asset: str = None, limit: int = 200, min_real: int = 5) -> list[dict]:
    """Real X/Twitter signals when there's enough volume to be meaningful;
    supplemented with news-derived signals (get_news_as_signals) when
    Twitter volume is too sparse -- e.g. an invalid/expired X bearer token
    shouldn't leave Overview/Trending/etc showing empty for a user whose
    own X credentials aren't the issue."""
    real = get_signals(hours=hours, asset=asset, limit=limit)
    if len(real) >= min_real:
        return real
    news_signals = get_news_as_signals(hours=hours, asset=asset, limit=limit)
    combined = real + news_signals
    return combined[:limit]


def get_trending_assets_with_fallback(hours: int = 4, limit: int = 20, min_real: int = 5) -> list[dict]:
    """Same fallback reasoning as get_signals_with_fallback, applied to the
    trending-assets aggregation (ranked by signal volume + sentiment)."""
    real = get_signals(hours=hours, limit=1000)
    if len(real) >= min_real:
        return get_trending_assets(hours=hours, limit=limit)

    combined = real + get_news_as_signals(hours=hours, limit=1000)
    agg: dict = {}
    for s in combined:
        a = s.get("asset")
        if not a:
            continue
        d = agg.setdefault(a, {"scores": [], "bullish": 0, "total": 0, "latest": ""})
        d["scores"].append(s.get("sentiment_score") or 0)
        d["total"] += 1
        if s.get("signal_type") == "bullish":
            d["bullish"] += 1
        ts = s.get("timestamp") or ""
        if ts > d["latest"]:
            d["latest"] = ts

    rows = [
        {
            "asset": a,
            "signal_count": d["total"],
            "avg_sentiment": sum(d["scores"]) / len(d["scores"]) if d["scores"] else 0,
            "bullish_pct": d["bullish"] * 100.0 / d["total"] if d["total"] else 0,
            "latest": d["latest"],
        }
        for a, d in agg.items()
    ]
    rows.sort(key=lambda r: r["signal_count"], reverse=True)
    return rows[:limit]


def get_sentiment_snapshot(symbols: list[str], hours: int = 24, min_real: int = 5) -> dict[str, dict]:
    """Per-symbol {avg_sentiment, signal_type, signal_count} for Watchlist/
    Portfolio/AI Universe sentiment overlays -- one shared query covering all
    requested symbols (via get_signals_with_fallback's real-or-news blend)
    rather than a separate DB round-trip per symbol."""
    if not symbols:
        return {}
    combined = get_signals_with_fallback(hours=hours, limit=2000, min_real=min_real)
    wanted = set(symbols)
    agg: dict = {}
    for s in combined:
        a = s.get("asset")
        if a not in wanted:
            continue
        d = agg.setdefault(a, {"scores": [], "bullish": 0, "bearish": 0, "total": 0})
        d["scores"].append(s.get("sentiment_score") or 0)
        d["total"] += 1
        if s.get("signal_type") == "bullish":
            d["bullish"] += 1
        elif s.get("signal_type") == "bearish":
            d["bearish"] += 1

    result = {}
    for sym in symbols:
        d = agg.get(sym)
        if not d or not d["total"]:
            continue
        avg = sum(d["scores"]) / len(d["scores"])
        sig_type = "bullish" if d["bullish"] > d["bearish"] else "bearish" if d["bearish"] > d["bullish"] else "neutral"
        result[sym] = {"avg_sentiment": round(avg, 3), "signal_type": sig_type, "signal_count": d["total"]}
    return result


def get_sentiment_timeline(hours=24, bucket_minutes=30) -> list[dict]:
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT
                strftime('%Y-%m-%dT%H:', timestamp) ||
                printf('%02d', (CAST(strftime('%M', timestamp) AS INTEGER) / ?) * ?) || ':00' as bucket,
                AVG(sentiment_score) as avg_sentiment,
                COUNT(*) as signal_count,
                SUM(CASE WHEN signal_type='bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN signal_type='bearish' THEN 1 ELSE 0 END) as bearish
            FROM signals
            WHERE timestamp > ? AND source = 'twitter'
            GROUP BY bucket ORDER BY bucket ASC""",
            (bucket_minutes, bucket_minutes, since)
        ).fetchall()
    return [dict(r) for r in rows]


# ── SUMMARIES ─────────────────────────────────────────────────────────────────
def insert_summary(period_start, period_end, content, key_signals, overall_sentiment, risk_level, signal_count):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO summaries (period_start, period_end, content, key_signals, overall_sentiment, risk_level, signal_count) VALUES (?,?,?,?,?,?,?)",
            (period_start.isoformat(), period_end.isoformat(), content, json.dumps(key_signals), overall_sentiment, risk_level, signal_count)
        )


def get_latest_summary() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM summaries ORDER BY timestamp DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def get_summaries(limit=10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM summaries ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── TRENDS ────────────────────────────────────────────────────────────────────
def insert_trend(asset, metric, value, trend_direction):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO trends (asset, metric, value, trend_direction) VALUES (?,?,?,?)",
            (asset, metric, value, trend_direction)
        )


def get_trend_history(asset, metric, hours=24) -> list[dict]:
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trends WHERE asset=? AND metric=? AND timestamp>? ORDER BY timestamp ASC",
            (asset, metric, since)
        ).fetchall()
    return [dict(r) for r in rows]


# ── BACKTESTING (signal outcome tracking) ──────────────────────────────────────
_OUTCOME_CHECKPOINTS = ("4h", "24h", "72h")


def log_signal_outcome(asset: str, predicted_direction: str, signal_count: int,
                        avg_sentiment: float, price_at_t0: float | None,
                        source: str = "aggregate", baseline_direction: str | None = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO signal_outcomes
               (asset, predicted_direction, signal_count, avg_sentiment, price_at_t0,
                source, baseline_direction)
               VALUES (?,?,?,?,?,?,?)""",
            (asset, predicted_direction, signal_count, avg_sentiment, price_at_t0,
             source, baseline_direction)
        )


def get_pending_outcomes(checkpoint: str, min_hours: float) -> list[dict]:
    """Rows where `checkpoint` hasn't been filled yet and enough time has
    passed since predicted_at for that checkpoint to be due."""
    if checkpoint not in _OUTCOME_CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {_OUTCOME_CHECKPOINTS}")
    col = f"price_at_{checkpoint}"
    cutoff = (datetime.utcnow() - timedelta(hours=min_hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_outcomes WHERE {col} IS NULL AND price_at_t0 IS NOT NULL AND predicted_at<=?",
            (cutoff,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_outcome_price(outcome_id: int, checkpoint: str, price: float):
    if checkpoint not in _OUTCOME_CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {_OUTCOME_CHECKPOINTS}")
    col = f"price_at_{checkpoint}"
    with get_conn() as conn:
        conn.execute(f"UPDATE signal_outcomes SET {col}=? WHERE id=?", (price, outcome_id))


def _score_rows(rows: list[dict], col: str, direction_field: str) -> dict | None:
    """Shared scorer: for each row, does rows[direction_field] match the
    actual price move at checkpoint `col`. Returns None if no row has a
    usable value in direction_field (e.g. baseline_direction on legacy
    pre-migration rows)."""
    scored = [r for r in rows if r.get(direction_field)]
    if not scored:
        return None
    correct = 0
    for r in scored:
        change = r[col] - r["price_at_t0"]
        actual_dir = "bullish" if change > 0 else ("bearish" if change < 0 else "neutral")
        if r[direction_field] == actual_dir:
            correct += 1
    return {"total": len(scored), "correct": correct, "accuracy_pct": round(correct / len(scored) * 100, 1)}


def get_backtest_accuracy(checkpoint: str = "24h", hours: int = 24 * 30) -> dict:
    """Of outcomes completed at this checkpoint within the lookback window,
    how often did Fred's predicted direction match the actual price move --
    broken down per signal source, and compared against the naive momentum
    baseline recorded alongside each prediction (MISSION.md Principle #4:
    a source only proves its worth if it beats doing nothing clever)."""
    if checkpoint not in _OUTCOME_CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {_OUTCOME_CHECKPOINTS}")
    col = f"price_at_{checkpoint}"
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_outcomes WHERE {col} IS NOT NULL AND predicted_at>?",
            (since,)
        ).fetchall()
    rows = [dict(r) for r in rows]

    by_source: dict[str, list[dict]] = {}
    for r in rows:
        by_source.setdefault(r.get("source") or "aggregate", []).append(r)

    sources = {}
    for src, src_rows in by_source.items():
        signal_score = _score_rows(src_rows, col, "predicted_direction")
        baseline_score = _score_rows(src_rows, col, "baseline_direction")
        if signal_score is None:
            continue
        entry = dict(signal_score)
        if baseline_score:
            entry["baseline_accuracy_pct"] = baseline_score["accuracy_pct"]
            entry["baseline_delta_pct"] = round(signal_score["accuracy_pct"] - baseline_score["accuracy_pct"], 1)
            entry["proving_value"] = not (entry["baseline_delta_pct"] <= 0 and entry["total"] >= 20)
        else:
            entry["baseline_accuracy_pct"] = None
            entry["baseline_delta_pct"] = None
            entry["proving_value"] = None
        sources[src] = entry

    aggregate = sources.get("aggregate", {"total": 0, "correct": 0, "accuracy_pct": None,
                                           "baseline_accuracy_pct": None, "baseline_delta_pct": None})
    return {
        "checkpoint": checkpoint,
        "total": aggregate["total"], "correct": aggregate["correct"], "accuracy_pct": aggregate["accuracy_pct"],
        "baseline_accuracy_pct": aggregate.get("baseline_accuracy_pct"),
        "baseline_delta_pct": aggregate.get("baseline_delta_pct"),
        "sources": sources,
    }


# ── ALERTS ────────────────────────────────────────────────────────────────────
def insert_alert(level, title, message, asset=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts (level, title, message, asset) VALUES (?,?,?,?)",
            (level, title, message, asset)
        )


# ── FEATURE BACKLOG ───────────────────────────────────────────────────────────

_DEDUP_STOPWORDS = {
    "the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "with",
    "is", "are", "this", "that", "implement", "add", "integrate", "upgrade",
    "new", "support", "via", "using", "into",
    "gemini", "claude",  # provenance markers (e.g. the "[Gemini] " title prefix), not semantic content
}


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _DEDUP_STOPWORDS and len(w) > 2}


def _find_similar_proposal(conn, title: str, description: str, category: str, threshold: float = 0.3):
    """Cheap keyword-overlap dedup across agents — catches e.g. Gemini's
    '[Gemini] FinBERT integration' matching Claude's 'FinBERT sentiment
    upgrade' even though the titles don't match exactly. Deliberately a
    Jaccard word-overlap check rather than embeddings, so it stays safe to
    run on constrained hardware (Raspberry Pi Zero, per MISSION.md)."""
    target = _tokenize(title) | _tokenize(description)
    if not target:
        return None
    candidates = conn.execute(
        "SELECT id, title, description FROM feature_backlog "
        "WHERE status IN ('proposed','in_progress') AND category=?",
        (category,)
    ).fetchall()
    for row in candidates:
        other = _tokenize(row["title"]) | _tokenize(row["description"])
        if not other:
            continue
        overlap = len(target & other) / len(target | other)
        if overlap >= threshold:
            return row["id"]
    return None


def insert_feature_proposal(title, description, category, implementation_spec="",
                             estimated_hours=2, impact_score=5.0, priority=3,
                             proposed_by="rnd_cycle") -> int:
    with get_conn() as conn:
        # Avoid exact duplicates
        existing = conn.execute("SELECT id FROM feature_backlog WHERE title=?", (title,)).fetchone()
        if existing:
            return existing["id"]

        dupe_id = _find_similar_proposal(conn, title, description, category)
        if dupe_id:
            return dupe_id

        cur = conn.execute(
            """INSERT INTO feature_backlog
               (title, description, category, implementation_spec, estimated_hours, impact_score, priority, proposed_by)
               VALUES (?,?,?,?,?,?,?,?)""",
            (title, description, category, implementation_spec, estimated_hours, impact_score, priority, proposed_by)
        )
        return cur.lastrowid


def set_github_issue_number(proposal_id: int, issue_number: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE feature_backlog SET github_issue_number=? WHERE id=?",
            (issue_number, proposal_id)
        )


def get_proposal_by_issue_number(issue_number: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM feature_backlog WHERE github_issue_number=?", (issue_number,)
        ).fetchone()
    return dict(row) if row else None


def get_track_record(agent: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_track_record WHERE agent=?", (agent,)
        ).fetchone()
    if not row:
        return {"agent": agent, "proposals_implemented": 0, "proposals_succeeded": 0}
    return dict(row)


def _bump_track_record(conn, agent: str, success: bool):
    conn.execute(
        """INSERT INTO agent_track_record (agent, proposals_implemented, proposals_succeeded)
           VALUES (?, 1, ?)
           ON CONFLICT(agent) DO UPDATE SET
             proposals_implemented = proposals_implemented + 1,
             proposals_succeeded = proposals_succeeded + excluded.proposals_succeeded,
             updated_at = CURRENT_TIMESTAMP""",
        (agent, 1 if success else 0)
    )


def get_top_proposals(status="proposed", limit=5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM feature_backlog WHERE status=? ORDER BY impact_score DESC, priority ASC LIMIT ?",
            (status, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_proposal(proposal_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM feature_backlog WHERE id=?", (proposal_id,)).fetchone()
    return dict(row) if row else None


def get_all_proposals(limit=50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM feature_backlog ORDER BY proposed_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_proposal_in_progress(proposal_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE feature_backlog SET status='in_progress', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (proposal_id,)
        )


def mark_proposal_done(proposal_id: int, success: bool, notes: str = ""):
    status = "implemented" if success else "failed"
    with get_conn() as conn:
        row = conn.execute("SELECT proposed_by FROM feature_backlog WHERE id=?", (proposal_id,)).fetchone()
        conn.execute(
            "UPDATE feature_backlog SET status=?, implementation_notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, notes, proposal_id)
        )
        if row and row["proposed_by"] in ("claude", "gemini"):
            _bump_track_record(conn, row["proposed_by"], success)


def get_recent_alerts(limit=20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── PRIVACY / GDPR / CCPA / AUSTRALIAN PRIVACY ACT ───────────────────────────

def log_consent(user_id: int, policy_version: str, ip_hash: str = None):
    """Record user's explicit consent to privacy policy (required by GDPR Art.7)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO consent_log (user_id, policy_version, ip_hash) VALUES (?,?,?)",
            (user_id, policy_version, ip_hash)
        )


def has_consent(user_id: int, policy_version: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM consent_log WHERE user_id=? AND policy_version=? LIMIT 1",
            (user_id, policy_version)
        ).fetchone()
    return row is not None


def export_user_data(user_id: int) -> dict:
    """
    GDPR Art.20 / CCPA / APP 12 — Right of access and data portability.
    Returns all data held about a user as a JSON-serializable dict.
    """
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, username, display_name, created_at, last_login, preferences FROM users WHERE id=?",
            (user_id,)
        ).fetchone()
        if not user:
            return {}

        watchlist = [dict(r) for r in conn.execute(
            "SELECT symbol, notes, added_at FROM watchlist WHERE user_id=?", (user_id,)
        ).fetchall()]

        portfolio = [dict(r) for r in conn.execute(
            "SELECT symbol, shares, avg_cost, added_at FROM portfolio WHERE user_id=?", (user_id,)
        ).fetchall()]

        interests = [dict(r) for r in conn.execute(
            "SELECT symbol, interest_score, view_count, last_viewed FROM user_interests WHERE user_id=?",
            (user_id,)
        ).fetchall()]

        consents = [dict(r) for r in conn.execute(
            "SELECT policy_version, consented_at FROM consent_log WHERE user_id=? ORDER BY consented_at DESC",
            (user_id,)
        ).fetchall()]

    return {
        "export_generated_at": datetime.utcnow().isoformat() + "Z",
        "data_controller": "FredAI (self-hosted)",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "created_at": user["created_at"],
            "last_login": user["last_login"],
        },
        "watchlist": watchlist,
        "portfolio": portfolio,
        "interests": interests,
        "consent_history": consents,
        "note": (
            "Signal data and market summaries are shared/aggregated and not linked "
            "to individual users. Chat history is stored in-memory only and is not "
            "persisted to disk."
        ),
    }


def delete_user_data(user_id: int) -> bool:
    """
    GDPR Art.17 / CCPA 'Do Not Sell' / APP 13 — Right to erasure.
    Permanently deletes all personal data for the given user.
    Signal/summary/trend data is shared (not personal) and retained.
    """
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM portfolio WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM watchlist WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM user_interests WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM consent_log WHERE user_id=?", (user_id,))
            # Anonymise rather than delete the user row to preserve referential integrity;
            # username becomes a one-way hash so the account cannot be re-identified.
            import hashlib
            anon = "deleted_" + hashlib.sha256(str(user_id).encode()).hexdigest()[:12]
            conn.execute(
                "UPDATE users SET username=?, display_name='[Deleted]', password_hash='', preferences='{}' WHERE id=?",
                (anon, user_id)
            )
        return True
    except Exception:
        return False


def prune_old_data(retention_days: int = 90):
    """
    Data minimisation (GDPR Art.5 / APP 11.2).
    Removes signals and summaries older than retention_days.
    Personal data (users, portfolio, watchlist) is never auto-pruned.
    """
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        deleted_signals = conn.execute(
            "DELETE FROM signals WHERE timestamp < ?", (cutoff,)
        ).rowcount
        deleted_summaries = conn.execute(
            "DELETE FROM summaries WHERE timestamp < ?", (cutoff,)
        ).rowcount
        deleted_trends = conn.execute(
            "DELETE FROM trends WHERE timestamp < ?", (cutoff,)
        ).rowcount
        deleted_alerts = conn.execute(
            "DELETE FROM alerts WHERE timestamp < ?", (cutoff,)
        ).rowcount
    return {
        "cutoff": cutoff,
        "deleted": {
            "signals": deleted_signals,
            "summaries": deleted_summaries,
            "trends": deleted_trends,
            "alerts": deleted_alerts,
        }
    }


def prune_stale_news(retention_hours: int = 72) -> int:
    """News is meant to drive near-term decisions -- a much shorter,
    dedicated window than prune_old_data's 90-day GDPR-style retention.
    Returns the number of rows deleted.

    published_at has two coexisting formats in the wild ("2026-07-03
    15:50:00" and "2026-07-03T15:50:00", both produced by
    news_client.py::_parse_date at different times) -- REPLACE normalizes
    the separator so string comparison against the cutoff is correct for
    both, not just whichever format happens to be more common right now."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(hours=retention_hours)).isoformat(sep=" ")
    with get_conn() as conn:
        return conn.execute(
            "DELETE FROM news_items WHERE REPLACE(published_at, 'T', ' ') < ?", (cutoff,)
        ).rowcount


# ── NEWS ──────────────────────────────────────────────────────────────────────

def upsert_news_items(items: list[dict]) -> int:
    saved = 0
    with get_conn() as conn:
        for item in items:
            try:
                d = dict(item)
                d.setdefault("sentiment_model", "vader")
                conn.execute("""
                    INSERT INTO news_items (guid, title, summary, url, source, category, tickers, sentiment_score, sentiment_model, published_at)
                    VALUES (:guid, :title, :summary, :url, :source, :category, :tickers, :sentiment_score, :sentiment_model, :published_at)
                    ON CONFLICT(guid) DO NOTHING
                """, d)
                saved += 1
            except Exception:
                pass
    return saved


def get_news(category: str = None, ticker: str = None, hours: int = 24,
             limit: int = 50, offset: int = 0) -> list[dict]:
    from datetime import datetime, timedelta
    # Space-separated to match REPLACE(published_at, 'T', ' ') below --
    # .isoformat() would produce a 'T' separator, and since space (0x20) sorts
    # below 'T' (0x54) lexicographically, a same-day T-separated cutoff would
    # always compare "less than" a space-normalized column value regardless of
    # actual time, silently matching zero rows.
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        # REPLACE normalizes published_at's two coexisting separator formats
        # ("2026-07-03 15:50:00" vs "2026-07-03T15:50:00") before comparing --
        # see prune_stale_news's docstring for why naive string comparison is
        # wrong here (space < 'T' lexicographically regardless of actual time).
        base = "SELECT * FROM news_items WHERE REPLACE(published_at, 'T', ' ') > ?"
        params: list = [cutoff]
        if category and category != "all":
            base += " AND category=?"
            params.append(category)
        if ticker:
            base += " AND (tickers LIKE ? OR title LIKE ?)"
            params += [f"%{ticker}%", f"%{ticker}%"]
        base += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [dict(r) for r in conn.execute(base, params).fetchall()]


def count_news(category: str = None, ticker: str = None, hours: int = 24) -> int:
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        base = "SELECT COUNT(*) FROM news_items WHERE REPLACE(published_at, 'T', ' ') > ?"
        params: list = [cutoff]
        if category and category != "all":
            base += " AND category=?"
            params.append(category)
        if ticker:
            base += " AND (tickers LIKE ? OR title LIKE ?)"
            params += [f"%{ticker}%", f"%{ticker}%"]
        return conn.execute(base, params).fetchone()[0]


def get_news_diverse(category: str = None, hours: int = 24, limit: int = 6) -> list[dict]:
    """A recency-ordered feed naturally lets whichever source posts most
    often (Yahoo Finance is ~49% of all stored volume) crowd out everything
    else in a small "top N" slice, which reads as a lack of real global
    breadth regardless of how balanced the underlying source list actually
    is. Round-robins one item per source (each source's own items still
    ordered by recency) instead of a flat ORDER BY, so a small preview
    genuinely reflects the diversity of what's being tracked rather than
    whichever outlet happens to publish most frequently.

    Pool must be large enough to actually contain every active source, not
    just whichever source's items happen to cluster at the very top of the
    recency ordering -- with ~20+ distinct sources typically active in a 24h
    window, a small pool (e.g. limit*8) can easily be dominated by one or two
    bursty sources before round-robin ever gets a chance to diversify anything
    (verified empirically: a limit*8 pool of 48 items contained only 12 of the
    ~23 active sources). Pulling a much larger pool costs one extra SQL query,
    not extra requests, so there's no reason to under-size it."""
    pool = get_news(category=category, hours=hours, limit=500)
    by_source: dict = {}
    for item in pool:
        by_source.setdefault(item["source"], []).append(item)
    # With ~20+ distinct sources typically active and limit usually much
    # smaller (6 for a preview), a single round-robin pass never reaches most
    # sources -- whichever ones happen to appear first in by_source's
    # insertion order (i.e. whichever had the single most recent individual
    # item) would otherwise win by pure chance, not real editorial weight.
    # Ordering sources by their own volume in this pool first means an
    # established, consistently-publishing outlet (Bloomberg, CNBC, Yahoo
    # Finance) gets priority over a source that happens to have one very
    # recent item, while round-robin still caps any single source at one
    # slot per pass so nothing can dominate the result.
    ordered_sources = sorted(by_source.keys(), key=lambda s: -len(by_source[s]))
    result = []
    while len(result) < limit and any(by_source.values()):
        for source in ordered_sources:
            if by_source[source]:
                result.append(by_source[source].pop(0))
                if len(result) >= limit:
                    break
    return result


# ── ECONOMIC CALENDAR ─────────────────────────────────────────────────────────

def upsert_calendar_events(events: list[dict]) -> int:
    saved = 0
    with get_conn() as conn:
        for ev in events:
            try:
                conn.execute("""
                    INSERT INTO calendar_events
                        (event_key, event_type, title, symbol, event_date, event_time,
                         description, eps_forecast, eps_actual, importance, source)
                    VALUES (:event_key, :event_type, :title, :symbol, :event_date, :event_time,
                            :description, :eps_forecast, :eps_actual, :importance, :source)
                    ON CONFLICT(event_key) DO UPDATE SET
                        eps_actual=excluded.eps_actual,
                        updated_at=CURRENT_TIMESTAMP
                """, ev)
                saved += 1
            except Exception:
                pass
    return saved


def get_calendar_events(days: int = 7) -> list[dict]:
    from datetime import datetime, timedelta
    today = datetime.utcnow().date().isoformat()
    end = (datetime.utcnow().date() + timedelta(days=days)).isoformat()
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM calendar_events WHERE event_date BETWEEN ? AND ? ORDER BY event_date, event_time",
            (today, end)
        ).fetchall()]


# ── TECHNICAL ALERTS ─────────────────────────────────────────────────────────

def get_tech_alerts(user_id: int) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM tech_alerts WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()]


def create_tech_alert(user_id: int, symbol: str, alert_type: str,
                      condition: str, threshold: float, period: int = 20) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tech_alerts (user_id, symbol, alert_type, condition, threshold, period)
               VALUES (?,?,?,?,?,?)""",
            (user_id, symbol.upper(), alert_type, condition, threshold, period)
        )
        return {"id": cur.lastrowid, "symbol": symbol, "alert_type": alert_type,
                "condition": condition, "threshold": threshold, "period": period}


def delete_tech_alert(user_id: int, alert_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM tech_alerts WHERE id=? AND user_id=?", (alert_id, user_id))
    return True


def mark_tech_alert_triggered(alert_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tech_alerts SET triggered_at=CURRENT_TIMESTAMP WHERE id=?", (alert_id,)
        )


def get_all_tech_alerts_enabled() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM tech_alerts WHERE enabled=1"
        ).fetchall()]


# ── TICKER INFO ───────────────────────────────────────────────────────────────

def get_ticker_info(symbol: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ticker_info WHERE symbol=?", (symbol,)).fetchone()
        return dict(row) if row else None


def upsert_ticker_info(info: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO ticker_info (symbol, name, sector, industry, description, country, market_cap)
            VALUES (:symbol, :name, :sector, :industry, :description, :country, :market_cap)
            ON CONFLICT(symbol) DO UPDATE SET
                name=excluded.name, sector=excluded.sector, industry=excluded.industry,
                description=excluded.description, country=excluded.country,
                market_cap=excluded.market_cap, updated_at=CURRENT_TIMESTAMP
        """, info)


# ── CORRELATION MATRIX ────────────────────────────────────────────────────────

def store_correlation_matrix(pairs: list[dict], window_days: int):
    """pairs: [{"symbol_a", "symbol_b", "correlation"}, ...] for one computed snapshot."""
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO correlation_matrix (symbol_a, symbol_b, window_days, correlation) VALUES (?, ?, ?, ?)",
            [(p["symbol_a"], p["symbol_b"], window_days, p["correlation"]) for p in pairs]
        )


def get_latest_correlation_matrix(window_days: int) -> list[dict]:
    with get_conn() as conn:
        latest_ts = conn.execute(
            "SELECT MAX(computed_at) FROM correlation_matrix WHERE window_days=?", (window_days,)
        ).fetchone()[0]
        if not latest_ts:
            return []
        rows = conn.execute(
            "SELECT * FROM correlation_matrix WHERE window_days=? AND computed_at=?",
            (window_days, latest_ts)
        ).fetchall()
        return [dict(r) for r in rows]


# ── SHORT INTEREST ────────────────────────────────────────────────────────────

def insert_short_interest(symbol: str, short_float_pct: float | None, short_ratio: float | None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO short_interest (symbol, short_float_pct, short_ratio) VALUES (?, ?, ?)",
            (symbol, short_float_pct, short_ratio)
        )


def get_latest_short_interest(symbol: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM short_interest WHERE symbol=? ORDER BY fetched_at DESC LIMIT 1",
            (symbol,)
        ).fetchone()
        return dict(row) if row else None


def get_short_interest_direction(symbol: str) -> str | None:
    """Short interest alone (a static % of float) has no inherent direction --
    the real signal is the trend: rising short_ratio means growing bearish
    positioning, falling means short-covering (bullish). Requires two stored
    readings; returns None (no fabricated 'neutral') when there's only one
    or the ratio hasn't moved."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT short_ratio FROM short_interest WHERE symbol=? ORDER BY fetched_at DESC LIMIT 2",
            (symbol,)
        ).fetchall()
    if len(rows) < 2 or rows[0]["short_ratio"] is None or rows[1]["short_ratio"] is None:
        return None
    latest, prior = rows[0]["short_ratio"], rows[1]["short_ratio"]
    if latest > prior:
        return "bearish"
    if latest < prior:
        return "bullish"
    return None


# ── INSIDER TRANSACTIONS (SEC Form 4) ─────────────────────────────────────────

def insert_insider_transactions(transactions: list[dict]) -> int:
    """Idempotent on (ticker, owner_name, transaction_date, transaction_code, shares) —
    safe to call repeatedly with overlapping filing history. Returns rows actually inserted."""
    if not transactions:
        return 0
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany("""
            INSERT OR IGNORE INTO insider_transactions
                (ticker, owner_name, owner_title, transaction_date, transaction_code,
                 is_signal_code, signal_type, shares, price_per_share, acquired_disposed)
            VALUES (:ticker, :owner_name, :owner_title, :transaction_date, :transaction_code,
                    :is_signal_code, :signal_type, :shares, :price_per_share, :acquired_disposed)
        """, [{**t, "is_signal_code": int(t["is_signal_code"])} for t in transactions])
        return conn.total_changes - before


def get_recent_insider_transactions(ticker: str, days: int = 90, signal_only: bool = True) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    query = "SELECT * FROM insider_transactions WHERE ticker=? AND transaction_date >= ?"
    params = [ticker, since]
    if signal_only:
        query += " AND is_signal_code=1"
    query += " ORDER BY transaction_date DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_layout_prefs(user_id: int, page: str) -> dict:
    """Per-user, per-page widget layout: which widgets are hidden and what
    order they render in. Stored inside users.preferences (same column/
    pattern as saved API keys) -- no schema migration needed."""
    user = get_user(user_id)
    if not user:
        return {"hidden": [], "order": {}}
    try:
        prefs = json.loads(user.get("preferences") or "{}")
    except Exception:
        prefs = {}
    layout = prefs.get("layout", {}).get(page, {})
    return {
        "hidden": layout.get("hidden", []),
        "order": layout.get("order", {}),
        "sizes": layout.get("sizes", {}),
    }


def save_layout_prefs(user_id: int, page: str, hidden: list, order: dict, sizes: dict | None = None) -> None:
    with get_conn() as conn:
        row = conn.execute("SELECT preferences FROM users WHERE id=?", (user_id,)).fetchone()
        try:
            prefs = json.loads(row["preferences"] or "{}") if row else {}
        except Exception:
            prefs = {}
        entry = {"hidden": hidden, "order": order, "sizes": sizes or {}}
        prefs.setdefault("layout", {})[page] = entry
        conn.execute("UPDATE users SET preferences=? WHERE id=?", (json.dumps(prefs), user_id))
