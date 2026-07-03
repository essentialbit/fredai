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
        """)

        # Lightweight migrations for columns added after initial release —
        # CREATE TABLE IF NOT EXISTS above only covers fresh databases.
        for ddl in (
            "ALTER TABLE feature_backlog ADD COLUMN github_issue_number INTEGER",
            "ALTER TABLE users ADD COLUMN oauth_github_id TEXT",
            "ALTER TABLE users ADD COLUMN oauth_google_sub TEXT",
            "ALTER TABLE signals ADD COLUMN sentiment_model TEXT DEFAULT 'vader'",
            "ALTER TABLE news_items ADD COLUMN sentiment_model TEXT DEFAULT 'vader'",
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
def verify_user(username: str, password: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
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
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
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
    since = datetime.utcnow() - timedelta(hours=hours)
    with get_conn() as conn:
        if asset:
            rows = conn.execute(
                "SELECT * FROM signals WHERE timestamp > ? AND asset = ? ORDER BY timestamp DESC LIMIT ?",
                (since.isoformat(), asset, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signals WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
                (since.isoformat(), limit)
            ).fetchall()
    return [dict(r) for r in rows]


def get_trending_assets(hours: int = 4, limit: int = 20) -> list[dict]:
    """Return assets ranked by signal volume and sentiment shift in last N hours."""
    since = datetime.utcnow() - timedelta(hours=hours)
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
            (since.isoformat(), limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_sentiment_timeline(hours=24, bucket_minutes=30) -> list[dict]:
    since = datetime.utcnow() - timedelta(hours=hours)
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
            (bucket_minutes, bucket_minutes, since.isoformat())
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
    since = datetime.utcnow() - timedelta(hours=hours)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trends WHERE asset=? AND metric=? AND timestamp>? ORDER BY timestamp ASC",
            (asset, metric, since.isoformat())
        ).fetchall()
    return [dict(r) for r in rows]


# ── BACKTESTING (signal outcome tracking) ──────────────────────────────────────
_OUTCOME_CHECKPOINTS = ("4h", "24h", "72h")


def log_signal_outcome(asset: str, predicted_direction: str, signal_count: int,
                        avg_sentiment: float, price_at_t0: float | None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO signal_outcomes
               (asset, predicted_direction, signal_count, avg_sentiment, price_at_t0)
               VALUES (?,?,?,?,?)""",
            (asset, predicted_direction, signal_count, avg_sentiment, price_at_t0)
        )


def get_pending_outcomes(checkpoint: str, min_hours: float) -> list[dict]:
    """Rows where `checkpoint` hasn't been filled yet and enough time has
    passed since predicted_at for that checkpoint to be due."""
    if checkpoint not in _OUTCOME_CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {_OUTCOME_CHECKPOINTS}")
    col = f"price_at_{checkpoint}"
    cutoff = datetime.utcnow() - timedelta(hours=min_hours)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_outcomes WHERE {col} IS NULL AND price_at_t0 IS NOT NULL AND predicted_at<=?",
            (cutoff.isoformat(),)
        ).fetchall()
    return [dict(r) for r in rows]


def update_outcome_price(outcome_id: int, checkpoint: str, price: float):
    if checkpoint not in _OUTCOME_CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {_OUTCOME_CHECKPOINTS}")
    col = f"price_at_{checkpoint}"
    with get_conn() as conn:
        conn.execute(f"UPDATE signal_outcomes SET {col}=? WHERE id=?", (price, outcome_id))


def get_backtest_accuracy(checkpoint: str = "24h", hours: int = 24 * 30) -> dict:
    """Of outcomes completed at this checkpoint within the lookback window,
    how often did the predicted direction match the actual price move."""
    if checkpoint not in _OUTCOME_CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {_OUTCOME_CHECKPOINTS}")
    col = f"price_at_{checkpoint}"
    since = datetime.utcnow() - timedelta(hours=hours)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_outcomes WHERE {col} IS NOT NULL AND predicted_at>?",
            (since.isoformat(),)
        ).fetchall()
    rows = [dict(r) for r in rows]
    if not rows:
        return {"checkpoint": checkpoint, "total": 0, "correct": 0, "accuracy_pct": None}
    correct = 0
    for r in rows:
        change = r[col] - r["price_at_t0"]
        actual_dir = "bullish" if change > 0 else ("bearish" if change < 0 else "neutral")
        if r["predicted_direction"] == actual_dir:
            correct += 1
    return {
        "checkpoint": checkpoint, "total": len(rows), "correct": correct,
        "accuracy_pct": round(correct / len(rows) * 100, 1),
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
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
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
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        base = "SELECT * FROM news_items WHERE published_at > ?"
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
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        base = "SELECT COUNT(*) FROM news_items WHERE published_at > ?"
        params: list = [cutoff]
        if category and category != "all":
            base += " AND category=?"
            params.append(category)
        if ticker:
            base += " AND (tickers LIKE ? OR title LIKE ?)"
            params += [f"%{ticker}%", f"%{ticker}%"]
        return conn.execute(base, params).fetchone()[0]


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
