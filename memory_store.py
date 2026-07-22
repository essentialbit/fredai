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

        CREATE TABLE IF NOT EXISTS calibration_scores (
            source TEXT PRIMARY KEY,
            window_days INTEGER NOT NULL,
            brier REAL,
            sample_n INTEGER NOT NULL DEFAULT 0,
            reliability_weight REAL NOT NULL DEFAULT 1.0,
            low_sample INTEGER NOT NULL DEFAULT 1,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
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

        CREATE TABLE IF NOT EXISTS options_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            expiration TEXT,
            put_call_volume_ratio REAL,
            put_call_oi_ratio REAL,
            atm_iv_pct REAL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS google_trends_interest (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            keyword TEXT NOT NULL,
            interest_score REAL NOT NULL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ticker_debates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            bull_json TEXT NOT NULL,
            bear_json TEXT NOT NULL,
            verdict_json TEXT NOT NULL,
            consensus TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS vault_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            mtime REAL NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS optimized_params (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            indicator TEXT NOT NULL,
            params_json TEXT NOT NULL,
            score REAL NOT NULL,
            sample_size INTEGER NOT NULL,
            computed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, indicator)
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

        CREATE TABLE IF NOT EXISTS volume_anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            count INTEGER NOT NULL,
            z_score REAL NOT NULL,
            level TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, date)
        );


        CREATE TABLE IF NOT EXISTS onchain_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric TEXT NOT NULL,
            latest_value REAL,
            baseline_mean REAL,
            z_score REAL,
            direction TEXT,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );


        CREATE TABLE IF NOT EXISTS seasonality_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            period_type TEXT NOT NULL,
            period_value INTEGER NOT NULL,
            period_name TEXT,
            sample_size INTEGER,
            avg_return_pct REAL,
            hit_rate_pct REAL,
            computed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, period_type, period_value)
        );


        CREATE TABLE IF NOT EXISTS institutional_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manager TEXT NOT NULL,
            cik TEXT NOT NULL,
            issuer TEXT NOT NULL,
            ticker TEXT,
            cusip TEXT,
            shares REAL,
            value_usd REAL,
            filing_period TEXT,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(manager, cusip, filing_period, shares)
        );

        CREATE TABLE IF NOT EXISTS market_debates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            debate_date TEXT NOT NULL,
            bull_case TEXT,
            bear_case TEXT,
            verdict TEXT,
            confidence REAL,
            signals_snapshot TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, debate_date)
        );

        CREATE TABLE IF NOT EXISTS hypotheses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            thesis TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            horizon_days INTEGER NOT NULL,
            price_at_creation REAL,
            benchmark_at_creation REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolves_at DATETIME NOT NULL,
            resolved_at DATETIME,
            price_at_resolution REAL,
            benchmark_at_resolution REAL,
            actual_return REAL,
            benchmark_return REAL,
            outcome TEXT
        );

        CREATE TABLE IF NOT EXISTS analyst_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            firm TEXT,
            action TEXT,
            from_grade TEXT,
            to_grade TEXT,
            price_target REAL,
            prior_price_target REAL,
            graded_at TEXT,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, firm, graded_at, action)
        );

        CREATE TABLE IF NOT EXISTS filing_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            company TEXT,
            cik TEXT,
            accession_number TEXT NOT NULL,
            filed_date TEXT,
            item_codes TEXT,
            item_summary TEXT,
            signal_type TEXT,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(accession_number)
        );

        CREATE TABLE IF NOT EXISTS central_bank_statements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bank TEXT NOT NULL,
            meeting_date TEXT NOT NULL,
            prior_meeting_date TEXT,
            raw_text TEXT,
            added_paragraphs TEXT,
            removed_paragraphs TEXT,
            changed_paragraphs TEXT,
            sentiment_delta REAL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bank, meeting_date)
        );

        CREATE TABLE IF NOT EXISTS earnings_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            earnings_date TEXT NOT NULL,
            eps_estimate REAL,
            reported_eps REAL,
            surprise_pct REAL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, earnings_date)
        );

        CREATE TABLE IF NOT EXISTS short_volume_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            short_volume REAL,
            total_volume REAL,
            short_volume_pct REAL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, trade_date)
        );

        CREATE TABLE IF NOT EXISTS beige_book_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_date TEXT NOT NULL UNIQUE,
            composite_score REAL NOT NULL,
            prior_score REAL,
            score_delta REAL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            user_id INTEGER,
            title TEXT,
            content TEXT NOT NULL,
            tickers TEXT DEFAULT '',
            url TEXT,
            published_at DATETIME,
            embedding TEXT,
            mtime REAL,
            indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_type, source_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(
            content, title, tickers, content='rag_chunks', content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS rag_chunks_ai AFTER INSERT ON rag_chunks BEGIN
            INSERT INTO rag_fts(rowid, content, title, tickers) VALUES (new.id, new.content, new.title, new.tickers);
        END;
        CREATE TRIGGER IF NOT EXISTS rag_chunks_ad AFTER DELETE ON rag_chunks BEGIN
            INSERT INTO rag_fts(rag_fts, rowid, content, title, tickers) VALUES ('delete', old.id, old.content, old.title, old.tickers);
        END;
        CREATE TRIGGER IF NOT EXISTS rag_chunks_au AFTER UPDATE ON rag_chunks BEGIN
            INSERT INTO rag_fts(rag_fts, rowid, content, title, tickers) VALUES ('delete', old.id, old.content, old.title, old.tickers);
            INSERT INTO rag_fts(rowid, content, title, tickers) VALUES (new.id, new.content, new.title, new.tickers);
        END;

        CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(source_type, indexed_at);
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_user ON rag_chunks(user_id);
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_published ON rag_chunks(published_at);

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
        CREATE INDEX IF NOT EXISTS idx_onchain_metric ON onchain_metrics(metric, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_seasonality_ticker ON seasonality_cache(ticker, period_type);
        CREATE INDEX IF NOT EXISTS idx_options_symbol ON options_data(symbol, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_institutional_ticker ON institutional_holdings(ticker, filing_period);
        CREATE INDEX IF NOT EXISTS idx_hypotheses_ticker ON hypotheses(ticker);
        CREATE INDEX IF NOT EXISTS idx_hypotheses_resolves_at ON hypotheses(resolves_at);
        CREATE INDEX IF NOT EXISTS idx_trends_interest_ticker ON google_trends_interest(ticker, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_analyst_ratings_ticker ON analyst_ratings(ticker, graded_at);
        CREATE INDEX IF NOT EXISTS idx_central_bank_meeting ON central_bank_statements(bank, meeting_date);
        CREATE INDEX IF NOT EXISTS idx_earnings_history_ticker ON earnings_history(ticker, earnings_date);

        CREATE TABLE IF NOT EXISTS job_listings_daily (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open_roles INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, date)
        );
        CREATE INDEX IF NOT EXISTS idx_job_listings_ticker ON job_listings_daily(ticker, date);

        CREATE TABLE IF NOT EXISTS geopolitical_risk_daily (
            date TEXT PRIMARY KEY,
            score REAL NOT NULL,
            article_count INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_short_volume_symbol ON short_volume_history(symbol, trade_date);
        CREATE INDEX IF NOT EXISTS idx_ticker_debates_ticker ON ticker_debates(ticker, created_at);
        CREATE INDEX IF NOT EXISTS idx_vault_embeddings_path ON vault_embeddings(path);
        CREATE INDEX IF NOT EXISTS idx_optimized_params_ticker ON optimized_params(ticker);
        CREATE INDEX IF NOT EXISTS idx_beige_book_release ON beige_book_sentiment(release_date);

        CREATE TABLE IF NOT EXISTS tracked_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            thesis TEXT DEFAULT '',
            confidence REAL DEFAULT 0.5,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, entity_type, name)
        );

        CREATE TABLE IF NOT EXISTS entity_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            from_entity_id INTEGER NOT NULL,
            to_entity_id INTEGER NOT NULL,
            relationship TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_entity_id, to_entity_id, relationship)
        );

        CREATE TABLE IF NOT EXISTS entity_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            source TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_tracked_entities_user ON tracked_entities(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_entity_links_from ON entity_links(from_entity_id);
        CREATE INDEX IF NOT EXISTS idx_entity_links_to ON entity_links(to_entity_id);
        CREATE INDEX IF NOT EXISTS idx_entity_evidence_entity ON entity_evidence(entity_id, created_at);
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
        cur = conn.execute(
            "INSERT INTO signals (source, asset, content, author, sentiment_score, signal_type, sentiment_model, metadata) VALUES (?,?,?,?,?,?,?,?)",
            (source, asset, content, author, sentiment_score, signal_type, sentiment_model, json.dumps(metadata or {}))
        )
        return cur.lastrowid


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
        cur = conn.execute(
            "INSERT INTO summaries (period_start, period_end, content, key_signals, overall_sentiment, risk_level, signal_count) VALUES (?,?,?,?,?,?,?)",
            (period_start.isoformat(), period_end.isoformat(), content, json.dumps(key_signals), overall_sentiment, risk_level, signal_count)
        )
        return cur.lastrowid


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


def get_outcome_rows_by_source(checkpoint: str, hours: int = 24 * 30) -> dict[str, list[dict]]:
    """Completed signal_outcomes rows at this checkpoint within the lookback
    window, grouped by source. Shared by get_backtest_accuracy (simple
    hit-rate) and calibration_engine.py (Brier scoring) so both read the
    exact same underlying rows/definition of 'completed'."""
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
    return by_source


def get_backtest_accuracy(checkpoint: str = "24h", hours: int = 24 * 30) -> dict:
    """Of outcomes completed at this checkpoint within the lookback window,
    how often did Fred's predicted direction match the actual price move --
    broken down per signal source, and compared against the naive momentum
    baseline recorded alongside each prediction (MISSION.md Principle #4:
    a source only proves its worth if it beats doing nothing clever)."""
    col = f"price_at_{checkpoint}"
    by_source = get_outcome_rows_by_source(checkpoint, hours)

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


# ── CALIBRATION (Brier scoring / reliability weights, FSI L4) ─────────────────

def upsert_calibration_score(source: str, window_days: int, brier: float | None,
                              sample_n: int, reliability_weight: float, low_sample: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO calibration_scores (source, window_days, brier, sample_n, reliability_weight, low_sample, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(source) DO UPDATE SET
                   window_days=excluded.window_days, brier=excluded.brier, sample_n=excluded.sample_n,
                   reliability_weight=excluded.reliability_weight, low_sample=excluded.low_sample,
                   updated_at=CURRENT_TIMESTAMP""",
            (source, window_days, brier, sample_n, reliability_weight, int(low_sample)),
        )


def get_calibration_scores() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM calibration_scores ORDER BY source").fetchall()
    return [dict(r) for r in rows]


def get_calibration_weight(source: str) -> float:
    """1.0 (neutral) if this source has no calibration row yet -- new
    sources, or before the first nightly compute_calibration() run, must
    never be silently dampened/amplified."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT reliability_weight FROM calibration_scores WHERE source=?", (source,)
        ).fetchone()
    return row["reliability_weight"] if row else 1.0


# ── ALERTS ────────────────────────────────────────────────────────────────────
def insert_alert(level, title, message, asset=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts (level, title, message, asset) VALUES (?,?,?,?)",
            (level, title, message, asset)
        )


def _integrity_check_result(table: str, raw_count: int, read_count: int) -> dict:
    if raw_count > 0 and read_count == 0:
        return {
            "check": table,
            "status": "alert",
            "detail": (
                f"{raw_count} row(s) written to {table} in the last hour, but the "
                f"app's own read path returned 0 for the same window -- a query "
                f"filter is likely broken, not that the source stopped producing data."
            ),
        }
    return {
        "check": table,
        "status": "ok",
        "detail": f"{table}: {raw_count} written, {read_count} readable in the last hour.",
    }


def run_data_integrity_checks() -> list[dict]:
    """Catch the write-succeeds-but-paired-read-returns-nothing failure mode
    that hit signals/news_items twice already (see get_news's and get_signals'
    own docstrings/history -- a CURRENT_TIMESTAMP-defaulted column compared
    against a mismatched separator format silently matches zero rows, no
    exception, no log line). Compares a raw COUNT(*) against each table's own
    native timestamp column (ground truth) to its normal read function's row
    count for the same 1h window. Deliberately narrow -- two tables already
    bitten by this exact bug class, not a general observability framework."""
    with get_conn() as conn:
        raw_signals = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE timestamp > datetime('now', '-1 hour')"
        ).fetchone()[0]
        raw_news = conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE REPLACE(published_at, 'T', ' ') > datetime('now', '-1 hour')"
        ).fetchone()[0]

    read_signals = len(get_signals(hours=1, limit=100000))
    read_news = len(get_news(hours=1, limit=100000))

    return [
        _integrity_check_result("signals", raw_signals, read_signals),
        _integrity_check_result("news_items", raw_news, read_news),
    ]


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


# ── OPTIONS DATA (put/call ratio + ATM IV) ─────────────────────────────────────

def insert_options_data(symbol: str, expiration: str | None, put_call_volume_ratio: float | None,
                         put_call_oi_ratio: float | None, atm_iv_pct: float | None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO options_data
               (symbol, expiration, put_call_volume_ratio, put_call_oi_ratio, atm_iv_pct)
               VALUES (?, ?, ?, ?, ?)""",
            (symbol, expiration, put_call_volume_ratio, put_call_oi_ratio, atm_iv_pct)
        )


def get_latest_options_data(symbol: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM options_data WHERE symbol=? ORDER BY fetched_at DESC LIMIT 1",
            (symbol,)
        ).fetchone()
        return dict(row) if row else None


# ── GOOGLE TRENDS SEARCH INTEREST ─────────────────────────────────────────────

def insert_trends_interest(ticker: str, keyword: str, interest_score: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO google_trends_interest (ticker, keyword, interest_score) VALUES (?, ?, ?)",
            (ticker, keyword, interest_score)
        )


def get_latest_search_interest(ticker: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM google_trends_interest WHERE ticker=? ORDER BY fetched_at DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        return dict(row) if row else None


# ── FINRA REG SHO SHORT VOLUME ────────────────────────────────────────────────

def insert_short_volume(symbol: str, trade_date: str, short_volume: float, total_volume: float, short_volume_pct: float):
    """One row per (symbol, trade_date) -- INSERT OR IGNORE keeps a same-day
    re-run of the refresh job idempotent instead of duplicating rows."""
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO short_volume_history
               (symbol, trade_date, short_volume, total_volume, short_volume_pct)
               VALUES (?, ?, ?, ?, ?)""",
            (symbol, trade_date, short_volume, total_volume, short_volume_pct)
        )


def get_short_volume_series(symbol: str, limit: int = 30) -> list[dict]:
    """Ascending by trade_date (oldest first) -- ready to feed straight into
    a rolling z-score/trend helper."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM (
                   SELECT * FROM short_volume_history WHERE symbol=?
                   ORDER BY trade_date DESC LIMIT ?
               ) ORDER BY trade_date ASC""",
            (symbol, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_beige_book_sentiment() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM beige_book_sentiment ORDER BY release_date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def insert_beige_book_sentiment(release_date: str, composite_score: float, prior_score: float | None, score_delta: float | None):
    """One row per release_date -- INSERT OR IGNORE keeps a same-release cache
    refresh idempotent instead of duplicating rows (releases are infrequent,
    ~8/year, so this only actually inserts when a genuinely new release is found)."""
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO beige_book_sentiment
               (release_date, composite_score, prior_score, score_delta)
               VALUES (?, ?, ?, ?)""",
            (release_date, composite_score, prior_score, score_delta)
        )


def get_latest_short_volume(symbol: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM short_volume_history WHERE symbol=? ORDER BY trade_date DESC LIMIT 1",
            (symbol,)
        ).fetchone()
        return dict(row) if row else None


def get_options_data_prior_pair(symbol: str) -> tuple[dict, dict] | None:
    """Latest two options_data snapshots for a symbol, newest first. Returns
    None if there's fewer than two -- shift detection needs a prior reading,
    not just a static snapshot."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM options_data WHERE symbol=? ORDER BY fetched_at DESC LIMIT 2",
            (symbol,)
        ).fetchall()
    if len(rows) < 2:
        return None
    return dict(rows[0]), dict(rows[1])


def get_search_interest_velocity(ticker: str, lookback: int = 7) -> dict | None:
    """Latest daily search-interest reading vs the trailing average of up to
    `lookback` prior readings, expressed as a % velocity. Requires at least
    two stored readings (no fabricated baseline off a single point)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT interest_score FROM google_trends_interest WHERE ticker=? "
            "ORDER BY fetched_at DESC LIMIT ?",
            (ticker, lookback + 1)
        ).fetchall()
    if len(rows) < 2:
        return None
    latest = rows[0]["interest_score"]
    prior = [r["interest_score"] for r in rows[1:]]
    avg_prior = sum(prior) / len(prior)
    if avg_prior <= 0:
        return None
    velocity_pct = (latest - avg_prior) / avg_prior * 100
    return {
        "ticker": ticker,
        "latest": latest,
        "avg_prior": round(avg_prior, 1),
        "velocity_pct": round(velocity_pct, 1),
    }


def insert_ticker_debate(ticker: str, bull: dict, bear: dict, verdict: dict):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO ticker_debates
               (ticker, bull_json, bear_json, verdict_json, consensus, confidence)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticker, json.dumps(bull), json.dumps(bear), json.dumps(verdict),
             verdict.get("consensus"), verdict.get("confidence"))
        )
        return cur.lastrowid


def get_latest_ticker_debate(ticker: str, max_age_s: float | None = None) -> dict | None:
    """Latest persisted debate for ticker, or None if there isn't one yet
    or (when max_age_s is given) the latest one is older than that. Age is
    computed in Python against SQLite's own CURRENT_TIMESTAMP format
    ("%Y-%m-%d %H:%M:%S", space-separated, UTC) rather than a SQL WHERE
    clause -- avoids the isoformat()-vs-CURRENT_TIMESTAMP string-sort bug
    class already hit elsewhere in this file."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ticker_debates WHERE ticker=? ORDER BY created_at DESC LIMIT 1",
            (ticker,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if max_age_s is not None:
        created = datetime.strptime(d["created_at"], "%Y-%m-%d %H:%M:%S")
        if (datetime.utcnow() - created).total_seconds() > max_age_s:
            return None
    return {
        "ticker": d["ticker"],
        "bull": json.loads(d["bull_json"]),
        "bear": json.loads(d["bear_json"]),
        "verdict": json.loads(d["verdict_json"]),
        "created_at": d["created_at"],
    }


def upsert_vault_chunk(path: str, chunk_text: str, embedding: list[float], mtime: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO vault_embeddings (path, chunk_text, embedding_json, mtime) VALUES (?, ?, ?, ?)",
            (path, chunk_text, json.dumps(embedding), mtime)
        )


def get_all_vault_chunks() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT path, chunk_text, embedding_json FROM vault_embeddings").fetchall()
    return [
        {"path": r["path"], "chunk_text": r["chunk_text"], "embedding": json.loads(r["embedding_json"])}
        for r in rows
    ]


def get_vault_chunk_mtimes() -> dict:
    """Latest indexed mtime per source file, for incremental reindexing."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT path, MAX(mtime) as mtime FROM vault_embeddings GROUP BY path"
        ).fetchall()
    return {r["path"]: r["mtime"] for r in rows}


def delete_vault_chunks_for_path(path: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM vault_embeddings WHERE path=?", (path,))


def upsert_optimized_params(ticker: str, indicator: str, params: dict, score: float, sample_size: int):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO optimized_params (ticker, indicator, params_json, score, sample_size, computed_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(ticker, indicator) DO UPDATE SET
                   params_json=excluded.params_json, score=excluded.score,
                   sample_size=excluded.sample_size, computed_at=excluded.computed_at""",
            (ticker, indicator, json.dumps(params), score, sample_size)
        )


def get_optimized_params(ticker: str, indicator: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if indicator:
            rows = conn.execute(
                "SELECT * FROM optimized_params WHERE ticker=? AND indicator=?",
                (ticker, indicator)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM optimized_params WHERE ticker=?", (ticker,)
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d.pop("params_json"))
        out.append(d)
    return out


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


def insert_volume_anomaly(ticker: str, date: str, count: int, z_score: float, level: str) -> bool:
    """Idempotent per (ticker, date) -- returns False if today's row for
    this ticker already exists (already recorded/alerted, nothing to do)."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM volume_anomalies WHERE ticker=? AND date=?", (ticker, date)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO volume_anomalies (ticker, date, count, z_score, level) VALUES (?,?,?,?,?)",
            (ticker, date, count, z_score, level)
        )
        return True


def get_recent_volume_anomalies(days: int = 7) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM volume_anomalies WHERE date >= ? AND level != 'normal' ORDER BY date DESC",
            (since,)
        ).fetchall()
        return [dict(r) for r in rows]




# ── BITCOIN ON-CHAIN METRICS ────────────────────────────────────────────────────

def insert_onchain_metric(metric: str, trend: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO onchain_metrics (metric, latest_value, baseline_mean, z_score, direction) "
            "VALUES (?, ?, ?, ?, ?)",
            (metric, trend.get("latest"), trend.get("mean"), trend.get("z_score"), trend.get("direction"))
        )


def get_latest_onchain_metrics() -> dict:
    """{"hash_rate": {...}, "active_addresses": {...}} -- most recent row per
    metric, or {} if the daily refresh job hasn't populated anything yet."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT m.* FROM onchain_metrics m
            INNER JOIN (
                SELECT metric, MAX(fetched_at) AS max_fetched
                FROM onchain_metrics GROUP BY metric
            ) latest ON m.metric = latest.metric AND m.fetched_at = latest.max_fetched
        """).fetchall()
        return {r["metric"]: dict(r) for r in rows}


# ── SEASONALITY ────────────────────────────────────────────────────────────────

def save_seasonal_bias(ticker: str, bias: dict) -> None:
    """Upserts every period in a seasonality_engine.compute_seasonal_bias()
    result. Stores all 12 months + up to 7 weekdays so `/api/seasonality`
    lookups are always cache-hits regardless of what day it is."""
    if bias.get("status") != "ok":
        return
    rows = [("month", p) for p in bias.get("months", [])] + [("dow", p) for p in bias.get("weekdays", [])]
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO seasonality_cache
                (ticker, period_type, period_value, period_name, sample_size, avg_return_pct, hit_rate_pct, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(ticker, period_type, period_value) DO UPDATE SET
                period_name=excluded.period_name,
                sample_size=excluded.sample_size,
                avg_return_pct=excluded.avg_return_pct,
                hit_rate_pct=excluded.hit_rate_pct,
                computed_at=CURRENT_TIMESTAMP
        """, [
            (ticker, period_type, p["period_value"], p["period_name"], p["sample_size"], p["avg_return_pct"], p["hit_rate_pct"])
            for period_type, p in rows
        ])


def get_current_seasonality(ticker: str) -> dict:
    """Cache-only: this calendar month's bias + today's day-of-week bias for
    `ticker`. Never triggers a live fetch -- weekly refresh job keeps this warm."""
    now = datetime.utcnow()
    with get_conn() as conn:
        month_row = conn.execute(
            "SELECT * FROM seasonality_cache WHERE ticker=? AND period_type='month' AND period_value=?",
            (ticker, now.month),
        ).fetchone()
        dow_row = conn.execute(
            "SELECT * FROM seasonality_cache WHERE ticker=? AND period_type='dow' AND period_value=?",
            (ticker, now.weekday()),
        ).fetchone()
    return {
        "ticker": ticker,
        "month": dict(month_row) if month_row else None,
        "day_of_week": dict(dow_row) if dow_row else None,
    }


# ── INSTITUTIONAL HOLDINGS (SEC Form 13F-HR) ──────────────────────────────────

def insert_institutional_holdings(holdings: list[dict]) -> int:
    """Idempotent on (manager, cusip, filing_period, shares) -- safe to call
    repeatedly with overlapping filing history. Returns rows actually inserted."""
    if not holdings:
        return 0
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany("""
            INSERT OR IGNORE INTO institutional_holdings
                (manager, cik, issuer, ticker, cusip, shares, value_usd, filing_period)
            VALUES (:manager, :cik, :issuer, :ticker, :cusip, :shares, :value_usd, :filing_period)
        """, holdings)
        return conn.total_changes - before


def get_institutional_holdings_for_symbol(ticker: str) -> list[dict]:
    """Which curated managers currently hold this ticker, per each manager's
    own most recent filing_period on file (managers file on independent
    schedules, so this is NOT one global latest quarter)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM institutional_holdings h
            WHERE h.ticker = ? AND h.filing_period = (
                SELECT MAX(h2.filing_period) FROM institutional_holdings h2
                WHERE h2.manager = h.manager
            )
            ORDER BY manager, value_usd DESC
        """, (ticker.upper(),)).fetchall()
        return [dict(r) for r in rows]


def get_market_debate(ticker: str, debate_date: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM market_debates WHERE ticker=? AND debate_date=?",
            (ticker, debate_date)
        ).fetchone()
        return dict(row) if row else None


def save_market_debate(ticker: str, debate_date: str, bull_case: str, bear_case: str,
                        verdict: str, confidence: float, signals_snapshot: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO market_debates (ticker, debate_date, bull_case, bear_case, verdict, confidence, signals_snapshot)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(ticker, debate_date) DO UPDATE SET
                   bull_case=excluded.bull_case, bear_case=excluded.bear_case,
                   verdict=excluded.verdict, confidence=excluded.confidence,
                   signals_snapshot=excluded.signals_snapshot""",
            (ticker, debate_date, bull_case, bear_case, verdict, confidence, signals_snapshot)
        )


# ── HYPOTHESIS TESTING LOOP (FSI L4) ────────────────────────────────────────
def insert_hypothesis(ticker: str, thesis: str, direction: str, confidence: float,
                       horizon_days: int, price_at_creation: float | None,
                       benchmark_at_creation: float | None) -> int:
    resolves_at = datetime.utcnow() + timedelta(days=horizon_days)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO hypotheses
               (ticker, thesis, direction, confidence, horizon_days,
                price_at_creation, benchmark_at_creation, resolves_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (ticker, thesis, direction, confidence, horizon_days,
             price_at_creation, benchmark_at_creation, resolves_at.isoformat()),
        )
        return cur.lastrowid


def count_hypotheses_since(since: datetime) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM hypotheses WHERE created_at>=?", (since.isoformat(),)
        ).fetchone()
    return row[0]


def get_open_hypothesis_tickers() -> set[str]:
    """Tickers with an unresolved hypothesis -- used to avoid stacking a new
    thesis on top of one that hasn't played out yet."""
    with get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT ticker FROM hypotheses WHERE resolved_at IS NULL").fetchall()
    return {r[0] for r in rows}


def get_due_hypotheses() -> list[dict]:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM hypotheses WHERE resolved_at IS NULL AND resolves_at<=?",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def resolve_hypothesis(hypothesis_id: int, price_at_resolution: float,
                        benchmark_at_resolution: float | None, outcome: str,
                        actual_return: float | None, benchmark_return: float | None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE hypotheses SET resolved_at=?, price_at_resolution=?,
               benchmark_at_resolution=?, outcome=?, actual_return=?, benchmark_return=?
               WHERE id=?""",
            (datetime.utcnow().isoformat(), price_at_resolution, benchmark_at_resolution,
             outcome, actual_return, benchmark_return, hypothesis_id),
        )


def get_hypotheses(status: str = "all", limit: int = 100) -> list[dict]:
    query = "SELECT * FROM hypotheses"
    if status == "open":
        query += " WHERE resolved_at IS NULL"
    elif status == "resolved":
        query += " WHERE resolved_at IS NOT NULL"
    query += " ORDER BY created_at DESC LIMIT ?"
    with get_conn() as conn:
        rows = conn.execute(query, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_hypothesis_calibration() -> dict:
    """Rolling accuracy by confidence bucket: is Fred's stated 0.8 confidence
    actually right ~80% of the time? Distinct from backtest's raw per-signal
    accuracy -- this grades Fred's own calibration, not a signal source."""
    buckets = [(0.0, 0.5), (0.5, 0.65), (0.65, 0.8), (0.8, 0.95), (0.95, 1.01)]
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT confidence, outcome FROM hypotheses WHERE resolved_at IS NOT NULL"
        ).fetchall()
    rows = [dict(r) for r in rows]
    result = []
    for lo, hi in buckets:
        in_bucket = [r for r in rows if lo <= r["confidence"] < hi]
        if not in_bucket:
            continue
        correct = sum(1 for r in in_bucket if r["outcome"] == "correct")
        result.append({
            "confidence_range": f"{lo:.2f}-{hi:.2f}",
            "total": len(in_bucket),
            "correct": correct,
            "actual_accuracy_pct": round(correct / len(in_bucket) * 100, 1),
        })
    return {
        "total_resolved": len(rows),
        "overall_accuracy_pct": (
            round(sum(1 for r in rows if r["outcome"] == "correct") / len(rows) * 100, 1)
            if rows else None
        ),
        "buckets": result,
    }


# ── ANALYST RATINGS ───────────────────────────────────────────────────────────

def insert_analyst_ratings(ratings: list[dict]) -> int:
    """Idempotent on (ticker, firm, graded_at, action) -- safe to call
    repeatedly with overlapping upgrade/downgrade history."""
    if not ratings:
        return 0
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany("""
            INSERT OR IGNORE INTO analyst_ratings
                (ticker, firm, action, from_grade, to_grade, price_target, prior_price_target, graded_at)
            VALUES (:ticker, :firm, :action, :from_grade, :to_grade, :price_target, :prior_price_target, :graded_at)
        """, ratings)
        return conn.total_changes - before


def get_recent_analyst_ratings(ticker: str, days: int = 90, limit: int = 10) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM analyst_ratings WHERE ticker=? AND graded_at >= ? ORDER BY graded_at DESC LIMIT ?",
            (ticker, since, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ── FILING EVENTS (SEC 8-K real-time monitor) ─────────────────────────────────

def insert_filing_events(filings: list[dict]) -> int:
    """Idempotent on accession_number — safe to call repeatedly against the
    same rolling feed window. Returns rows actually inserted."""
    if not filings:
        return 0
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany("""
            INSERT OR IGNORE INTO filing_events
                (ticker, company, cik, accession_number, filed_date,
                 item_codes, item_summary, signal_type)
            VALUES (:ticker, :company, :cik, :accession_number, :filed_date,
                    :item_codes, :item_summary, :signal_type)
        """, filings)
        return conn.total_changes - before


def get_recent_filing_events(ticker: str, days: int = 30, material_only: bool = False) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    query = "SELECT * FROM filing_events WHERE ticker=? AND filed_date >= ?"
    params = [ticker, since]
    if material_only:
        query += " AND signal_type='material'"
    query += " ORDER BY filed_date DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ── CENTRAL BANK STATEMENT DELTAS ────────────────────────────────────────────

def save_central_bank_statement(bank: str, meeting_date: str, prior_meeting_date: str | None,
                                 raw_text: str, delta: dict) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO central_bank_statements
                (bank, meeting_date, prior_meeting_date, raw_text, added_paragraphs,
                 removed_paragraphs, changed_paragraphs, sentiment_delta, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(bank, meeting_date) DO UPDATE SET
                prior_meeting_date=excluded.prior_meeting_date,
                raw_text=excluded.raw_text,
                added_paragraphs=excluded.added_paragraphs,
                removed_paragraphs=excluded.removed_paragraphs,
                changed_paragraphs=excluded.changed_paragraphs,
                sentiment_delta=excluded.sentiment_delta,
                fetched_at=CURRENT_TIMESTAMP
        """, (
            bank, meeting_date, prior_meeting_date, raw_text,
            json.dumps(delta.get("added", [])),
            json.dumps(delta.get("removed", [])),
            json.dumps(delta.get("changed", [])),
            delta.get("sentiment_delta"),
        ))


def _hydrate_central_bank_row(row) -> dict:
    d = dict(row)
    d["added_paragraphs"] = json.loads(d["added_paragraphs"] or "[]")
    d["removed_paragraphs"] = json.loads(d["removed_paragraphs"] or "[]")
    d["changed_paragraphs"] = json.loads(d["changed_paragraphs"] or "[]")
    return d


def get_central_bank_statement(bank: str, meeting_date: str | None) -> dict | None:
    if not meeting_date:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM central_bank_statements WHERE bank=? AND meeting_date=?",
            (bank, meeting_date),
        ).fetchone()
    return _hydrate_central_bank_row(row) if row else None


def get_latest_central_bank_delta(bank: str = "Fed") -> dict:
    """Cache-only -- the weekly-ish scheduled job keeps this warm, this
    never triggers a live fetch."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM central_bank_statements WHERE bank=? ORDER BY meeting_date DESC LIMIT 1",
            (bank,),
        ).fetchone()
    if not row:
        return {"bank": bank, "status": "no_data"}
    return _hydrate_central_bank_row(row)


# ── EARNINGS HISTORY (beat/miss tracking) ──────────────────────────────────────

def insert_earnings_history(rows: list[dict]) -> int:
    """Idempotent on (ticker, earnings_date) -- safe to call repeatedly with
    overlapping quarter history. Returns rows actually inserted."""
    if not rows:
        return 0
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany("""
            INSERT OR IGNORE INTO earnings_history
                (ticker, earnings_date, eps_estimate, reported_eps, surprise_pct)
            VALUES (:ticker, :earnings_date, :eps_estimate, :reported_eps, :surprise_pct)
        """, rows)
        return conn.total_changes - before


def get_earnings_history(ticker: str, limit: int = 12) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM earnings_history WHERE ticker=? ORDER BY earnings_date DESC LIMIT ?",
            (ticker, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_earnings_beat_rate(ticker: str, limit: int = 12) -> dict | None:
    """Beat-rate base rate over the last `limit` reported quarters, e.g.
    'beat in 9 of last 12 quarters, average surprise +4.2%'. Returns None
    (no fabricated 0%) when there's no stored history for this ticker."""
    history = get_earnings_history(ticker, limit=limit)
    if not history:
        return None
    beats = sum(1 for h in history if (h["surprise_pct"] or 0) > 0)
    misses = sum(1 for h in history if (h["surprise_pct"] or 0) < 0)
    surprises = [h["surprise_pct"] for h in history if h["surprise_pct"] is not None]
    return {
        "quarters": len(history),
        "beats": beats,
        "misses": misses,
        "inline": len(history) - beats - misses,
        "beat_rate_pct": round(beats * 100.0 / len(history), 1),
        "avg_surprise_pct": round(sum(surprises) / len(surprises), 2) if surprises else None,
    }


def record_job_listings_daily(ticker: str, date: str, open_roles: int) -> bool:
    """Idempotent per (ticker, date) -- returns False if today's row for
    this ticker already exists (already recorded this cycle, nothing to do)."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT date FROM job_listings_daily WHERE ticker=? AND date=?", (ticker, date)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO job_listings_daily (ticker, date, open_roles) VALUES (?,?,?)",
            (ticker, date, open_roles)
        )
        return True


def get_job_listings_history(ticker: str, days: int = 90) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM job_listings_daily WHERE ticker=? AND date >= ? ORDER BY date ASC",
            (ticker, since)
        ).fetchall()
        return [dict(r) for r in rows]


def record_geopolitical_risk_daily(date: str, score: float, article_count: int) -> bool:
    """Idempotent per date -- returns False if today's row already exists
    (already recorded this cycle, nothing to do)."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT date FROM geopolitical_risk_daily WHERE date=?", (date,)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO geopolitical_risk_daily (date, score, article_count) VALUES (?,?,?)",
            (date, score, article_count)
        )
        return True


def get_geopolitical_risk_history(days: int = 90) -> list[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM geopolitical_risk_daily WHERE date >= ? ORDER BY date ASC",
            (since,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_layout_prefs(user_id: int, page: str) -> dict:
    """Per-user, per-page widget layout: which widgets are hidden and what
    order they render in. Stored inside users.preferences (same column/
    pattern as saved API keys) -- no schema migration needed."""
    user = get_user(user_id)
    if not user:
        return {"hidden": [], "order": {}, "state": {}}
    try:
        prefs = json.loads(user.get("preferences") or "{}")
    except Exception:
        prefs = {}
    layout = prefs.get("layout", {}).get(page, {})
    return {
        "hidden": layout.get("hidden", []),
        "order": layout.get("order", {}),
        "sizes": layout.get("sizes", {}),
        "state": layout.get("state", {}),
    }


def save_layout_prefs(user_id: int, page: str, hidden: list, order: dict,
                      sizes: dict | None = None, state: dict | None = None) -> None:
    with get_conn() as conn:
        row = conn.execute("SELECT preferences FROM users WHERE id=?", (user_id,)).fetchone()
        try:
            prefs = json.loads(row["preferences"] or "{}") if row else {}
        except Exception:
            prefs = {}
        # Widget-toggle saves don't always send sizes/state; keep whatever was there.
        prior = prefs.get("layout", {}).get(page, {})
        entry = {"hidden": hidden, "order": order}
        entry["sizes"] = sizes if sizes is not None else prior.get("sizes", {})
        if state is not None:
            entry["state"] = state
        elif "state" in prior:
            entry["state"] = prior["state"]
        prefs.setdefault("layout", {})[page] = entry
        conn.execute("UPDATE users SET preferences=? WHERE id=?", (json.dumps(prefs), user_id))
