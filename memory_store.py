import sqlite3
import json
from datetime import datetime, timedelta
from contextlib import contextmanager
from config import DB_PATH


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
            preferences TEXT DEFAULT '{}'
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

        CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
        CREATE INDEX IF NOT EXISTS idx_signals_asset ON signals(asset);
        CREATE INDEX IF NOT EXISTS idx_trends_asset ON trends(asset);
        CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
        CREATE INDEX IF NOT EXISTS idx_portfolio_user ON portfolio(user_id);
        CREATE INDEX IF NOT EXISTS idx_backlog_status ON feature_backlog(status);
        CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at);
        CREATE INDEX IF NOT EXISTS idx_news_category ON news_items(category);
        CREATE INDEX IF NOT EXISTS idx_calendar_date ON calendar_events(event_date);
        CREATE INDEX IF NOT EXISTS idx_techalerts_user ON tech_alerts(user_id);
        """)

        # Seed a default admin user if none exist.
        # Password is randomised on first run — printed to console once.
        # Set FREDAI_ADMIN_PASSWORD in .env to pin a specific initial password.
        existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing == 0:
            import hashlib, os, secrets as _sec
            env_pw = os.getenv("FREDAI_ADMIN_PASSWORD", "")
            initial_pw = env_pw if env_pw else _sec.token_urlsafe(16)
            pw_hash = hashlib.sha256(initial_pw.encode()).hexdigest()
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
    import hashlib
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND password_hash=?", (username, pw_hash)
        ).fetchone()
        if row:
            conn.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
            return dict(row)
    return None


def create_user(username: str, password: str, display_name: str = None) -> dict | None:
    import hashlib
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
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
def insert_signal(source, content, asset=None, author=None, sentiment_score=0.0, signal_type="neutral", metadata=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO signals (source, asset, content, author, sentiment_score, signal_type, metadata) VALUES (?,?,?,?,?,?,?)",
            (source, asset, content, author, sentiment_score, signal_type, json.dumps(metadata or {}))
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


# ── ALERTS ────────────────────────────────────────────────────────────────────
def insert_alert(level, title, message, asset=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts (level, title, message, asset) VALUES (?,?,?,?)",
            (level, title, message, asset)
        )


# ── FEATURE BACKLOG ───────────────────────────────────────────────────────────

def insert_feature_proposal(title, description, category, implementation_spec="",
                             estimated_hours=2, impact_score=5.0, priority=3,
                             proposed_by="rnd_cycle"):
    with get_conn() as conn:
        # Avoid exact duplicates
        existing = conn.execute("SELECT id FROM feature_backlog WHERE title=?", (title,)).fetchone()
        if existing:
            return existing["id"]
        conn.execute(
            """INSERT INTO feature_backlog
               (title, description, category, implementation_spec, estimated_hours, impact_score, priority, proposed_by)
               VALUES (?,?,?,?,?,?,?,?)""",
            (title, description, category, implementation_spec, estimated_hours, impact_score, priority, proposed_by)
        )


def get_top_proposals(status="proposed", limit=5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM feature_backlog WHERE status=? ORDER BY impact_score DESC, priority ASC LIMIT ?",
            (status, limit)
        ).fetchall()
    return [dict(r) for r in rows]


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
        conn.execute(
            "UPDATE feature_backlog SET status=?, implementation_notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, notes, proposal_id)
        )


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
                conn.execute("""
                    INSERT INTO news_items (guid, title, summary, url, source, category, tickers, sentiment_score, published_at)
                    VALUES (:guid, :title, :summary, :url, :source, :category, :tickers, :sentiment_score, :published_at)
                    ON CONFLICT(guid) DO NOTHING
                """, item)
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
