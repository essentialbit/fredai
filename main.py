import os
import json
import threading
import functools
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
from apscheduler.schedulers.background import BackgroundScheduler

import psutil as _psutil
RAM_GB = _psutil.virtual_memory().total / 1e9
LITE_MODE = RAM_GB < 1.0  # Raspberry Pi Zero / wearable companion

from config import SECRET_KEY, PORT, SCAN_INTERVAL_HOURS, MARKET_REFRESH_SECONDS, WATCHLIST, DISPLAY_SYMBOLS, FREDAI_DEPLOY_SECRET
from memory_store import (
    init_db, get_signals, get_latest_summary, get_summaries,
    get_sentiment_timeline, get_recent_alerts, insert_summary,
    get_watchlist, add_to_watchlist, remove_from_watchlist,
    get_portfolio, upsert_portfolio,
    get_user_interests, bump_interest, decay_interests,
    get_trending_assets, get_signals_with_fallback, get_trending_assets_with_fallback, get_sentiment_snapshot,
    verify_user, create_user, get_user,
    get_user_by_oauth, create_oauth_user,
    log_consent, has_consent, export_user_data, delete_user_data, prune_old_data,
)
from market_data import fetch_quotes, fetch_history, get_sector_snapshot, calculate_portfolio_value
from twitter_client import fetch_signals
from trend_detector import compute_sentiment_stats, detect_trends, get_risk_level, detect_insider_clusters, detect_short_volume_pressure
from reversal_detector import check_reversals
from agent import chat, generate_summary, generate_recommendations
from obsidian_bridge import write_summary_to_vault, write_signal_digest, vault_available
from nasdaq_client import get_macro_snapshot
from backtesting_engine import log_scan_outcomes, run_backtest_check, get_accuracy_report
from fear_greed_client import fetch_fear_greed
from copper_gold_ratio import get_copper_gold_ratio
from ppi_client import get_ppi
from retail_sales_client import get_retail_sales
from durable_goods_client import get_durable_goods_orders
from credit_spread_client import get_credit_spread
from core_pce_client import get_core_pce
from industrial_production_client import get_industrial_production
from fed_funds_futures_client import get_fed_funds_expectations
from cpi_consensus_market import get_cpi_consensus
from payrolls_consensus_market import get_payrolls_consensus
from fed_decision_market import get_fed_decision_odds
from housing_starts import get_housing_starts
from repo_funding_stress import get_repo_stress
from treasury_auction_client import get_treasury_auction_demand
from credit_oas_spread import get_credit_oas_spread
from commodity_futures_curve import get_commodity_futures_curve, most_extreme_basket
from vvix_index import get_vvix_index
from stlfsi_index import get_stlfsi_index
from consumer_sentiment import get_consumer_sentiment
from cross_market_contagion import get_cross_market_contagion
from nfci_index import get_nfci_index
from sahm_rule import get_sahm_rule
from variance_risk_premium import get_variance_risk_premium
from dollar_index_client import get_dollar_index
from oss_velocity_client import get_velocity_snapshot, TRACKED_REPOS
from crypto_fear_greed import get_crypto_fear_greed
from market_breadth import get_market_breadth
from epu_index import get_epu_index
from fed_liquidity import get_liquidity_snapshot
from breakeven_inflation import get_breakeven_inflation
from skew_index import get_skew_index
from median_home_price_client import get_median_home_price
from dark_pool_client import get_dark_pool_signal
from whale_activity import compute_whale_activity
from ticker_debate import get_ticker_debate
from lead_lag_engine import get_lead_lag
from vault_semantic_search import semantic_search, reindex_vault
from param_optimizer import optimize_universe
from memory_store import (
    get_all_proposals, insert_feature_proposal,
    get_news, get_news_diverse, count_news, upsert_news_items, prune_stale_news,
    get_calendar_events, upsert_calendar_events,
    get_tech_alerts, create_tech_alert, delete_tech_alert,
    get_ticker_info, upsert_ticker_info,
    insert_trend, get_trend_history,
    get_latest_correlation_matrix,
    get_latest_short_interest,
    get_recent_insider_transactions,
    get_layout_prefs, save_layout_prefs,
    get_optimized_params,
)
from news_client import fetch_all_news, fetch_ticker_info
from calendar_client import refresh_calendar
from technical_alerts import run_technical_alerts, get_technicals
from graph_engine import generate_assessment, _ai_assessment_cache
from cascade_engine import cascade_for_event, run_cascade_check, detect_major_moves, get_ticker_network
from signal_density import compute_signal_density, invalidate as invalidate_density
from asx_client import fetch_asx_quotes, fetch_au_news, ASX_TICKERS, ASX_SECTOR_COLORS, is_asx_ticker
from correlation_engine import refresh_correlation_matrix
from sector_rotation import get_sector_rotation
from finviz_client import refresh_short_interest
from finra_short_volume import refresh_short_volume, compute_short_volume_signal
from sec_client import fetch_form4_filings
from config import PRIVACY_POLICY_VERSION, PRIVACY_MODE, STRIP_PORTFOLIO_FROM_AI, DATA_RETENTION_DAYS, NEWS_RETENTION_HOURS, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
import installer as _installer
import updater as _updater


def _ensure_git_hooks_path():
    # Re-asserts the repo-tracked pre-commit hook (blocks .env/*.db from being
    # committed) on every startup — protects fresh clones and CI checkouts
    # where core.hooksPath was never set, since .gitignore alone didn't stop
    # .env from being force-added in the past.
    import subprocess
    repo_root = os.path.dirname(os.path.abspath(__file__))
    hooks_dir = os.path.join(repo_root, "scripts", "hooks")
    if not os.path.isdir(os.path.join(repo_root, ".git")) or not os.path.isdir(hooks_dir):
        return
    try:
        current = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if current != "scripts/hooks":
            subprocess.run(
                ["git", "config", "core.hooksPath", "scripts/hooks"],
                cwd=repo_root, timeout=5,
            )
    except Exception:
        pass  # never block app startup over hook wiring


_ensure_git_hooks_path()

_macro_cache: dict = {}

# ── AI UNIVERSE ───────────────────────────────────────────────────────────────
AI_UNIVERSE = {
    "Semiconductors": {
        "color": "#9b59ff",
        "desc": "AI compute silicon — the picks and shovels of the AI revolution",
        "tickers": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "ARM", "AMAT", "ASML", "TSM", "MRVL"],
    },
    "Cloud & Hyperscalers": {
        "color": "#00b4ff",
        "desc": "Platforms running AI at scale — compute, storage, model APIs",
        "tickers": ["MSFT", "AMZN", "GOOGL", "META", "ORCL", "IBM"],
    },
    "AI Software & SaaS": {
        "color": "#00ff88",
        "desc": "AI-native applications and enterprise AI platforms",
        "tickers": ["PLTR", "AI", "SNOW", "CRM", "NOW", "ADBE", "DDOG", "MDB"],
    },
    "AI Infrastructure": {
        "color": "#f5a623",
        "desc": "Data centers, networking, cooling — physical AI backbone",
        "tickers": ["SMCI", "VRT", "EQIX", "DLR", "AMT", "CSCO", "ANET"],
    },
    "AI Energy & Power": {
        "color": "#ff3b5c",
        "desc": "Nuclear, renewables and utilities powering AI data centers",
        "tickers": ["CEG", "VST", "NRG", "NEE", "ETR", "DUK", "SO", "CCJ"],
    },
    "Robotics & Automation": {
        "color": "#00e5cc",
        "desc": "Physical AI — autonomous systems, industrial robots, drones",
        "tickers": ["TSLA", "ISRG", "ABB", "FANUY", "KEYS", "ZBRA", "ROK"],
    },
    "AI Pure-Plays": {
        "color": "#ff9500",
        "desc": "Companies with AI as their primary business model",
        "tickers": ["PLTR", "AI", "SOUN", "BBAI", "UPST", "PATH", "RXRX"],
    },
    "Defence & Aerospace": {
        "color": "#8ba3b8",
        "desc": "Defence contractors, aerospace, and military-AI companies",
        "tickers": ["LMT", "RTX", "NOC", "GD", "BA", "KTOS", "HII", "LDOS", "CACI", "SAIC"],
    },
    "Oil, Gas & Energy": {
        "color": "#f5a623",
        "desc": "Fossil fuel majors and energy transition plays",
        "tickers": ["XOM", "CVX", "COP", "OXY", "SLB", "EOG", "PSX", "VLO", "MPC", "BP"],
    },
    "Biotech & AI Health": {
        "color": "#ff6b9d",
        "desc": "AI-driven drug discovery, genomics, and health tech",
        "tickers": ["RXRX", "ISRG", "MRNA", "ILMN", "NVAX", "CRSP", "EDIT", "BEAM", "PACB", "TMO"],
    },
    "Financial Technology": {
        "color": "#00e5cc",
        "desc": "AI-native fintech, payments, and digital banking",
        "tickers": ["V", "MA", "PYPL", "SQ", "NU", "SOFI", "AFRM", "UPST", "COIN", "HOOD"],
    },
    "Autonomous Vehicles": {
        "color": "#9b59ff",
        "desc": "Self-driving, EV, and mobility AI companies",
        "tickers": ["TSLA", "UBER", "LYFT", "RIVN", "LCID", "GM", "F", "MBLY"],
    },
    "Consumer AI": {
        "color": "#00ff88",
        "desc": "AI-powered consumer products, media, and entertainment",
        "tickers": ["AAPL", "AMZN", "GOOGL", "NFLX", "SPOT", "META", "SNAP", "PINS", "RBLX"],
    },
    "ASX — Australia": {
        "color": "#f5a623",
        "desc": "Australian Securities Exchange blue chips: banks, mining, energy, tech, healthcare",
        "tickers": [
            "BHP.AX", "CBA.AX", "CSL.AX", "WBC.AX", "ANZ.AX", "NAB.AX",
            "WES.AX", "RIO.AX", "FMG.AX", "MQG.AX", "WTC.AX", "XRO.AX",
            "WDS.AX", "STO.AX", "COH.AX", "MIN.AX", "LYC.AX", "PLS.AX",
            "PME.AX", "REA.AX", "SEK.AX", "QBE.AX", "WOW.AX", "COL.AX",
        ],
    },
}

from datetime import timedelta as _td

app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = SECRET_KEY
app.config["SESSION_COOKIE_NAME"] = "fredai_session"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
# Defaults False since this app is commonly self-hosted over plain HTTP on a
# LAN (Raspberry Pi, etc. — see MISSION.md deployment targets); the comment
# this replaced said "set True in production behind HTTPS" but there was no
# actual way to do that without editing source. Set SESSION_COOKIE_SECURE=true
# in .env once you're behind HTTPS (reverse proxy, Cloudflare Tunnel, etc.).
app.config["PERMANENT_SESSION_LIFETIME"] = _td(days=30)

# SocketIO: only allow connections from the same origin (prevents cross-origin WS abuse)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins=[])

# ── SECURITY: rate-limiting for login (in-memory, resets on restart) ──────────
import time as _time
_login_attempts: dict = {}       # ip -> [timestamps]
_LOGIN_WINDOW = 300              # 5-minute rolling window
_LOGIN_MAX = 10                  # max attempts per window


def _check_rate_limit(ip: str) -> bool:
    """Return True if this IP is allowed; False if rate-limited."""
    now = _time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    if len(attempts) >= _LOGIN_MAX:
        return False
    attempts.append(now)
    _login_attempts[ip] = attempts
    return True


# Ticker symbols (watchlist/portfolio/tech-alerts) were stored with zero
# server-side validation — a symbol containing HTML/JS was rendered back
# unescaped in the watchlist table (including inside an inline onclick
# attribute in dashboard.html), a stored-XSS path. Covers plain tickers
# (AAPL), crypto pairs (BTC-USD), and ASX suffixes (BHP.AX).
import re as _re
_SYMBOL_RE = _re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


def _valid_symbol(sym: str) -> bool:
    return bool(sym) and bool(_SYMBOL_RE.match(sym))


@app.after_request
def _security_headers(response):
    """Attach security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Content-Security-Policy: allow our CDN scripts (lightweight-charts, globe.gl, fonts)
    # and same-origin everything else.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' unpkg.com cdn.jsdelivr.net cdn.socket.io fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
        "font-src 'self' fonts.gstatic.com; "
        "img-src 'self' data: *.ytimg.com unpkg.com; "
        "connect-src 'self' wss: ws:; "
        "frame-src https://www.youtube.com; "
        "object-src 'none';"
    )
    return response

_updater.init(socketio)

_quotes_cache: dict = {}
_crypto_spread_cache: dict = {}
_insider_cluster_cache: dict = {}
_short_volume_cache: dict = {}
_last_scan: datetime = datetime.min
_scan_lock = threading.Lock()
_chat_histories: dict = {}  # user_id -> list


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


# ── AUTH ROUTES ───────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if not _check_rate_limit(ip):
            return jsonify({"error": "Too many login attempts. Try again in 5 minutes."}), 429
        data = request.json or request.form
        user = verify_user(data.get("username", ""), data.get("password", ""))
        if user:
            # Session regeneration — clear old session to prevent fixation
            session.clear()
            session.permanent = bool(data.get("remember_me", True))
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["display_name"] = user.get("display_name") or user["username"]
            return jsonify({"status": "ok", "display_name": session["display_name"]})
        return jsonify({"error": "Invalid credentials"}), 401
    return render_template("dashboard.html")


@app.route("/register", methods=["POST"])
def register():
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"error": "Too many registration attempts. Try again in 5 minutes."}), 429
    data = request.json or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    display = data.get("display_name", username)
    if len(username) < 3 or len(password) < 6:
        return jsonify({"error": "Username ≥3 chars, password ≥6 chars"}), 400
    user = create_user(username, password, display)
    if not user:
        return jsonify({"error": "Username already taken"}), 409
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user.get("display_name") or user["username"]
    # Log consent at registration (GDPR Art.7 / CCPA / APP 5)
    if data.get("consent_accepted"):
        import hashlib
        ip_hash = hashlib.sha256((request.remote_addr or "").encode()).hexdigest()[:16]
        log_consent(user["id"], PRIVACY_POLICY_VERSION, ip_hash)
    return jsonify({"status": "ok", "display_name": session["display_name"]})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})


# ── OAUTH ROUTES ──────────────────────────────────────────────────────────────
import urllib.parse
import secrets

@app.route("/api/auth/status")
def api_auth_status():
    uid = session.get("user_id")
    providers = []
    if GOOGLE_CLIENT_ID:
        providers.append("google")
    if GITHUB_CLIENT_ID:
        providers.append("github")
        
    status_info = {
        "status": "anonymous" if not uid else ("accepted" if has_consent(uid, f"disclaimer-{DISCLAIMER_VERSION}") else "pending"),
        "providers": providers
    }
    if uid:
        status_info.update({
            "username": session["username"],
            "display_name": session["display_name"]
        })
    return jsonify(status_info)


@app.route("/login/github")
def login_github():
    if not GITHUB_CLIENT_ID:
        return "GitHub OAuth is not configured on this server.", 400
    state = secrets.token_hex(16)
    session["oauth_state"] = state
    redirect_uri = request.url_root.rstrip('/') + "/login/github/callback"
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": "read:user user:email"
    }
    url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)
    return redirect(url)


@app.route("/login/github/callback")
def login_github_callback():
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        return "GitHub OAuth is not configured on this server.", 400
        
    state = request.args.get("state")
    if not state or state != session.pop("oauth_state", None):
        return "Invalid OAuth state.", 400
        
    code = request.args.get("code")
    if not code:
        return "Missing code.", 400
        
    token_url = "https://github.com/login/oauth/access_token"
    redirect_uri = request.url_root.rstrip('/') + "/login/github/callback"
    headers = {"Accept": "application/json"}
    data = {
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": redirect_uri
    }
    
    import requests as oauth_requests
    token_res = oauth_requests.post(token_url, headers=headers, data=data, timeout=15)
    if token_res.status_code != 200:
        return "Failed to exchange authorization code.", 400
        
    token_data = token_res.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return "Could not retrieve access token.", 400
        
    user_url = "https://api.github.com/user"
    user_headers = {
        "Authorization": f"token {access_token}",
        "User-Agent": "FredAI-App"
    }
    user_res = oauth_requests.get(user_url, headers=user_headers, timeout=15)
    if user_res.status_code != 200:
        return "Failed to fetch user profile from GitHub.", 400
        
    user_profile = user_res.json()
    github_id = user_profile.get("id")
    github_login = user_profile.get("login")
    github_name = user_profile.get("name") or github_login

    if not github_id or not github_login:
        return "Failed to retrieve user ID from GitHub.", 400

    github_id = str(github_id)

    # Look up by GitHub's stable numeric ID, never by a derived username —
    # a username string can be squatted via /register ahead of time, which
    # would otherwise let an attacker hijack a victim's future OAuth login.
    user = get_user_by_oauth("github", github_id)
    if not user:
        username = f"github_{github_login}".lower()
        user = create_oauth_user("github", github_id, username, github_name)
        if not user:
            return "Failed to register user.", 500

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user.get("display_name") or user["username"]
    
    return redirect("/")


def save_google_credentials(user_id: int, access_token: str, refresh_token: str = None):
    from memory_store import get_conn, get_user
    from crypto_utils import encrypt_secret
    import json
    user = get_user(user_id)
    if not user:
        return
    prefs = {}
    try:
        prefs = json.loads(user.get("preferences") or "{}")
    except Exception:
        pass
    google_creds = prefs.get("google_credentials", {})
    google_creds["access_token"] = encrypt_secret(access_token)
    if refresh_token:
        google_creds["refresh_token"] = encrypt_secret(refresh_token)
    prefs["google_credentials"] = google_creds
    with get_conn() as conn:
        conn.execute("UPDATE users SET preferences=? WHERE id=?", (json.dumps(prefs), user_id))

def get_google_token(user_id: int) -> str | None:
    from memory_store import get_user
    from crypto_utils import decrypt_secret
    import json
    user = get_user(user_id)
    if not user:
        return None
    try:
        prefs = json.loads(user.get("preferences") or "{}")
        encrypted = prefs.get("google_credentials", {}).get("access_token")
        return decrypt_secret(encrypted) if encrypted else None
    except Exception:
        return None


@app.route("/login/google")
def login_google():
    if not GOOGLE_CLIENT_ID:
        return "Google OAuth is not configured on this server.", 400
    state = secrets.token_hex(16)
    session["oauth_state"] = state
    redirect_uri = request.url_root.rstrip('/') + "/login/google/callback"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": "openid profile email https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/gmail.send",
        "access_type": "offline",
        "prompt": "consent"
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return redirect(url)


@app.route("/login/google/callback")
def login_google_callback():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return "Google OAuth is not configured on this server.", 400
        
    state = request.args.get("state")
    if not state or state != session.pop("oauth_state", None):
        return "Invalid OAuth state.", 400
        
    code = request.args.get("code")
    if not code:
        return "Missing code.", 400
        
    token_url = "https://oauth2.googleapis.com/token"
    redirect_uri = request.url_root.rstrip('/') + "/login/google/callback"
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }
    
    import requests as oauth_requests
    token_res = oauth_requests.post(token_url, data=data, timeout=15)
    if token_res.status_code != 200:
        return "Failed to exchange authorization code.", 400
        
    token_data = token_res.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token:
        return "Could not retrieve access token.", 400
        
    user_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    user_headers = {"Authorization": f"Bearer {access_token}"}
    user_res = oauth_requests.get(user_url, headers=user_headers, timeout=15)
    if user_res.status_code != 200:
        return "Failed to fetch user profile from Google.", 400
        
    user_profile = user_res.json()
    google_sub = user_profile.get("sub")
    google_name = user_profile.get("name") or user_profile.get("given_name") or "Google User"
    google_email = user_profile.get("email")
    
    if not google_sub:
        return "Failed to retrieve user ID from Google.", 400
        
    # Look up by Google's stable "sub" claim, never by a derived username —
    # a username string can be squatted via /register ahead of time, which
    # would otherwise let an attacker hijack a victim's future OAuth login
    # (and, worse, receive the victim's real Google access/refresh tokens).
    user = get_user_by_oauth("google", google_sub)
    if not user:
        local_name = google_email.split('@')[0] if google_email else google_sub[:8]
        username = f"google_{local_name}".lower()
        user = create_oauth_user("google", google_sub, username, google_name)
        if not user:
            return "Failed to register user.", 500

    # Save tokens in user preferences database
    save_google_credentials(user["id"], access_token, refresh_token)

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user.get("display_name") or user["username"]
    
    return redirect("/")


@app.route("/")
def index():
    return render_template("dashboard.html")


# ── GOOGLE ECOSYSTEM INTEGRATION ENDPOINTS ────────────────────────────────────

@app.route("/api/google/status")
@login_required
def api_google_status():
    uid = session["user_id"]
    token = get_google_token(uid)
    return jsonify({
        "linked": token is not None
    })

@app.route("/api/google/export/sheets", methods=["POST"])
@login_required
def api_google_sheets_export():
    uid = session["user_id"]
    token = get_google_token(uid)
    if not token:
        return jsonify({"error": "Google account not linked. Please sign in via Google OAuth first."}), 400
        
    from google_integration import export_to_sheets
    from memory_store import get_watchlist
    
    quotes = _quotes_cache or {}
    holdings = get_portfolio(uid)
    portfolio = calculate_portfolio_value(holdings, quotes)
    
    watchlist = get_watchlist(uid)
    
    result = export_to_sheets(token, portfolio, watchlist)
    if result:
        return jsonify({"status": "ok", "spreadsheetId": result["spreadsheetId"], "url": result["url"]})
    return jsonify({"error": "Failed to create Google Sheet. Ensure your session token is valid."}), 500


@app.route("/api/google/export/gmail", methods=["POST"])
@login_required
def api_google_gmail_export():
    uid = session["user_id"]
    token = get_google_token(uid)
    if not token:
        return jsonify({"error": "Google account not linked. Please sign in via Google OAuth first."}), 400
        
    data = request.get_json() or {}
    ticker = data.get("ticker", "").strip().upper()
    subject = data.get("subject", f"FredAI Analyst Report: {ticker}" if ticker else "FredAI Briefing Report")
    body_html = data.get("html", "")
    
    if not body_html:
        return jsonify({"error": "Missing report content."}), 400
        
    import requests as api_requests
    recipient = None
    try:
        user_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        user_headers = {"Authorization": f"Bearer {token}"}
        user_res = api_requests.get(user_url, headers=user_headers, timeout=10)
        if user_res.status_code == 200:
            recipient = user_res.json().get("email")
    except Exception:
        pass
        
    if not recipient:
        return jsonify({"error": "Could not retrieve recipient email address from Google profile."}), 400
        
    from google_integration import send_gmail_report
    if send_gmail_report(token, recipient, subject, body_html):
        return jsonify({"status": "ok", "recipient": recipient})
    return jsonify({"error": "Failed to send email via Gmail API."}), 500

@app.route("/api/google/sync/calendar", methods=["POST"])
@login_required
def api_google_calendar_sync():
    uid = session["user_id"]
    token = get_google_token(uid)
    if not token:
        return jsonify({"error": "Google account not linked."}), 400
        
    from google_integration import sync_to_calendar
    
    events = get_calendar_events(days=7)
    if not events:
        return jsonify({"status": "ok", "message": "No events found to sync."})
        
    count = 0
    for event in events:
        event_map = {
            "title": event.get("title") or event.get("name") or "Economic Event",
            "description": f"Sector/Symbol: {event.get('symbol','Global')} | Impact: High | Source: FredAI",
            "date": event.get("date") or datetime.now().strftime("%Y-%m-%d")
        }
        if sync_to_calendar(token, event_map):
            count += 1
            
    return jsonify({"status": "ok", "synced_count": count})

@app.route("/api/google/backup/drive", methods=["POST"])
@login_required
def api_google_drive_backup():
    uid = session["user_id"]
    token = get_google_token(uid)
    if not token:
        return jsonify({"error": "Google account not linked."}), 400
        
    from google_integration import backup_to_drive
    from memory_store import get_watchlist, get_user
    
    user = get_user(uid)
    wl = get_watchlist(uid)
    holdings = get_portfolio(uid)
    
    backup_data = {
        "user_profile": {
            "username": user["username"],
            "display_name": user.get("display_name"),
            "preferences": user.get("preferences")
        },
        "watchlist": wl,
        "portfolio": holdings,
        "timestamp": datetime.now().isoformat()
    }
    
    if backup_to_drive(token, backup_data):
        return jsonify({"status": "ok", "message": "Backup saved successfully as fredai_secure_backup.json on Google Drive."})
    return jsonify({"error": "Failed to upload backup to Google Drive."}), 500


# ── INIT / DATA ROUTES ────────────────────────────────────────────────────────

@app.route("/api/init")
@login_required
def api_init():
    uid = session["user_id"]
    quotes = _quotes_cache or {}
    holdings = get_portfolio(uid)
    portfolio = calculate_portfolio_value(holdings, quotes)
    watchlist = get_watchlist(uid)
    watchlist_symbols = [w["symbol"] for w in watchlist]
    signals = get_signals_with_fallback(hours=4, limit=50)
    stats = compute_sentiment_stats(signals)
    summary = get_latest_summary()
    timeline = get_sentiment_timeline(hours=24)
    alerts = get_recent_alerts(limit=20)
    sector = get_sector_snapshot(quotes)
    risk = get_risk_level(stats, alerts)
    interests = get_user_interests(uid, limit=10)
    trending = get_trending_assets_with_fallback(hours=4, limit=15)
    next_scan = (_last_scan + timedelta(hours=SCAN_INTERVAL_HOURS)).isoformat() if _last_scan > datetime.min else None

    news_preview = get_news_diverse(hours=24, limit=6)
    calendar_preview = get_calendar_events(days=7)
    tech_alerts_user = get_tech_alerts(uid)

    return jsonify({
        "user": {"id": uid, "username": session["username"], "display_name": session["display_name"]},
        "quotes": quotes,
        "portfolio": portfolio,
        "watchlist": watchlist_symbols,
        "watchlist_detail": [dict(w, **quotes.get(w["symbol"], {})) for w in watchlist],
        "signals": signals[:30],
        "stats": stats,
        "summary": summary,
        "timeline": timeline,
        "alerts": alerts,
        "sector": sector,
        "risk_level": risk,
        "next_scan": next_scan,
        "interests": interests,
        "trending": trending,
        "macro": _macro_cache,
        "news_preview": news_preview,
        "calendar": calendar_preview,
        "tech_alerts": tech_alerts_user,
    })


@app.route("/api/history/<symbol>")
@login_required
def api_history(symbol):
    bump_interest(session["user_id"], symbol, delta=0.5)
    # Whitelist period/interval to prevent yfinance abuse
    valid_periods = {"1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max"}
    valid_intervals = {"1m","5m","15m","30m","60m","1h","1d","1wk","1mo"}
    period = request.args.get("period", "5d")
    interval = request.args.get("interval", "30m")
    if period not in valid_periods: period = "5d"
    if interval not in valid_intervals: interval = "30m"
    return jsonify(fetch_history(symbol.upper(), period=period, interval=interval))


@app.route("/api/summaries")
@login_required
def api_summaries():
    return jsonify(get_summaries(limit=10))


@app.route("/api/trending")
@login_required
def api_trending():
    hours = min(max(int(request.args.get("hours", 4)), 1), 168)
    trending = get_trending_assets_with_fallback(hours=hours, limit=20)
    quotes = _quotes_cache or {}
    for t in trending:
        q = quotes.get(t["asset"])
        if q:
            t.update({"price": q["price"], "change_pct": q["change_pct"], "name": q["name"]})
    return jsonify(trending)


# ── WATCHLIST ROUTES ──────────────────────────────────────────────────────────

@app.route("/api/watchlist", methods=["GET", "POST", "DELETE"])
@login_required
def api_watchlist():
    uid = session["user_id"]
    if request.method == "POST":
        data = request.json or {}
        sym = data.get("symbol", "").upper().strip()
        if not sym:
            return jsonify({"error": "symbol required"}), 400
        if not _valid_symbol(sym):
            return jsonify({"error": "invalid symbol"}), 400
        add_to_watchlist(uid, sym, data.get("notes"))
        return jsonify({"status": "ok", "symbol": sym})
    if request.method == "DELETE":
        sym = (request.json or {}).get("symbol", "").upper()
        remove_from_watchlist(uid, sym)
        return jsonify({"status": "ok"})
    wl = get_watchlist(uid)
    quotes = _quotes_cache or {}
    sentiment = get_sentiment_snapshot([w["symbol"] for w in wl], hours=24)
    result = []
    for w in wl:
        entry = dict(w)
        q = quotes.get(w["symbol"])
        if q:
            entry.update(q)
        s = sentiment.get(w["symbol"])
        if s:
            entry["sentiment"] = s
        spread = _crypto_spread_cache.get(w["symbol"])
        if spread:
            entry["cross_exchange_spread"] = spread
        cluster = _insider_cluster_cache.get(w["symbol"])
        if cluster:
            entry["insider_cluster"] = cluster
        sv = _short_volume_cache.get(w["symbol"])
        if sv:
            entry["short_volume"] = sv
        result.append(entry)
    return jsonify(result)


# ── PORTFOLIO ROUTES ──────────────────────────────────────────────────────────

@app.route("/api/portfolio", methods=["GET", "POST", "DELETE"])
@login_required
def api_portfolio():
    uid = session["user_id"]
    if request.method == "POST":
        data = request.json or {}
        sym = data.get("symbol", "").upper()
        if not _valid_symbol(sym):
            return jsonify({"error": "invalid symbol"}), 400
        upsert_portfolio(uid, sym, float(data.get("shares", 0)), float(data.get("avg_cost", 0)))
        return jsonify({"status": "ok"})
    if request.method == "DELETE":
        sym = (request.json or {}).get("symbol", "").upper()
        upsert_portfolio(uid, sym, 0, 0)
        return jsonify({"status": "ok"})
    holdings = get_portfolio(uid)
    portfolio = calculate_portfolio_value(holdings, _quotes_cache or {})
    sentiment = get_sentiment_snapshot([p["symbol"] for p in portfolio.get("positions", [])], hours=24)
    for pos in portfolio.get("positions", []):
        si = get_latest_short_interest(pos["symbol"])
        if si:
            pos["short_float_pct"] = si["short_float_pct"]
            pos["short_ratio"] = si["short_ratio"]
        sv = _short_volume_cache.get(pos["symbol"])
        if sv:
            pos["short_volume"] = sv
        s = sentiment.get(pos["symbol"])
        if s:
            pos["sentiment"] = s
    return jsonify(portfolio)


@app.route("/api/portfolio/risk")
@login_required
def api_portfolio_risk():
    from portfolio_risk import compute_portfolio_risk
    uid = session["user_id"]
    holdings = get_portfolio(uid)
    portfolio = calculate_portfolio_value(holdings, _quotes_cache or {})
    risk = compute_portfolio_risk(
        portfolio.get("positions", []), portfolio.get("total_value")
    )
    return jsonify(risk)


@app.route("/api/scan", methods=["POST"])
@login_required
def api_manual_scan():
    socketio.start_background_task(job_scan_cycle)
    return jsonify({"status": "scan started"})


@app.route("/api/rnd/backlog")
@login_required
def api_rnd_backlog():
    return jsonify(get_all_proposals(limit=50))


@app.route("/api/backtest/accuracy")
@login_required
def api_backtest_accuracy():
    """Reporting for the signal outcome tracker (FSI L3): how often Fred's
    per-asset signal direction matched the actual price move, at each of
    the 4h/24h/72h checkpoints -- per source, vs a naive momentum baseline."""
    return jsonify(get_accuracy_report())


@app.route("/api/backtest/source-health")
@login_required
def api_backtest_source_health():
    """Sources whose 30-day accuracy hasn't beaten the naive baseline at
    a meaningful sample size (MISSION.md Principle #4). Flags only -- no
    automatic removal, a human reviews this list."""
    from backtesting_engine import get_underperforming_sources
    return jsonify(get_underperforming_sources())


@app.route("/api/rnd/propose", methods=["POST"])
@login_required
def api_rnd_propose():
    data = request.json or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    insert_feature_proposal(
        title=title,
        description=data.get("description", ""),
        category=data.get("category", "general"),
        implementation_spec=data.get("spec", ""),
        proposed_by=f"user:{session['username']}",
    )
    return jsonify({"status": "ok"})


@app.route("/api/rnd/run", methods=["POST"])
@login_required
def api_rnd_run():
    """Trigger a full R&D + implementation cycle (admin only)."""
    uid = session["user_id"]
    user = get_user(uid)
    if not user or user.get("username") != "admin":
        return jsonify({"error": "Admin only"}), 403
    def _run():
        try:
            from improve import run_improvement_cycle
            results = run_improvement_cycle()
            socketio.emit("rnd_complete", results)
        except Exception as e:
            socketio.emit("rnd_complete", {"error": "R&D cycle failed"})
    socketio.start_background_task(_run)
    return jsonify({"status": "R&D cycle started"})


# ── INSTALL / DEVICE / UPDATE ROUTES ─────────────────────────────────────────

@app.route("/api/device")
def api_device():
    """Return detected platform info and install capabilities. No auth — used pre-login."""
    device = _installer.detect_device()
    os_family = device["os_family"]
    capabilities = {
        "pwa": True,
        "native_shortcut": os_family in ("macos", "windows", "linux"),
        "dock": os_family == "macos",
        "start_menu": os_family == "windows",
        "app_menu": os_family == "linux",
        "taskbar": os_family in ("windows", "linux"),
        "ios_pwa": False,
        "android_pwa": False,
    }
    return jsonify({**device, "capabilities": capabilities})


@app.route("/api/install", methods=["POST"])
@login_required
def api_install():
    """Autonomously install FredAI shortcuts on the host device."""
    port = int(request.json.get("port", PORT)) if request.json else PORT
    try:
        result = _installer.install(port)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "actions": [], "warnings": []}), 500


@app.route("/api/update/status")
@login_required
def api_update_status():
    return jsonify(_updater.status())


@app.route("/api/update/check", methods=["POST"])
@login_required
def api_update_check():
    """Poll GitHub for new commits (async-safe, returns immediately)."""
    def _check():
        _updater.check_for_updates(emit_event=True)
    socketio.start_background_task(_check)
    return jsonify({"status": "checking"})


@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    """Pull latest from GitHub. Accepts authenticated session OR CI deploy secret header."""
    deploy_header = request.headers.get("X-FredAI-Deploy", "")
    if "user_id" not in session:
        # CI path: must supply correct deploy secret (empty secret = CI webhook disabled)
        if not FREDAI_DEPLOY_SECRET or not deploy_header:
            return jsonify({"error": "unauthorized"}), 401
        import hmac as _hmac
        if not _hmac.compare_digest(deploy_header, FREDAI_DEPLOY_SECRET):
            return jsonify({"error": "unauthorized"}), 401
    result = _updater.apply_update()
    if result.get("restart_triggered"):
        socketio.emit("alert", {
            "title": "FredAI Updated",
            "message": f"Updated to {result['sha_after'][:8]}. Restarting now...",
            "level": "info",
        })
    elif result.get("rolled_back"):
        socketio.emit("alert", {
            "title": "FredAI Update Failed",
            "message": f"Pulled update failed validation and was rolled back: {result.get('message','')}",
            "level": "warning",
        })
    elif result.get("updated"):
        socketio.emit("alert", {
            "title": "FredAI Updated",
            "message": f"Updated to {result['sha_after'][:8]}. Restart to apply.",
            "level": "info",
        })
    return jsonify(result)


# ── PRIVACY / DATA GOVERNANCE ROUTES ──────────────────────────────────────────
# GDPR (EU) · Australian Privacy Act 1988 · US CCPA / state laws

DISCLAIMER_TEXT = """FredAI — Disclaimer & Terms of Use

IMPORTANT: Please read before using FredAI.

1. NOT FINANCIAL ADVICE
   FredAI is an AI-powered information and signal aggregation tool.
   It is NOT a licensed financial advisor, investment advisor, broker-dealer,
   or regulated financial professional under any jurisdiction, including but
   not limited to the United States, United Kingdom, European Union, Australia,
   and Canada.

2. INFORMATIONAL PURPOSES ONLY
   All content produced by FredAI — including market signals, summaries,
   portfolio commentary, trend analysis, and Fred's conversational responses —
   is provided for INFORMATIONAL AND EDUCATIONAL PURPOSES ONLY.
   Nothing constitutes a solicitation, recommendation, or offer to buy or sell
   any security, cryptocurrency, or other financial instrument.

3. YOUR RISK, YOUR DECISION
   All investment and financial decisions you make based on information from
   FredAI are ENTIRELY YOUR OWN RESPONSIBILITY. You acknowledge that:
   - Financial markets involve substantial risk of loss, including total loss of capital.
   - Past signal accuracy or performance does not predict future results.
   - AI-generated analysis may be incomplete, inaccurate, or delayed.
   - X/Twitter signals and third-party market data relayed by FredAI may be
     erroneous, manipulated, or unreliable.

4. NO LIABILITY
   FredAI, its developers, contributors, operators, and affiliates accept
   ZERO LIABILITY for any direct, indirect, incidental, or consequential
   financial losses, damages, or harm arising from:
   - Your use of or reliance on FredAI's output
   - Errors, omissions, or delays in data
   - System downtime or technical failures
   - Any third-party data sources integrated with FredAI

5. SEEK PROFESSIONAL ADVICE
   Before making any investment decision, consult a licensed and regulated
   financial advisor in your jurisdiction. FredAI is not a substitute for
   professional financial guidance.

6. ACCEPTANCE
   By using FredAI, you confirm that you have read, understood, and accepted
   this disclaimer in its entirety. You agree to use FredAI solely for
   informational and educational purposes.

Version 1.0 — Effective from first use."""

DISCLAIMER_VERSION = "1.0"


@app.route("/disclaimer")
def api_disclaimer_page():
    """Public endpoint — no auth required."""
    return DISCLAIMER_TEXT, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/disclaimer")
def api_disclaimer_json():
    """Machine-readable disclaimer for the frontend."""
    return jsonify({
        "version": DISCLAIMER_VERSION,
        "text": DISCLAIMER_TEXT,
        "requires_acceptance": True,
        "acceptance_endpoint": "/api/user/accept-disclaimer",
    })


@app.route("/api/user/accept-disclaimer", methods=["POST"])
@login_required
def api_accept_disclaimer():
    """Record that the user has accepted the disclaimer."""
    import hashlib
    uid = session["user_id"]
    ip_hash = hashlib.sha256((request.remote_addr or "").encode()).hexdigest()[:16]
    log_consent(uid, f"disclaimer-{DISCLAIMER_VERSION}", ip_hash)
    return jsonify({"status": "accepted", "version": DISCLAIMER_VERSION})


@app.route("/api/user/disclaimer-status")
@login_required
def api_disclaimer_status():
    uid = session["user_id"]
    accepted = has_consent(uid, f"disclaimer-{DISCLAIMER_VERSION}")
    return jsonify({"accepted": accepted, "version": DISCLAIMER_VERSION})


@app.route("/api/user/privacy")
@login_required
def api_privacy_info():
    """Return privacy settings and AI provider status."""
    from agent import get_provider_status
    uid = session["user_id"]
    return jsonify({
        "data_location": "local",
        "database": "SQLite on this device — never transmitted",
        "ai_provider": get_provider_status(),
        "privacy_mode": PRIVACY_MODE,
        "strip_portfolio_from_ai": STRIP_PORTFOLIO_FROM_AI,
        "data_retention_days": DATA_RETENTION_DAYS,
        "policy_version": PRIVACY_POLICY_VERSION,
        "user_has_consented": has_consent(uid, PRIVACY_POLICY_VERSION),
        "applicable_laws": ["GDPR (EU)", "Australian Privacy Act 1988", "CCPA (California)"],
        "agent_code_source": "github.com/essentialbit/fredai (public code, no user data)",
        "user_rights": {
            "access": "GET /api/user/export",
            "erasure": "DELETE /api/user/delete",
            "consent": "POST /api/user/consent",
        },
        "third_party_data_flows": [
            {"recipient": "yfinance/Yahoo Finance", "data": "ticker symbols only", "personal": False},
            {"recipient": "X/Twitter API", "data": "public search queries", "personal": False},
            {"recipient": "Anthropic API (if AI_PROVIDER=anthropic)", "data": "market signals + anonymized context", "personal": False if STRIP_PORTFOLIO_FROM_AI else "partial"},
            {"recipient": "Nasdaq Data Link", "data": "macro data requests", "personal": False},
            {"recipient": "Ollama (if AI_PROVIDER=ollama)", "data": "none — fully local", "personal": False},
        ],
    })


@app.route("/api/user/consent", methods=["POST"])
@login_required
def api_record_consent():
    """Record explicit consent (GDPR Art.7 / APP 5)."""
    import hashlib
    uid = session["user_id"]
    ip_hash = hashlib.sha256((request.remote_addr or "").encode()).hexdigest()[:16]
    log_consent(uid, PRIVACY_POLICY_VERSION, ip_hash)
    return jsonify({"status": "consent_recorded", "policy_version": PRIVACY_POLICY_VERSION})


@app.route("/api/user/export")
@login_required
def api_user_export():
    """
    GDPR Art.20 / CCPA / APP 12 — Data portability.
    Returns all personal data held for the current user as JSON.
    """
    uid = session["user_id"]
    data = export_user_data(uid)
    from flask import Response
    return Response(
        __import__("json").dumps(data, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=fredai-data-{uid}.json"}
    )


@app.route("/api/user/delete", methods=["DELETE"])
@login_required
def api_user_delete():
    """
    GDPR Art.17 / CCPA opt-out / APP 13 — Right to erasure.
    Permanently deletes all personal data. Requires password confirmation.
    """
    data = request.json or {}
    uid = session["user_id"]
    user = get_user(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404
    # Require password re-confirmation unless OAuth user
    is_oauth = user["username"].startswith("google_") or user["username"].startswith("github_")
    if not is_oauth:
        from werkzeug.security import check_password_hash
        if not check_password_hash(user["password_hash"], data.get("password", "")):
            return jsonify({"error": "Password confirmation required"}), 403
    ok = delete_user_data(uid)
    if ok:
        session.clear()
        return jsonify({"status": "deleted", "message": "All personal data has been permanently erased."})
    return jsonify({"error": "Deletion failed"}), 500


@app.route("/api/user/change-password", methods=["POST"])
@login_required
def api_change_password():
    """Change password with current-password verification."""
    import hashlib
    data = request.json or {}
    uid = session["user_id"]
    user = get_user(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404
    from werkzeug.security import check_password_hash, generate_password_hash
    if not check_password_hash(user["password_hash"], data.get("current_password", "")):
        return jsonify({"error": "Current password incorrect"}), 403
    new_pw = data.get("new_password", "")
    if len(new_pw) < 6:
        return jsonify({"error": "New password must be ≥6 characters"}), 400
    new_hash = generate_password_hash(new_pw)
    from memory_store import get_conn as _gc
    with _gc() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, uid))
    return jsonify({"status": "password_changed"})


@app.route("/api/user/reset-password", methods=["POST"])
@login_required
def api_reset_password():
    """Admin-only: reset any user's password. Requires admin username."""
    import hashlib
    uid = session["user_id"]
    user = get_user(uid)
    if not user or user.get("username") != "admin":
        return jsonify({"error": "Admin only"}), 403
    data = request.json or {}
    target = data.get("username", "").strip().lower()
    new_pw = data.get("new_password", "")
    if not target or len(new_pw) < 6:
        return jsonify({"error": "username and new_password (≥6 chars) required"}), 400
    new_hash = hashlib.sha256(new_pw.encode()).hexdigest()
    from memory_store import get_conn as _gc
    with _gc() as c:
        rows = c.execute("UPDATE users SET password_hash=? WHERE username=?", (new_hash, target)).rowcount
    if rows:
        return jsonify({"status": "reset", "username": target})
    return jsonify({"error": "User not found"}), 404


@app.route("/api/translate", methods=["POST"])
@login_required
def api_translate():
    data = request.json or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"translated_text": "", "was_translated": False})
    from news_client import translate_to_english
    translated, was_translated = translate_to_english(text)
    return jsonify({
        "translated_text": translated,
        "was_translated": was_translated
    })


@app.route("/api/globe/node-risk", methods=["POST"])
@login_required
def api_globe_node_risk():
    data = request.json or {}
    ticker = data.get("ticker", "").strip().upper()
    headline = data.get("headline", "").strip()
    summary = data.get("summary", "").strip()

    from agent import _provider
    prompt = f"""
    You are Fred's geopolitical and supply chain intelligence auditor.
    Analyze the following node signal:
    - Target Asset/Region: {ticker or 'Global/Geographic Node'}
    - Title/Headline: {headline}
    - Details: {summary}

    Perform a professional, multi-step risk audit detailing:
    1. Geopolitical or macroeconomic exposure of this node.
    2. Downstream supply-chain vulnerabilities and business dependencies.
    3. Potential black swan risks and market correlation implications.
    4. Strategic mitigation recommendations.
    
    Use clear, professional markdown formatting with sections.
    """
    try:
        report = _provider.complete(
            messages=[{"role": "user", "content": prompt}],
            system="You are a senior geopolitical risk analyst and supply-chain auditor.",
            tier="chat",
            grounding=True
        )
        return jsonify({"report": report})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyst/debate/<ticker>", methods=["POST"])
@login_required
def api_analyst_debate(ticker):
    ticker = ticker.upper().strip()
    if not ticker:
        return jsonify({"error": "Invalid ticker symbol."}), 400

    from agent import _provider
    from memory_store import get_news
    news = get_news(hours=72, limit=20)
    ticker_news = [n for n in news if ticker in (n.get("ticker") or n.get("title") or "")]
    news_context = "\n".join([f"- {n.get('title')}: {n.get('content')}" for n in ticker_news[:5]])

    bull_prompt = f"""
    Role: Extremely bullish investor championing {ticker}.
    Context News:\n{news_context}
    Write a short, highly persuasive bull thesis for {ticker} highlighting key catalysts, competitive advantages, and growth avenues. Limit to 2 bullet points.
    """
    bear_prompt = f"""
    Role: Extremely bearish short-seller exposing risks for {ticker}.
    Context News:\n{news_context}
    Write a short, highly persuasive bear thesis for {ticker} highlighting risks, margin pressures, and head-winds. Limit to 2 bullet points.
    """
    
    try:
        bull = _provider.complete(
            messages=[{"role": "user", "content": bull_prompt}],
            system="You are a bullish buy-side equity analyst.",
            tier="chat"
        )
        bear = _provider.complete(
            messages=[{"role": "user", "content": bear_prompt}],
            system="You are a skeptical short-seller research analyst.",
            tier="chat"
        )
        
        verdict_prompt = f"""
        Analyze the following debate:
        BULL CASE:
        {bull}

        BEAR CASE:
        {bear}

        Synthesize these cases objectively. Write a brief final committee consensus verdict recommendation for {ticker}. Limit to 2 sentences.
        """
        verdict = _provider.complete(
            messages=[{"role": "user", "content": verdict_prompt}],
            system="You are the neutral Investment Committee Chair.",
            tier="chat"
        )
        
        return jsonify({"bull": bull, "bear": bear, "verdict": verdict})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyst/report/<ticker>")
@login_required
def api_analyst_report(ticker):
    ticker = ticker.upper().strip()
    if not ticker:
        return jsonify({"error": "Invalid ticker symbol."}), 400
        
    from memory_store import get_news, get_signals
    from agent import _provider
    
    price_info = (_quotes_cache or {}).get(ticker, {})
    
    # Get recent news relating to this ticker
    news = get_news(hours=72, limit=50)
    ticker_news = []
    for n in news:
        tickers_list = [t.strip().upper() for t in (n.get("tickers") or "").split(",") if t.strip()]
        if ticker in tickers_list or ticker in n.get("title", "").upper() or ticker in n.get("summary", "").upper():
            ticker_news.append(n)
            
    # Get recent signals relating to this ticker
    sigs = get_signals(hours=72, limit=50)
    ticker_sigs = []
    for s in sigs:
        if s.get("asset") == ticker or ticker in s.get("content", "").upper():
            ticker_sigs.append(s)
            
    system_prompt = (
        "You are an elite Wall Street equity analyst. Write a professional, comprehensive, and objective "
        "equity research report for the requested stock ticker/company. Leverage the provided market data, "
        "recent news items, and technical signals to formulate your report. "
        "Format the report in clean Markdown using headings, tables, bullet points, and strong bold highlights. "
        "Sections MUST include: "
        "1. Executive Summary & Recommendation Rating (Buy/Hold/Sell) "
        "2. Financial Snapshot (discuss pricing, market cap, and relative performance) "
        "3. Sentiment Audit (summarize the tone and focus of recent news/signals) "
        "4. Risk & Catalyst Analysis (identify key competitive headwinds and upcoming upside triggers) "
        "5. 12-Month Outlook & Forecast. "
        "Be detailed, precise, and maintain a highly professional analytical tone."
    )
    
    user_prompt = f"Stock Ticker: {ticker}\n"
    if price_info:
        user_prompt += f"Current Market Price Context: {price_info}\n"
    else:
        user_prompt += f"Note: No real-time quote info cached for symbol {ticker}.\n"
        
    if ticker_news:
        user_prompt += "Recent Feed news:\n"
        for n in ticker_news[:8]:
            user_prompt += f"- [{n.get('source', 'Unknown')}] {n.get('title')} (VADER Sentiment Score: {n.get('sentiment_score', 0.0)})\n"
    else:
        user_prompt += "No recent news headlines available for this symbol.\n"
        
    if ticker_sigs:
        user_prompt += "Recent Technical & Geopolitical Signals:\n"
        for s in ticker_sigs[:5]:
            user_prompt += f"- [{s.get('signal_type', 'signal')}] {s.get('content')[:150]} (Sentiment Score: {s.get('sentiment_score', 0.0)})\n"
    else:
        user_prompt += "No recent technical signal entries available for this symbol.\n"
        
    try:
        report_markdown = _provider.complete([{"role": "user", "content": user_prompt}], system_prompt, tier="chat", max_tokens=1500)
    except Exception as e:
        report_markdown = f"# Equity Analysis for {ticker}\n\nFailed to autogenerate report: {str(e)}"
        
    return jsonify({
        "status": "ok",
        "ticker": ticker,
        "report": report_markdown
    })


@app.route("/api/system/refresh", methods=["POST"])
@login_required
def api_system_refresh():
    import threading

    # 1. Pull + verify (but don't auto-restart yet — this button restarts
    # unconditionally below, same as before, but now goes through updater.py's
    # safe path: verifies the pulled code actually imports before ever
    # touching the running process, and rolls back instead of restarting
    # onto broken code (previously this route did its own bare `git pull`
    # + restart with no verification at all).
    result = _updater.apply_update(restart=False)
    if not result.get("rolled_back"):
        result["restart_triggered"] = _updater.trigger_restart()

    # 2. Refresh database feeds (fetch news in background) — only if we're
    # not about to restart onto new code anyway.
    if not result.get("restart_triggered"):
        try:
            from news_client import fetch_all_news
            from memory_store import get_watchlist
            uid = session.get("user_id")
            if uid:
                wl_items = get_watchlist(uid)
                wl = [w["symbol"] for w in wl_items]
                threading.Thread(target=fetch_all_news, args=(wl,), daemon=True).start()
        except Exception as e:
            print(f"[System Refresh] Feed update trigger failed: {e}")

    return jsonify({
        "status": "restarting" if result.get("restart_triggered") else "no_restart",
        "git": result.get("message", ""),
        "update": result,
    })


@app.route("/api/user/keys", methods=["POST"])
@login_required
def api_save_user_keys():
    from memory_store import get_conn, get_user
    from crypto_utils import encrypt_secret
    import json
    uid = session.get("user_id")
    user = get_user(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.json or {}
    anthropic_key = data.get("anthropic_key", "").strip()
    gemini_key = data.get("gemini_key", "").strip()

    prefs = {}
    try:
        prefs = json.loads(user.get("preferences") or "{}")
    except Exception:
        pass

    if anthropic_key:
        prefs["user_anthropic_key"] = encrypt_secret(anthropic_key)
    elif "user_anthropic_key" in prefs:
        del prefs["user_anthropic_key"]

    if gemini_key:
        prefs["user_gemini_key"] = encrypt_secret(gemini_key)
    elif "user_gemini_key" in prefs:
        del prefs["user_gemini_key"]
        
    with get_conn() as conn:
        conn.execute("UPDATE users SET preferences=? WHERE id=?", (json.dumps(prefs), uid))
        
    return jsonify({
        "status": "ok",
        "has_anthropic": bool(prefs.get("user_anthropic_key")),
        "has_gemini": bool(prefs.get("user_gemini_key"))
    })

@app.route("/api/user/keys", methods=["GET"])
@login_required
def api_get_user_keys_status():
    from memory_store import get_user
    import json
    uid = session.get("user_id")
    user = get_user(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404
    prefs = {}
    try:
        prefs = json.loads(user.get("preferences") or "{}")
    except Exception:
        pass
    return jsonify({
        "has_anthropic": bool(prefs.get("user_anthropic_key")),
        "has_gemini": bool(prefs.get("user_gemini_key"))
    })


@app.route("/api/news/globe-data")
@login_required
def api_news_globe_data():
    """Aggregate news by geographic source for the globe visualization."""
    from news_client import SOURCE_COORDINATES
    hours = min(max(int(request.args.get("hours", 24)), 1), 720)
    news = get_news(hours=hours, limit=500)
    from collections import defaultdict
    region_counts: dict = defaultdict(lambda: {"count": 0, "sources": set(), "categories": []})
    for item in news:
        src = item.get("source", "")
        coords = SOURCE_COORDINATES.get(src)
        if coords:
            key = src
            region_counts[key]["count"] += 1
            region_counts[key]["sources"].add(src)
            region_counts[key]["lat"] = coords[0]
            region_counts[key]["lng"] = coords[1]
            region_counts[key]["region"] = coords[2]
            cat = item.get("category", "market")
            region_counts[key]["categories"].append(cat)
    points = []
    for src, data in region_counts.items():
        cats = data["categories"]
        primary = max(set(cats), key=cats.count) if cats else "market"
        points.append({
            "lat": data["lat"],
            "lng": data["lng"],
            "label": data["region"],
            "count": data["count"],
            "category": primary,
        })

    from ticker_geo import resolve_ticker_location
    story_arcs = []
    for item in news:
        ticker = (item.get("tickers") or "").split(",")[0].strip()
        if not ticker:
            continue
        loc = resolve_ticker_location(ticker)
        story_arcs.append({
            "ticker": ticker,
            "title": item.get("title"),
            "sentiment_score": item.get("sentiment_score"),
            "hq_lat": loc["lat"], "hq_lng": loc["lon"],
            "exchange": loc["exchange"],
            "exchange_lat": loc["exchange_lat"], "exchange_lng": loc["exchange_lon"],
        })

    return jsonify({"points": points, "story_arcs": story_arcs, "total": len(news), "hours": hours})


@app.route("/api/news/youtube-channels")
@login_required
def api_youtube_channels():
    """Return latest videos from financial news YouTube channels via RSS."""
    import urllib.request
    import xml.etree.ElementTree as ET
    CHANNELS = {
        "Bloomberg": "UCIALMKvObZNtJ6AmdCLP7Lg",
        "Yahoo Finance": "UCDneEQMn4nkAHSX9UPnWtLQ",
        "CNBC": "UCvJJ_dzjViJCoLf5uKUTwoA",
    }
    results = {}
    for name, cid in CHANNELS.items():
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
            req = urllib.request.Request(url, headers={"User-Agent": "FredAI/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                tree = ET.fromstring(r.read())
            ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}
            entries = []
            for entry in tree.findall("atom:entry", ns)[:5]:
                vid_id = entry.find("yt:videoId", ns)
                title = entry.find("atom:title", ns)
                published = entry.find("atom:published", ns)
                thumb = entry.find(".//media:thumbnail", ns)
                if vid_id is not None and title is not None:
                    entries.append({
                        "id": vid_id.text,
                        "title": title.text,
                        "published": published.text if published is not None else "",
                        "thumbnail": thumb.get("url") if thumb is not None else "",
                        "embed_url": f"https://www.youtube.com/embed/{vid_id.text}?rel=0&modestbranding=1",
                    })
            results[name] = {"channel_id": cid, "videos": entries}
        except Exception:
            results[name] = {"channel_id": cid, "videos": []}
    return jsonify(results)


_VIDEO_EMBED_PREFIXES = ("https://www.youtube.com/embed/", "https://www.youtube-nocookie.com/embed/")


@app.route("/popout/video")
@login_required
def popout_video():
    """Standalone floating player window -- opened via window.open() from any
    video widget, so it's a genuinely separate browsing context that survives
    the opener navigating to a different page/tab (real window.open, not an
    in-page overlay)."""
    src = request.args.get("src", "")
    title = request.args.get("title", "Fred AI Video")[:120]
    if not src.startswith(_VIDEO_EMBED_PREFIXES):
        return "Invalid video source", 400
    return render_template("video_popout.html", src=src, title=title)


@app.route("/news")
@login_required
def news_page():
    return render_template("news.html")


@app.route("/api/news")
@login_required
def api_news():
    category = request.args.get("category", "all")
    ticker = request.args.get("ticker", "")[:20]   # truncate to prevent abuse
    hours = min(max(int(request.args.get("hours", 24)), 1), 720)
    page = min(max(int(request.args.get("page", 1)), 1), 100)
    limit = min(max(int(request.args.get("limit", 30)), 1), 100)
    offset = (page - 1) * limit
    items = get_news(category=category, ticker=ticker or None, hours=hours, limit=limit, offset=offset)
    total = count_news(category=category, ticker=ticker or None, hours=hours)
    return jsonify({"items": items, "total": total, "page": page, "limit": limit})


@app.route("/api/calendar")
@login_required
def api_calendar():
    days = min(max(int(request.args.get("days", 7)), 1), 90)
    events = get_calendar_events(days=days)
    return jsonify({"events": events})


@app.route("/api/tech-alerts", methods=["GET"])
@login_required
def api_get_tech_alerts():
    uid = session["user_id"]
    alerts = get_tech_alerts(uid)
    return jsonify({"alerts": alerts})


@app.route("/api/tech-alerts", methods=["POST"])
@login_required
def api_create_tech_alert():
    uid = session["user_id"]
    data = request.json or {}
    required = ["symbol", "alert_type", "condition", "threshold"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Required: {required}"}), 400
    if not _valid_symbol(data["symbol"].upper()):
        return jsonify({"error": "invalid symbol"}), 400
    alert = create_tech_alert(
        uid, data["symbol"], data["alert_type"],
        data["condition"], float(data["threshold"]),
        int(data.get("period", 20))
    )
    return jsonify({"status": "created", "alert": alert})


@app.route("/api/tech-alerts/<int:alert_id>", methods=["DELETE"])
@login_required
def api_delete_tech_alert(alert_id):
    uid = session["user_id"]
    delete_tech_alert(uid, alert_id)
    return jsonify({"status": "deleted"})


@app.route("/api/technicals/<symbol>")
@login_required
def api_technicals(symbol):
    data = get_technicals(symbol.upper())
    return jsonify(data)


@app.route("/api/ticker-info/<symbol>")
@login_required
def api_ticker_info(symbol):
    sym = symbol.upper()
    info = get_ticker_info(sym)
    if not info:
        info = fetch_ticker_info(sym)
    return jsonify(info or {"symbol": sym, "name": sym})


@app.route("/api/ai-universe")
@login_required
def api_ai_universe():
    sectors = []
    all_syms = []
    for name, meta in AI_UNIVERSE.items():
        all_syms.extend(meta["tickers"])

    sentiment = get_sentiment_snapshot(list(set(all_syms)), hours=24)

    # Add quotes for all AI universe tickers present in cache
    for name, meta in AI_UNIVERSE.items():
        tickers = []
        for sym in meta["tickers"]:
            q = _quotes_cache.get(sym, {})
            entry = {
                "symbol": sym,
                "name": q.get("name", sym),
                "price": q.get("price", 0),
                "change_pct": q.get("change_pct", 0),
                "change": q.get("change", 0),
            }
            s = sentiment.get(sym)
            if s:
                entry["sentiment"] = s
            tickers.append(entry)
        sectors.append({
            "name": name,
            "color": meta["color"],
            "desc": meta["desc"],
            "tickers": tickers,
        })
    return jsonify({"sectors": sectors})


@app.route("/api/correlation")
@login_required
def api_correlation():
    """Latest 30-day/90-day rolling cross-asset correlation matrix (FSI L2)."""
    window = request.args.get("window", "30", type=int)
    if window not in (30, 90):
        return jsonify({"error": "window must be 30 or 90"}), 400
    pairs = get_latest_correlation_matrix(window)
    return jsonify({
        "window_days": window,
        "computed_at": pairs[0]["computed_at"] if pairs else None,
        "pairs": [{"symbol_a": p["symbol_a"], "symbol_b": p["symbol_b"], "correlation": p["correlation"]} for p in pairs],
    })


@app.route("/api/sector-rotation")
@login_required
def api_sector_rotation():
    """Sector rotation leader/laggard ranking -- 11 SPDR sector ETFs' 5d/20d
    relative strength vs SPY (FSI L2). Cached 15min, see sector_rotation.py."""
    rankings = get_sector_rotation()
    return jsonify({"sectors": rankings, "benchmark": "SPY"})


@app.route("/api/housing-starts")
@login_required
def api_housing_starts():
    """Housing starts & building permits (FRED HOUST/PERMIT), real-economy
    leading-indicator macro badge (FSI L2) -- cached 6h, see housing_starts.py."""
    return jsonify(get_housing_starts() or {})


@app.route("/api/copper-gold-ratio")
@login_required
def api_copper_gold_ratio():
    """CPER-vs-GLD "Dr. Copper" growth-vs-safe-haven regime signal (FSI L2)
    -- cached 15min, see copper_gold_ratio.py."""
    return jsonify(get_copper_gold_ratio() or {})


@app.route("/api/ppi")
@login_required
def api_ppi():
    """Producer Price Index Final Demand (FRED PPIFIS) -- upstream
    wholesale-inflation leading indicator (FSI L2), distinct from the
    downstream Core PCE consumer-inflation gauge -- cached 1h, see
    ppi_client.py."""
    return jsonify(get_ppi() or {})
@app.route("/api/retail-sales")
@login_required
def api_retail_sales():
    """Advance Retail Sales (FRED RSAFS) -- forward consumer-demand signal
    (FSI L2) -- cached 1h, see retail_sales_client.py."""
    return jsonify(get_retail_sales() or {})
@app.route("/api/durable-goods")
@login_required
def api_durable_goods():
    """Durable Goods New Orders (FRED DGORDER) -- forward-looking business
    capex signal (FSI L2) -- cached 1h, see durable_goods_client.py."""
    return jsonify(get_durable_goods_orders() or {})
@app.route("/api/credit-spread")
@login_required
def api_credit_spread():
    """Moody's Baa Corporate Yield Spread (BAA10Y) -- investment-grade
    credit stress gauge (FSI L3) -- cached 1h, see credit_spread_client.py."""
    return jsonify(get_credit_spread() or {})
@app.route("/api/core-pce")
@login_required
def api_core_pce():
    """Core PCE Price Index (PCEPILFE) -- the Fed's actual inflation-target
    gauge (FSI L2) -- cached 1h, see core_pce_client.py."""
    return jsonify(get_core_pce() or {})
@app.route("/api/industrial-production")
@login_required
def api_industrial_production():
    """Industrial Production Index (INDPRO) real-economy hard-data
    manufacturing/output badge (FSI L2) -- cached 1h, see
    industrial_production_client.py."""
    return jsonify(get_industrial_production() or {})
@app.route("/api/fed-funds-expectations")
@login_required
def api_fed_funds_expectations():
    """CBOT ZQ futures term structure vs current FRED DFF effective rate --
    market-implied Fed rate-path expectations (FSI L2). Cached 1h, see
    fed_funds_futures_client.py."""
    return jsonify(get_fed_funds_expectations() or {})
@app.route("/api/cpi-consensus")
@login_required
def api_cpi_consensus():
    """Kalshi KXCPIYOY threshold-ladder market-implied median CPI-YoY forecast
    (FSI L2) -- cached 1h, see cpi_consensus_market.py."""
    return jsonify(get_cpi_consensus() or {})
@app.route("/api/payrolls-consensus")
@login_required
def api_payrolls_consensus():
    """Kalshi KXPAYROLLS threshold ladder -- market-implied median Non-Farm
    Payrolls forecast ahead of the BLS print (FSI L2). Cached 1h, see
    payrolls_consensus_market.py."""
    return jsonify(get_payrolls_consensus() or {})
@app.route("/api/fed-decision-odds")
@login_required
def api_fed_decision_odds():
    """Kalshi FOMC-decision prediction market -- real-money implied probability
    distribution over the next Fed rate decision (FSI L2). Cached 1h, see
    fed_decision_market.py."""
    return jsonify(get_fed_decision_odds() or {})
@app.route("/api/repo-stress")
@login_required
def api_repo_stress():
    """Repo funding-market stress (SOFR vs EFFR overnight spread), dealer
    balance-sheet/collateral plumbing signal (FSI L2) -- cached 1h, see
    repo_funding_stress.py."""
    return jsonify(get_repo_stress() or {})
@app.route("/api/treasury-auction-demand")
@login_required
def api_treasury_auction_demand():
    """10Y/30Y Treasury auction indirect-bidder share + bid-to-cover trend
    (FSI L2) -- cached 1h, see treasury_auction_client.py."""
    return jsonify(get_treasury_auction_demand() or {})
@app.route("/api/credit-oas-spread")
@login_required
def api_credit_oas_spread():
    """ICE BofA option-adjusted credit spreads (HY/IG, actual bps level, not
    an ETF relative-strength proxy) -- credit-stress regime signal (FSI L4)
    -- cached 1h, see credit_oas_spread.py."""
    return jsonify(get_credit_oas_spread() or {})
@app.route("/api/commodity-curve")
@login_required
def api_commodity_curve():
    """WTI crude + gold contract-month curves, contango/backwardation
    classification per basket (FSI L3) -- cached 15min, see
    commodity_futures_curve.py."""
    return jsonify(get_commodity_futures_curve() or {})
@app.route("/api/vvix-index")
@login_required
def api_vvix_index():
    """CBOE VVIX (volatility-of-VIX) tail-risk hedging badge (FSI L2)
    -- cached 15min, see vvix_index.py."""
    return jsonify(get_vvix_index() or {})
@app.route("/api/stlfsi-index")
@login_required
def api_stlfsi_index():
    """St. Louis Fed Financial Stress Index -- weekly 18-variable
    interest-rate/credit/volatility composite (FSI L2) -- cached 12h,
    see stlfsi_index.py."""
    return jsonify(get_stlfsi_index() or {})
@app.route("/api/consumer-sentiment")
@login_required
def api_consumer_sentiment():
    """University of Michigan Consumer Sentiment Index (UMCSENT), the only
    survey-based consumer-psychology macro badge (FSI L2) -- cached daily,
    see consumer_sentiment.py."""
    return jsonify(get_consumer_sentiment() or {})
@app.route("/api/cross-market-contagion")
@login_required
def api_cross_market_contagion():
    """SPY vs EEM/EWJ/EWG/FXI rolling correlation regime -- contagion_risk
    flags when 3+ pairs read "coupled" simultaneously (FSI L5) -- cached
    15min, see cross_market_contagion.py."""
    return jsonify(get_cross_market_contagion() or {})
@app.route("/api/nfci-index")
@login_required
def api_nfci_index():
    """Chicago Fed National Financial Conditions Index -- broad market-wide
    liquidity/leverage/risk regime signal (FSI L2) -- cached 1h, see
    nfci_index.py."""
    return jsonify(get_nfci_index() or {})
@app.route("/api/sahm-rule")
@login_required
def api_sahm_rule():
    """Sahm Rule recession-trigger indicator (FSI L3) -- cached daily,
    see sahm_rule.py."""
    return jsonify(get_sahm_rule() or {})
@app.route("/api/variance-risk-premium")
@login_required
def api_variance_risk_premium():
    """VIX implied vol vs SPY trailing realized vol gap (FSI L2)
    -- cached 15min, see variance_risk_premium.py."""
    return jsonify(get_variance_risk_premium() or {})
@app.route("/api/dollar-index")
@login_required
def api_dollar_index():
    """Broad Dollar Index (FRED DTWEXBGS), currency-market macro regime
    signal (FSI L2) -- cached 1h, see dollar_index_client.py."""
    return jsonify(get_dollar_index() or {})
@app.route("/api/oss-velocity/<ticker>")
@login_required
def api_oss_velocity(ticker):
    """Weekly commit-count/contributor trend for open-source-native tickers
    where the ticker->flagship-repo mapping is unambiguous (FSI L5) --
    cached 24h, see oss_velocity_client.py."""
    ticker = ticker.upper()
    if ticker not in TRACKED_REPOS:
        return jsonify({"error": "ticker not tracked", "tracked": sorted(TRACKED_REPOS)}), 404
    snapshot = get_velocity_snapshot(ticker)
    return jsonify(snapshot or {"ticker": ticker, "status": "unavailable"})
@app.route("/api/crypto-fear-greed")
@login_required
def api_crypto_fear_greed():
    """Crypto-specific Fear & Greed composite (alternative.me), distinct from
    the equity CNN Fear & Greed badge and the BTC on-chain health metrics --
    cached 1h, see crypto_fear_greed.py."""
    return jsonify(get_crypto_fear_greed() or {})
@app.route("/api/market-breadth")
@login_required
def api_market_breadth():
    """RSP-vs-SPY equal-weight/cap-weight market breadth signal (FSI L2)
    -- cached 15min, see market_breadth.py."""
    return jsonify(get_market_breadth() or {})
@app.route("/api/epu-index")
@login_required
def api_epu_index():
    """Economic Policy Uncertainty Index (Baker/Bloom/Davis) news-based
    macro-uncertainty trend badge (FSI L2) -- cached 15min, see epu_index.py."""
    return jsonify(get_epu_index() or {})
@app.route("/api/fed-liquidity")
@login_required
def api_fed_liquidity():
    """Fed balance sheet (WALCL) / M2 money supply (M2SL) liquidity regime
    (FSI L2) -- cached 12h, see fed_liquidity.py."""
    return jsonify(get_liquidity_snapshot() or {})
@app.route("/api/breakeven-inflation")
@login_required
def api_breakeven_inflation():
    """10Y breakeven inflation rate (FRED T10YIE), market-implied inflation
    expectation (FSI L2) -- cached 1h, see breakeven_inflation.py."""
    return jsonify(get_breakeven_inflation() or {})
@app.route("/api/skew-index")
@login_required
def api_skew_index():
    """CBOE SKEW Index tail-risk gauge (FSI L2) -- cached 15min, see skew_index.py."""
    return jsonify(get_skew_index() or {})
@app.route("/api/median-home-price")
@login_required
def api_median_home_price():
    """Median Sales Price of Houses Sold (FRED MSPUS), absolute housing-price
    level vs Case-Shiller's index-based appreciation rate (FSI L2) -- cached
    6h, see median_home_price_client.py."""
    return jsonify(get_median_home_price() or {})


@app.route("/api/dark-pool/<ticker>")
@login_required
def api_dark_pool(ticker):
    """Weekly off-exchange (dark pool / ATS) share-volume trend (FSI L2)
    -- lazy per-symbol, cached 24h, see dark_pool_client.py. Publishes on a
    ~2-3 week lag, never a same-week signal."""
    return jsonify(get_dark_pool_signal(ticker) or {})


@app.route("/api/ticker-debate/<symbol>")
@login_required
def api_ticker_debate(symbol):
    """Bull/Bear/Macro-Moderator adversarial debate panel for a ticker
    (FSI L4) -- serves a cached verdict (<=6h old) or runs a fresh panel.
    See ticker_debate.py."""
    result = get_ticker_debate(symbol.upper())
    if not result:
        return jsonify({"error": "debate panel unavailable — AI backend or parsing failed"}), 503
    return jsonify(result)


@app.route("/api/lead-lag")
@login_required
def api_lead_lag():
    """Granger-causality lead-lag relationships across a curated set of
    macro-to-market pairs (FSI L2) -- cached 6h, see lead_lag_engine.py."""
    return jsonify({"pairs": get_lead_lag()})


@app.route("/api/vault/search")
@login_required
def api_vault_search():
    """Local semantic search over the FredAI vault journal (FSI L4) --
    debugging/direct-testing endpoint for the same search chat uses
    automatically, see vault_semantic_search.py."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"results": []})
    return jsonify({"results": semantic_search(q)})


@app.route("/api/vault/reindex", methods=["POST"])
@login_required
def api_vault_reindex():
    """Manually trigger an incremental vault reindex (also runs on its
    own 6h cron, see job_vault_reindex)."""
    return jsonify(reindex_vault())


@app.route("/api/optimized-params/<ticker>")
@login_required
def api_optimized_params(ticker):
    """Best-scoring RSI / MA-cross parameter combo for this ticker, from
    the daily grid-search backtest (FSI L3) -- see param_optimizer.py."""
    return jsonify({"ticker": ticker.upper(), "params": get_optimized_params(ticker.upper())})


@app.route("/api/ticker-relationships")
@login_required
def api_ticker_relationships():
    """Small, focused relationship network for the user's own tracked tickers
    (portfolio + watchlist) -- both known business relationships and
    statistically-correlated tickers, honestly distinguished."""
    uid = session["user_id"]
    wl_rows = get_watchlist(uid)
    portfolio_rows = get_portfolio(uid)
    tracked = list(set([r["symbol"] for r in wl_rows] + [r["symbol"] for r in portfolio_rows]))
    if not tracked:
        tracked = WATCHLIST[:6]  # sensible default for a fresh account with nothing tracked yet
    network = get_ticker_network(tracked, quotes=_quotes_cache or {})
    return jsonify(network)


@app.route("/api/user/layout", methods=["GET"])
@login_required
def api_get_layout():
    """Per-page widget layout (hidden + order) -- lets users show only the
    widgets that add value to them, per FSI institutional-grade UX bar."""
    page = request.args.get("page", "").strip()
    if not page:
        return jsonify({"error": "page is required"}), 400
    return jsonify(get_layout_prefs(session["user_id"], page))


@app.route("/api/user/layout", methods=["POST"])
@login_required
def api_save_layout():
    data = request.json or {}
    page = str(data.get("page", "")).strip()
    hidden = data.get("hidden", [])
    order = data.get("order", {})
    sizes = data.get("sizes")
    state = data.get("state")
    if not page:
        return jsonify({"error": "page is required"}), 400
    if not isinstance(hidden, list) or not all(isinstance(h, str) for h in hidden):
        return jsonify({"error": "hidden must be a list of widget ids"}), 400
    if not isinstance(order, dict) or not all(isinstance(v, int) for v in order.values()):
        return jsonify({"error": "order must be a widget id -> position map"}), 400
    if sizes is not None and (not isinstance(sizes, dict) or not all(isinstance(v, str) for v in sizes.values())):
        return jsonify({"error": "sizes must be a widget id -> size string map"}), 400
    if state is not None and not isinstance(state, dict):
        return jsonify({"error": "state must be an object"}), 400
    save_layout_prefs(session["user_id"], page, hidden, order, sizes=sizes, state=state)
    return jsonify({"status": "ok"})


@app.route("/api/insider/<ticker>")
@login_required
def api_insider_transactions(ticker):
    """Recent SEC Form 4 open-market insider buy/sell transactions (FSI L2)."""
    days = request.args.get("days", "90", type=int)
    txns = get_recent_insider_transactions(ticker.upper(), days=days, signal_only=True)
    return jsonify({"ticker": ticker.upper(), "days": days, "transactions": txns})


@app.route("/api/short-volume/<ticker>")
@login_required
def api_short_volume(ticker):
    """Daily FINRA Reg SHO short-volume ratio + rolling trend (FSI L2) --
    distinct from the slower Finviz short-interest snapshot in /api/portfolio
    and /api/watchlist."""
    signal = compute_short_volume_signal(ticker.upper())
    return jsonify(signal or {"symbol": ticker.upper(), "short_volume_pct": None, "trend": None})


@app.route("/api/whale-activity/<symbol>")
@login_required
def api_whale_activity(symbol):
    """Composite "Whale Activity Index" (FSI L1/L2) blending FINRA short-
    volume + dark-pool/ATS z-scores -- an honest free-data proxy for
    institutional activity, not literal block/sweep-print data. See
    whale_activity.py."""
    result = compute_whale_activity(symbol.upper())
    return jsonify(result or {"ticker": symbol.upper(), "whale_index": None, "band": None})


@app.route("/api/assessment/<symbol>")
@login_required
def api_assessment(symbol):
    """Fred's buy/sell/hold signal for a symbol."""
    sym = symbol.upper()
    uid = session["user_id"]
    quote = _quotes_cache.get(sym, {})
    news_items = get_news(ticker=sym, hours=48, limit=10)
    technicals = get_technicals(sym)
    portfolio_rows = get_portfolio(uid)
    position = next((dict(r) for r in portfolio_rows if r.get("symbol") == sym), None)
    assessment = generate_assessment(sym, news_items, quote, technicals, position)
    return jsonify(assessment)


@app.route("/api/assessments")
@login_required
def api_assessments():
    """Fred's assessment for entire watchlist."""
    uid = session["user_id"]
    wl_rows = get_watchlist(uid)
    symbols = [r["symbol"] for r in wl_rows] if wl_rows else WATCHLIST[:5]
    portfolio_rows = get_portfolio(uid)
    results = []
    for sym in symbols[:8]:
        quote = _quotes_cache.get(sym, {})
        news_items = get_news(ticker=sym, hours=48, limit=8)
        technicals = {}
        position = next((dict(r) for r in portfolio_rows if r.get("symbol") == sym), None)
        a = generate_assessment(sym, news_items, quote, technicals, position)
        results.append(a)
    return jsonify({"assessments": results})


@app.route("/timeline/<symbol>")
@login_required
def timeline_page(symbol):
    return render_template("timeline.html", symbol=symbol.upper())


@app.route("/api/timeline/<symbol>")
@login_required
def api_timeline(symbol):
    """Chronological intelligence timeline for a symbol."""
    sym = symbol.upper()
    uid = session["user_id"]
    bump_interest(uid, sym, delta=0.5)

    news = get_news(ticker=sym, hours=168, limit=50)  # 7d
    calendar = get_calendar_events(days=30)
    sym_calendar = [e for e in calendar if e.get("symbol") == sym]

    quote = _quotes_cache.get(sym, {})
    technicals = get_technicals(sym)
    portfolio_rows = get_portfolio(uid)
    position = next((dict(r) for r in portfolio_rows if r.get("symbol") == sym), None)

    from cascade_engine import _ADJ
    relationships = _ADJ.get(sym, [])

    assessment = _ai_assessment_cache.get(sym, {}).get("data")

    events = []
    for n in news:
        events.append({
            "type": "news",
            "ts": n.get("published_at") or n.get("fetched_at", ""),
            "title": n.get("title", ""),
            "source": n.get("source", ""),
            "url": n.get("url", ""),
            "sentiment": n.get("sentiment_score", 0),
            "category": n.get("category", "market"),
        })
    for e in sym_calendar:
        events.append({
            "type": "calendar",
            "ts": e.get("event_date", "") + "T" + (e.get("event_time") or "00:00"),
            "title": e.get("title", ""),
            "importance": e.get("importance", "medium"),
            "event_type": e.get("event_type", ""),
            "eps_forecast": e.get("eps_forecast"),
            "eps_actual": e.get("eps_actual"),
        })

    events.sort(key=lambda x: x.get("ts", ""), reverse=True)

    return jsonify({
        "symbol": sym,
        "quote": quote,
        "technicals": technicals,
        "position": position,
        "assessment": assessment,
        "relationships": relationships[:12],
        "events": events,
        "generated_at": datetime.utcnow().isoformat(),
    })


@app.route("/api/cascade/<symbol>")
@login_required
def api_cascade(symbol):
    """Cascade impact analysis for a symbol."""
    sym = symbol.upper()
    q = _quotes_cache.get(sym, {})
    magnitude = float(request.args.get("magnitude", q.get("change_pct", 0)))
    event_type = request.args.get("event_type", "price_move")
    description = f"{sym} moved {magnitude:+.2f}%"
    cascades = cascade_for_event(sym, event_type, magnitude, description)
    # Augment with live quotes
    for c in cascades:
        cq = _quotes_cache.get(c["symbol"], {})
        c["price"] = cq.get("price", 0)
        c["change_pct"] = cq.get("change_pct", 0)
        c["name"] = cq.get("name", c["symbol"])
    return jsonify({
        "trigger_symbol": sym,
        "magnitude": magnitude,
        "event_type": event_type,
        "cascades": cascades,
        "generated_at": datetime.utcnow().isoformat(),
    })


@app.route("/api/signal-density")
@login_required
def api_signal_density():
    """Signal density scores for watchlist + portfolio symbols."""
    uid = session["user_id"]
    wl_rows = get_watchlist(uid)
    portfolio_rows = get_portfolio(uid)
    watchlist = [r["symbol"] for r in wl_rows] if wl_rows else WATCHLIST
    port_syms = [r["symbol"] for r in portfolio_rows]
    all_syms = list(dict.fromkeys(watchlist + port_syms + WATCHLIST[:5]))

    from cascade_engine import _ADJ
    scores = compute_signal_density(
        symbols=all_syms,
        quotes=_quotes_cache,
        get_news_fn=get_news,
        get_calendar_fn=get_calendar_events,
        assessment_cache=_ai_assessment_cache,
        adjacency=_ADJ,
    )
    return jsonify({"scores": scores, "generated_at": datetime.utcnow().isoformat()})


@app.route("/api/query", methods=["POST"])
@login_required
def api_fred_query():
    """
    Fred Query Bar — natural language market queries.
    POST {"query": "show me AI stocks with positive momentum"}
    Returns structured results filtered from Fred's universe.
    """
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "query required"}), 400

    uid = session["user_id"]
    wl_rows = get_watchlist(uid)
    portfolio_rows = get_portfolio(uid)
    watchlist = [r["symbol"] for r in wl_rows]
    port_syms = [r["symbol"] for r in portfolio_rows]

    from agent import _provider, FRED_SYSTEM
    from cascade_engine import _ADJ
    from graph_engine import SECTORS, SECTOR_COLORS

    # Build universe context
    universe_lines = []
    for sym, q in _quotes_cache.items():
        sector = SECTORS.get(sym, "Other")
        assess = _ai_assessment_cache.get(sym, {}).get("data", {})
        universe_lines.append(
            f"{sym}|{q.get('name',sym)}|{sector}|"
            f"${q.get('price',0):.2f}|{q.get('change_pct',0):+.2f}%|"
            f"signal={assess.get('signal','?')}|watchlist={'Y' if sym in watchlist else 'N'}|"
            f"portfolio={'Y' if sym in port_syms else 'N'}"
        )

    universe_text = "\n".join(universe_lines[:120])

    prompt = f"""User query: "{query}"

Available stocks (symbol|name|sector|price|change%|signal|watchlist|portfolio):
{universe_text}

Return a JSON object:
{{
  "interpretation": "one sentence: what the user is asking for",
  "results": [
    {{"symbol":"NVDA","name":"NVIDIA","sector":"Semiconductors","reason":"matches because..."}}
  ],
  "summary": "2 sentences summarising the findings"
}}

Filter and rank the stock list to answer the query. Return max 10 results.
Only return valid JSON, no markdown."""

    try:
        raw = _provider.complete(
            [{"role": "user", "content": prompt}],
            FRED_SYSTEM,
            tier="summary",
            max_tokens=1600,  # headroom for reasoning models that think inline
        )
        import re as _re, json as _json
        # Strip markdown fences and leading/trailing reasoning prose
        # then find the first complete JSON object anywhere in the response
        clean = _re.sub(r"```(?:json)?\s*|\s*```", "", raw)
        m = _re.search(r'\{[\s\S]*\}', clean)
        result = _json.loads(m.group()) if m else _json.loads(clean.strip())
    except Exception:
        result = {
            "interpretation": query,
            "results": [],
            "summary": "Query processing encountered an error. Please try again.",
        }

    # Augment results with live quote data
    # Fall back to on-demand yfinance fetch for any symbol the LLM returned
    # that isn't already in the cache (e.g. LLM suggested a symbol outside watchlist)
    missing = [r["symbol"] for r in result.get("results", []) if r["symbol"] not in _quotes_cache]
    if missing:
        try:
            fresh = fetch_quotes(missing)
            _quotes_cache.update(fresh)
        except Exception:
            pass

    for r in result.get("results", []):
        q = _quotes_cache.get(r["symbol"], {})
        r["price"] = q.get("price", 0)
        r["change_pct"] = q.get("change_pct", 0)
        r["color"] = SECTOR_COLORS.get(SECTORS.get(r["symbol"], ""), "#4a6380")

    result["query"] = query
    result["generated_at"] = datetime.utcnow().isoformat()
    return jsonify(result)


@app.route("/api/ops-picture")
@login_required
def api_ops_picture():
    """Operational picture: today's events, cascade alerts, top signal-density stocks."""
    uid = session["user_id"]
    wl_rows = get_watchlist(uid)
    watchlist = [r["symbol"] for r in wl_rows] if wl_rows else WATCHLIST
    port_rows = get_portfolio(uid)
    port_syms = [r["symbol"] for r in port_rows]

    # Today's calendar events (high importance)
    today_events = [
        e for e in get_calendar_events(days=3)
        if e.get("importance") in ("high", "critical")
    ]

    # Major price moves + their cascades
    cascades_today = run_cascade_check(_quotes_cache)

    # Top 5 signal density
    all_syms = list(dict.fromkeys(watchlist + port_syms + WATCHLIST[:5]))
    from cascade_engine import _ADJ
    density = compute_signal_density(
        symbols=all_syms,
        quotes=_quotes_cache,
        get_news_fn=get_news,
        get_calendar_fn=get_calendar_events,
        assessment_cache=_ai_assessment_cache,
        adjacency=_ADJ,
    )[:5]

    # Recent news alerts (high sentiment)
    hot_news = get_news(hours=4, limit=5)

    return jsonify({
        "today_events": today_events[:8],
        "cascades": cascades_today[:4],
        "top_signals": density,
        "hot_news": hot_news,
        "market_status": _get_market_status(),
        "generated_at": datetime.utcnow().isoformat(),
    })


def _get_market_status() -> dict:
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    weekday = now_utc.weekday()
    if weekday >= 5:
        return {"status": "CLOSED", "label": "Weekend", "color": "#4a6380"}
    if 14 <= hour < 21:  # 9:30am–4pm ET (UTC-5 approx)
        return {"status": "OPEN", "label": "US Market Open", "color": "#00ff88"}
    if 13 <= hour < 14:
        return {"status": "PRE", "label": "Pre-Market", "color": "#f5a623"}
    if 21 <= hour < 22:
        return {"status": "AH", "label": "After Hours", "color": "#9b59ff"}
    return {"status": "CLOSED", "label": "Market Closed", "color": "#4a6380"}


@app.route("/api/alerts")
@login_required
def api_alerts():
    """Fred's own alert stream -- sentiment shifts, volume spikes, insider
    clusters, and fired technical (price/RSI/MA/volume) alerts, all funneled
    through the same `alerts` table via insert_alert(). This is the real
    price-action/volatility signal, not a separate detector."""
    limit = min(max(request.args.get("limit", 10, type=int), 1), 50)
    return jsonify({"alerts": get_recent_alerts(limit=limit)})


@app.route("/api/asx/quotes")
@login_required
def api_asx_quotes():
    """Live ASX quotes (AUD). Returns quotes for all tracked ASX tickers."""
    asx_live = {sym: q for sym, q in _quotes_cache.items() if is_asx_ticker(sym)}
    # Return sector groupings too
    from asx_client import ASX_SECTORS
    sectors: dict = {}
    for sym, q in asx_live.items():
        sec = ASX_SECTORS.get(sym, "ASX")
        sectors.setdefault(sec, []).append(q)
    return jsonify({
        "quotes": asx_live,
        "sectors": sectors,
        "sector_colors": ASX_SECTOR_COLORS,
        "count": len(asx_live),
        "currency": "AUD",
        "generated_at": datetime.utcnow().isoformat(),
    })


@app.route("/api/asx/news")
@login_required
def api_asx_news():
    """Australian-scoped news feed."""
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 30))
    offset = (page - 1) * limit
    items = get_news(category="australia", hours=int(request.args.get("hours", 48)),
                     limit=limit, offset=offset)
    total = count_news(category="australia", hours=int(request.args.get("hours", 48)))
    return jsonify({"items": items, "total": total, "page": page, "limit": limit})


@app.route("/api/recommendations")
@login_required
def api_recommendations():
    """Fred's AI-powered picks: portfolio star, watchlist leader, trending discovery."""
    uid = session["user_id"]
    portfolio_raw = get_portfolio(uid)
    wl_rows = get_watchlist(uid)
    watchlist = [r["symbol"] for r in wl_rows] if wl_rows else WATCHLIST
    portfolio = calculate_portfolio_value(portfolio_raw, _quotes_cache)
    recs = generate_recommendations(_quotes_cache, portfolio, watchlist)
    return jsonify(recs)


# ── BACKGROUND JOBS ───────────────────────────────────────────────────────────

def job_asx_refresh():
    """Refresh ASX quotes separately (AUD-priced, staggered to avoid 429s)."""
    global _quotes_cache
    try:
        asx_quotes = fetch_asx_quotes()
        _quotes_cache.update(asx_quotes)
        print(f"[ASX] Refreshed {len(asx_quotes)} ASX quotes")
    except Exception as e:
        print(f"[ASX] Refresh error: {e}")


def job_market_refresh():
    global _quotes_cache, _macro_cache
    try:
        quotes = fetch_quotes()
        _quotes_cache = quotes
        signals_4h = get_signals_with_fallback(hours=4)
        stats = compute_sentiment_stats(signals_4h)
        alerts = get_recent_alerts(limit=5)
        risk = get_risk_level(stats, alerts)
        sector = get_sector_snapshot(quotes)
        trending = get_trending_assets_with_fallback(hours=4, limit=15)

        # Nasdaq macro data (cached 1h)
        try:
            macro = get_macro_snapshot()
            if macro:
                _macro_cache = macro
        except Exception:
            macro = _macro_cache

        # CNN Fear & Greed Index (cached 1h in fear_greed_client; stored once/day)
        try:
            fg = fetch_fear_greed()
            if fg and "score" in fg:
                _macro_cache = {**_macro_cache, "FEAR_GREED": {
                    "label": "Fear & Greed", "value": fg["score"], "rating": fg.get("rating"),
                    "change": round(fg["score"] - fg["previous_close"], 2) if fg.get("previous_close") is not None else None,
                }}
                if not get_trend_history("MARKET", "fear_greed", hours=20):
                    insert_trend("MARKET", "fear_greed", fg["score"], fg.get("rating", ""))
        except Exception as e:
            print(f"[Job] fear_greed error: {e}")

        # Copper/Gold "Dr. Copper" regime signal (cached 15min in copper_gold_ratio.py)
        try:
            cg = get_copper_gold_ratio()
            if cg:
                _macro_cache = {**_macro_cache, "COPPER_GOLD": {
                    "label": "Cu/Au", "value": cg["ratio"], "rating": cg["regime"],
                }}
        except Exception as e:
            print(f"[Job] copper_gold_ratio error: {e}")

        # Producer Price Index Final Demand -- upstream wholesale-inflation
        # leading indicator (cached 1h in ppi_client.py)
        try:
            ppi = get_ppi()
            if ppi:
                _macro_cache = {**_macro_cache, "PPI": {
                    "label": "PPI", "value": ppi["change_mom_pct"], "rating": ppi["regime"],
                }}
        except Exception as e:
            print(f"[Job] ppi_client error: {e}")
        # Advance Retail Sales -- forward consumer-demand signal
        # (cached 1h in retail_sales_client.py)
        try:
            rs = get_retail_sales()
            if rs:
                _macro_cache = {**_macro_cache, "RETAIL_SALES": {
                    "label": "Retail Sales", "value": rs["change_mom_pct"], "rating": rs["regime"],
                }}
        except Exception as e:
            print(f"[Job] retail_sales_client error: {e}")
        # Durable Goods New Orders -- forward-looking business capex signal
        # (cached 1h in durable_goods_client.py)
        try:
            dg = get_durable_goods_orders()
            if dg:
                _macro_cache = {**_macro_cache, "DURABLE_GOODS": {
                    "label": "Durable Goods", "value": dg["change_mom_pct"], "rating": dg["regime"],
                }}
        except Exception as e:
            print(f"[Job] durable_goods_client error: {e}")
        # Moody's Baa/10Y credit spread -- investment-grade credit stress (cached 1h in credit_spread_client.py)
        try:
            cs = get_credit_spread()
            if cs:
                _macro_cache = {**_macro_cache, "CREDIT_SPREAD": {
                    "label": "Baa-10Y", "value": cs["latest"], "rating": cs["regime"],
                }}
        except Exception as e:
            print(f"[Job] credit_spread error: {e}")
        # Core PCE Price Index -- Fed's actual inflation-target gauge (cached 1h in core_pce_client.py)
        try:
            pce = get_core_pce()
            if pce:
                _macro_cache = {**_macro_cache, "CORE_PCE": {
                    "label": "Core PCE", "value": pce["yoy_pct"], "rating": pce["regime"],
                }}
        except Exception as e:
            print(f"[Job] core_pce error: {e}")
        # Industrial Production Index (cached 1h in industrial_production_client.py)
        try:
            ip = get_industrial_production()
            if ip:
                _macro_cache = {**_macro_cache, "INDUSTRIAL_PRODUCTION": {
                    "label": "Ind. Prod.", "value": ip["latest"], "rating": ip["regime"],
                }}
        except Exception as e:
            print(f"[Job] industrial_production error: {e}")
        # Fed funds futures term structure -- market-implied rate-path
        # expectations (cached 1h in fed_funds_futures_client.py)
        try:
            ffe = get_fed_funds_expectations()
            if ffe and ffe.get("contracts"):
                front = ffe["contracts"][0]
                _macro_cache = {**_macro_cache, "FED_FUNDS_EXPECT": {
                    "label": "Fed Funds (front)", "value": front["implied_rate"], "rating": ffe["regime"],
                }}
        except Exception as e:
            print(f"[Job] fed_funds_futures error: {e}")
        # Kalshi KXCPIYOY threshold ladder -- market-implied median CPI-YoY forecast (cached 1h in cpi_consensus_market.py)
        try:
            cpi = get_cpi_consensus()
            if cpi:
                _macro_cache = {**_macro_cache, "CPI_CONSENSUS": {
                    "label": "CPI Consensus", "value": cpi["implied_median_pct"], "rating": cpi["release_date"],
                }}
        except Exception as e:
            print(f"[Job] cpi_consensus_market error: {e}")
        # Kalshi KXPAYROLLS market-implied median NFP forecast (cached 1h in payrolls_consensus_market.py)
        try:
            pc = get_payrolls_consensus()
            if pc:
                _macro_cache = {**_macro_cache, "PAYROLLS_CONSENSUS": {
                    "label": "NFP Est.", "value": pc["implied_median_k"], "rating": pc["release_date"],
                }}
        except Exception as e:
            print(f"[Job] payrolls_consensus_market error: {e}")
        # Kalshi FOMC-decision market odds (cached 1h in fed_decision_market.py)
        try:
            fd = get_fed_decision_odds()
            if fd:
                _macro_cache = {**_macro_cache, "FED_DECISION": {
                    "label": "Fed Odds", "value": round(fd["hold"] * 100, 1), "rating": fd["dominant_label"],
                }}
        except Exception as e:
            print(f"[Job] fed_decision_market error: {e}")
        # Housing starts & building permits real-economy leading indicator (cached 6h in housing_starts.py)
        try:
            hs = get_housing_starts()
            if hs:
                _macro_cache = {**_macro_cache, "HOUSING_STARTS": {
                    "label": "Housing Starts", "value": hs["starts"]["latest"], "rating": hs["regime"],
                }}
        except Exception as e:
            print(f"[Job] housing_starts error: {e}")
        # Repo funding-market stress: SOFR vs EFFR spread (cached 1h in repo_funding_stress.py)
        try:
            rs = get_repo_stress()
            if rs:
                _macro_cache = {**_macro_cache, "REPO_STRESS": {
                    "label": "Repo Stress", "value": rs["spread_bps"], "rating": rs["regime"],
                }}
        except Exception as e:
            print(f"[Job] repo_funding_stress error: {e}")
        # Treasury auction indirect-bidder demand (cached 1h in treasury_auction_client.py)
        try:
            ta = get_treasury_auction_demand()
            if ta:
                _macro_cache = {**_macro_cache, "TREASURY_AUCTION": {
                    "label": "Auction Demand", "value": ta["demand"], "rating": ta["demand"],
                }}
        except Exception as e:
            print(f"[Job] treasury_auction_client error: {e}")
        # ICE BofA OAS credit-stress signal (cached 1h in credit_oas_spread.py)
        try:
            oas = get_credit_oas_spread()
            if oas:
                _macro_cache = {**_macro_cache, "CREDIT_OAS": {
                    "label": "HY OAS", "value": oas["hy_oas"], "rating": oas["regime"],
                }}
        except Exception as e:
            print(f"[Job] credit_oas_spread error: {e}")
        # Commodity futures curve contango/backwardation (cached 15min in commodity_futures_curve.py)
        try:
            curve = get_commodity_futures_curve()
            extreme = most_extreme_basket(curve) if curve else None
            if extreme:
                _macro_cache = {**_macro_cache, "COMMODITY_CURVE": {
                    "label": "Cmdty Curve", "value": extreme["spread_pct"], "rating": extreme["classification"],
                }}
        except Exception as e:
            print(f"[Job] commodity_futures_curve error: {e}")
        # CBOE VVIX volatility-of-volatility tail-risk badge (cached 15min in vvix_index.py)
        try:
            vvix = get_vvix_index()
            if vvix:
                _macro_cache = {**_macro_cache, "VVIX": {
                    "label": "VVIX", "value": vvix["value"], "rating": vvix["regime"],
                }}
        except Exception as e:
            print(f"[Job] vvix_index error: {e}")
        # St. Louis Fed STLFSI4 financial-stress regime signal (cached 12h in stlfsi_index.py)
        try:
            stlfsi = get_stlfsi_index()
            if stlfsi:
                _macro_cache = {**_macro_cache, "STLFSI": {
                    "label": "STLFSI", "value": stlfsi["latest"], "rating": stlfsi["regime"],
                }}
        except Exception as e:
            print(f"[Job] stlfsi_index error: {e}")
        # UMCSENT consumer sentiment survey regime (cached daily in consumer_sentiment.py)
        try:
            cs = get_consumer_sentiment()
            if cs:
                _macro_cache = {**_macro_cache, "CONSUMER_SENTIMENT": {
                    "label": "Cons. Sentiment", "value": cs["latest"], "rating": cs["regime"],
                }}
        except Exception as e:
            print(f"[Job] consumer_sentiment error: {e}")
        # Cross-market contagion: SPY vs EEM/EWJ/EWG/FXI rolling correlation (cached 15min in cross_market_contagion.py)
        try:
            xmc = get_cross_market_contagion()
            if xmc:
                _macro_cache = {**_macro_cache, "CONTAGION": {
                    "label": "Contagion", "value": xmc["coupled_count"],
                    "rating": "risk" if xmc["contagion_risk"] else "normal",
                }}
        except Exception as e:
            print(f"[Job] cross_market_contagion error: {e}")
        # Chicago Fed NFCI broad financial-conditions regime signal (cached 1h in nfci_index.py)
        try:
            nfci = get_nfci_index()
            if nfci:
                _macro_cache = {**_macro_cache, "NFCI": {
                    "label": "NFCI", "value": nfci["latest"], "rating": nfci["regime"],
                }}
        except Exception as e:
            print(f"[Job] nfci_index error: {e}")
        # Sahm Rule recession-trigger indicator (cached daily in sahm_rule.py)
        try:
            sahm = get_sahm_rule()
            if sahm:
                _macro_cache = {**_macro_cache, "SAHM_RULE": {
                    "label": "Sahm Rule", "value": sahm["value"], "rating": sahm["regime"],
                }}
        except Exception as e:
            print(f"[Job] sahm_rule error: {e}")
        # Variance risk premium: VIX implied vol vs SPY realized vol (cached 15min)
        try:
            vrp = get_variance_risk_premium()
            if vrp:
                _macro_cache = {**_macro_cache, "VRP": {
                    "label": "VRP", "value": vrp["vrp"], "rating": vrp["regime"],
                }}
        except Exception as e:
            print(f"[Job] variance_risk_premium error: {e}")
        # Broad Dollar Index / DTWEXBGS currency regime signal (cached 1h in dollar_index_client.py)
        try:
            di = get_dollar_index()
            if di:
                _macro_cache = {**_macro_cache, "DOLLAR_INDEX": {
                    "label": "Broad $", "value": di["latest"], "rating": di["regime"],
                }}
        except Exception as e:
            print(f"[Job] dollar_index error: {e}")
        # Crypto Fear & Greed Index (cached 1h in crypto_fear_greed.py)
        try:
            cfg = get_crypto_fear_greed()
            if cfg:
                _macro_cache = {**_macro_cache, "CRYPTO_FNG": {
                    "label": "Crypto F&G", "value": cfg["value"], "rating": cfg["classification"],
                }}
        except Exception as e:
            print(f"[Job] crypto_fear_greed error: {e}")
        # Market breadth: RSP/SPY equal-weight vs cap-weight (cached 15min in market_breadth.py)
        try:
            mb = get_market_breadth()
            if mb:
                _macro_cache = {**_macro_cache, "MARKET_BREADTH": {
                    "label": "Breadth", "value": mb["ratio"], "rating": mb["regime"],
                }}
        except Exception as e:
            print(f"[Job] market_breadth error: {e}")
        # Economic Policy Uncertainty index (cached 15min in epu_index.py)
        try:
            epu = get_epu_index()
            if epu:
                _macro_cache = {**_macro_cache, "EPU": {
                    "label": "EPU", "value": epu["value"], "rating": epu["regime"],
                }}
        except Exception as e:
            print(f"[Job] epu_index error: {e}")
        # Fed balance sheet / M2 liquidity regime (cached 12h in fed_liquidity.py)
        try:
            liq = get_liquidity_snapshot()
            if liq:
                _macro_cache = {**_macro_cache, "FED_LIQUIDITY": {
                    "label": "Fed Liquidity", "value": liq["walcl"]["change_wow_pct"], "rating": liq["regime"],
                }}
        except Exception as e:
            print(f"[Job] fed_liquidity error: {e}")
        # 10Y breakeven inflation rate (cached 1h in breakeven_inflation.py)
        try:
            be = get_breakeven_inflation()
            if be:
                _macro_cache = {**_macro_cache, "BREAKEVEN_INFLATION": {
                    "label": "10Y Breakeven", "value": be["latest"], "rating": be["regime"],
                }}
        except Exception as e:
            print(f"[Job] breakeven_inflation error: {e}")
        # CBOE SKEW Index tail-risk gauge (cached 15min in skew_index.py)
        try:
            sk = get_skew_index()
            if sk:
                _macro_cache = {**_macro_cache, "SKEW": {
                    "label": "SKEW", "value": sk["value"], "rating": sk["band"],
                }}
        except Exception as e:
            print(f"[Job] skew_index error: {e}")
        # Median Sales Price of Houses Sold (cached 6h in median_home_price_client.py)
        try:
            mhp = get_median_home_price()
            if mhp:
                _macro_cache = {**_macro_cache, "MEDIAN_HOME_PRICE": {
                    "label": "Median Home $", "value": mhp["latest"], "rating": mhp["regime"],
                }}
        except Exception as e:
            print(f"[Job] median_home_price_client error: {e}")

        socketio.emit("market_update", {
            "quotes": quotes,
            "sector": sector,
            "stats": stats,
            "risk_level": risk,
            "trending": trending,
            "macro": _macro_cache,
            "timestamp": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        print(f"[Job] market_refresh error: {e}")


def job_scan_cycle():
    global _last_scan
    with _scan_lock:
        try:
            print(f"[Scan] Cycle starting at {datetime.utcnow().isoformat()}")
            period_start = _last_scan if _last_scan > datetime.min else datetime.utcnow() - timedelta(hours=4)
            period_end = datetime.utcnow()

            new_signals = fetch_signals()
            print(f"[Scan] Collected {len(new_signals)} signals")

            quotes = _quotes_cache or fetch_quotes()
            alerts = detect_trends(quotes)

            try:
                from memory_store import get_conn as _gc
                with _gc() as c:
                    port_syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM portfolio WHERE shares > 0").fetchall()]
                    wl_syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
                reversal_alerts = check_reversals(list(set(WATCHLIST + port_syms + wl_syms)))
                alerts += reversal_alerts
            except Exception as e:
                print(f"[Scan] Reversal detection error: {e}")

            for alert in alerts:
                socketio.emit("alert", alert)

            all_signals = get_signals_with_fallback(hours=4)
            summary_text = generate_summary(all_signals, quotes)
            stats = compute_sentiment_stats(all_signals)
            risk = get_risk_level(stats, alerts)
            from agent import _top_mentioned_assets
            key_signals = _top_mentioned_assets(all_signals)

            insert_summary(
                period_start=period_start,
                period_end=period_end,
                content=summary_text,
                key_signals=key_signals,
                overall_sentiment=stats["avg"],
                risk_level=risk,
                signal_count=len(all_signals),
            )

            trending = get_trending_assets_with_fallback(hours=4, limit=15)
            timeline = get_sentiment_timeline(hours=24)

            try:
                log_scan_outcomes(trending, quotes)
            except Exception as e:
                print(f"[Scan] backtest outcome logging error: {e}")

            socketio.emit("summary_update", {
                "summary": summary_text,
                "stats": stats,
                "risk_level": risk,
                "key_signals": key_signals,
                "trending": trending,
                "timestamp": datetime.utcnow().isoformat(),
                "next_scan": (datetime.utcnow() + timedelta(hours=SCAN_INTERVAL_HOURS)).isoformat(),
            })

            for s in new_signals[:20]:
                socketio.emit("new_signal", s)

            socketio.emit("timeline_update", {"timeline": timeline})
            _last_scan = period_end

            # Mirror to Obsidian vault
            write_signal_digest(all_signals, period_hours=4)
            write_summary_to_vault(summary_text, "last 4 hours", stats, risk)

            print(f"[Scan] Done. {len(all_signals)} signals. Risk: {risk}. Vault: {vault_available()}")
        except Exception as e:
            print(f"[Job] scan_cycle error: {e}")
            import traceback; traceback.print_exc()


# ── WEBSOCKET ─────────────────────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    print(f"[WS] Client {request.sid} connected")


@socketio.on("chat_message")
def on_chat(data):
    user_id = session.get("user_id", 0)
    user_msg = data.get("message", "").strip()
    image_url = data.get("image_data")
    if not user_msg and not image_url:
        return

    image_obj = None
    if image_url and ";base64," in image_url:
        try:
            header, base64_data = image_url.split(";base64,", 1)
            mime_type = header.split("data:", 1)[1]
            image_obj = {
                "mime_type": mime_type,
                "base64_data": base64_data
            }
        except Exception as e:
            print(f"[Chat Multimodal] Image parse error: {e}")

    history = _chat_histories.setdefault(user_id, [])
    history_item = {"role": "user", "content": user_msg}
    if image_obj:
        history_item["image"] = image_obj
    history.append(history_item)

    interests = get_user_interests(user_id, limit=5) if user_id else []
    # Pass portfolio for context — values anonymized per privacy settings in agent.py
    holdings = get_portfolio(user_id) if user_id else []
    portfolio = calculate_portfolio_value(holdings, _quotes_cache or {})
    response = chat(user_msg, history, quotes=_quotes_cache,
                    user_interests=interests, portfolio=portfolio)

    history.append({"role": "assistant", "content": response})
    if len(history) > 24:
        _chat_histories[user_id] = history[-20:]

    emit("chat_response", {"message": response, "timestamp": datetime.utcnow().isoformat()})


@socketio.on("view_symbol")
def on_view_symbol(data):
    uid = session.get("user_id")
    if uid and data.get("symbol"):
        bump_interest(uid, data["symbol"], delta=0.3)


# ── STARTUP ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== SENTINEL FI — Financial Intelligence Dashboard ===")
    init_db()

    # Claude's and Gemini's RnD cycles both write files and run `git add -A`
    # over the whole working tree, then commit + push. Without this lock,
    # two cycles firing in the same jitter window could interleave writes
    # into each other's commits or race on the push.
    _rnd_lock = threading.Lock()

    def job_rnd():
        if not _rnd_lock.acquire(blocking=False):
            print("[RnD] Skipped — Gemini RnD cycle already running")
            return
        try:
            from improve import run_improvement_cycle
            run_improvement_cycle()
        except Exception as e:
            print(f"[RnD] Cycle error: {e}")
        finally:
            _rnd_lock.release()

    def job_gemini_rnd():
        if not _rnd_lock.acquire(blocking=False):
            print("[Gemini RnD] Skipped — Claude RnD cycle already running")
            return
        try:
            from gemini_improve import run_gemini_improvement_cycle
            run_gemini_improvement_cycle()
        except Exception as e:
            print(f"[Gemini RnD] Cycle error: {e}")
        finally:
            _rnd_lock.release()

    def job_prune():
        """Data retention enforcement — GDPR Art.5 / APP 11.2 data minimisation."""
        from config import DATA_RETENTION_DAYS
        result = prune_old_data(DATA_RETENTION_DAYS)
        total = sum(result["deleted"].values())
        if total:
            print(f"[Prune] Removed {total} records older than {DATA_RETENTION_DAYS}d: {result['deleted']}")

    def job_news_refresh():
        """Refresh news from all sources every 30 minutes (global + ASX)."""
        try:
            wl_rows = []
            from memory_store import get_conn as _gc
            with _gc() as c:
                wl_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
            symbols = list(set(WATCHLIST + wl_rows))
            global_syms = [s for s in symbols if not is_asx_ticker(s)]
            asx_syms = [s for s in symbols if is_asx_ticker(s)]
            count = fetch_all_news(global_syms)
            # Australian news
            try:
                au_items = fetch_au_news(watchlist_asx=asx_syms)
                if au_items:
                    upsert_news_items(au_items)
                    count += len(au_items)
            except Exception as e:
                print(f"[ASX News] Error: {e}")
            deleted = prune_stale_news(NEWS_RETENTION_HOURS)
            print(f"[News] Refreshed — {count} new items (incl. AU), pruned {deleted} stale item(s) older than {NEWS_RETENTION_HOURS}h")
        except Exception as e:
            print(f"[News] Refresh error: {e}")

    def job_calendar_refresh():
        """Refresh earnings calendar daily."""
        try:
            from memory_store import get_conn as _gc
            with _gc() as c:
                wl_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
            symbols = list(set(WATCHLIST + wl_rows))
            result = refresh_calendar(symbols)
            print(f"[Calendar] Refreshed — {result}")
        except Exception as e:
            print(f"[Calendar] Refresh error: {e}")

    def job_short_interest_refresh():
        """Refresh Finviz short-interest snapshots daily for portfolio + watchlist symbols."""
        try:
            from memory_store import get_conn as _gc
            with _gc() as c:
                port_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM portfolio WHERE shares > 0").fetchall()]
                wl_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
            symbols = [s for s in set(port_rows + wl_rows) if not is_asx_ticker(s) and "-" not in s]
            if not symbols:
                return
            stored = refresh_short_interest(symbols)
            print(f"[Finviz] Short interest refreshed — {stored}/{len(symbols)} symbols")
        except Exception as e:
            print(f"[Finviz] Short interest refresh error: {e}")

    def job_short_volume_refresh():
        """Refresh FINRA Reg SHO daily short-volume ratios for portfolio +
        watchlist symbols, populate the watchlist-badge cache, and check for
        pressure spikes (FSI L2)."""
        global _short_volume_cache
        try:
            from memory_store import get_conn as _gc
            with _gc() as c:
                port_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM portfolio WHERE shares > 0").fetchall()]
                wl_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
            symbols = [s for s in set(port_rows + wl_rows) if not is_asx_ticker(s) and "-" not in s]
            if not symbols:
                return
            stored = refresh_short_volume(symbols)
            cache = {}
            for sym in symbols:
                signal = compute_short_volume_signal(sym)
                if signal:
                    cache[sym] = signal
            _short_volume_cache = cache
            alerts_fired = detect_short_volume_pressure(symbols)
            print(f"[FINRA] Short volume refreshed — {stored}/{len(symbols)} symbols, {len(alerts_fired)} pressure alert(s)")
        except Exception as e:
            print(f"[FINRA] Short volume refresh error: {e}")

    def job_vault_reindex():
        """Incremental semantic-search reindex of the FredAI vault journal
        (FSI L4) -- see vault_semantic_search.py."""
        try:
            result = reindex_vault()
            print(f"[VaultSearch] Reindexed — {result['indexed']} updated, {result['skipped']} unchanged")
        except Exception as e:
            print(f"[VaultSearch] Reindex error: {e}")

    def job_param_optimizer():
        """Daily grid-search backtest of RSI / MA-cross parameters per
        portfolio+watchlist ticker (FSI L3) -- see param_optimizer.py."""
        try:
            from memory_store import get_conn as _gc
            with _gc() as c:
                port_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM portfolio WHERE shares > 0").fetchall()]
                wl_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
            symbols = [s for s in set(port_rows + wl_rows) if not is_asx_ticker(s) and "-" not in s]
            if not symbols:
                return
            result = optimize_universe(symbols)
            print(f"[ParamOptimizer] Optimized {len(result)}/{len(symbols)} symbols")
        except Exception as e:
            print(f"[ParamOptimizer] Error: {e}")

    def job_insider_signals_refresh():
        """Refresh SEC Form 4 insider-trading data daily for portfolio + watchlist symbols,
        then check for buying/selling clusters (FSI L2)."""
        try:
            from memory_store import get_conn as _gc, insert_insider_transactions
            with _gc() as c:
                port_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM portfolio WHERE shares > 0").fetchall()]
                wl_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
            symbols = [s for s in set(port_rows + wl_rows) if not is_asx_ticker(s) and "-" not in s]
            if not symbols:
                return
            total_new = 0
            for sym in symbols:
                txns = fetch_form4_filings(sym, limit=5)
                total_new += insert_insider_transactions(txns)
            alerts_fired = detect_insider_clusters(symbols)
            _insider_cluster_cache.clear()
            for a in alerts_fired:
                _insider_cluster_cache[a["asset"]] = {"direction": a["direction"], "distinct_owners": a["distinct_owners"]}
            print(f"[SEC] Insider signals refreshed — {total_new} new transactions, {len(alerts_fired)} cluster alert(s)")
        except Exception as e:
            print(f"[SEC] Insider signals refresh error: {e}")

    def job_tech_alerts():
        """Check technical alerts every 5 minutes during market hours."""
        try:
            fired = run_technical_alerts()
            if fired:
                print(f"[TechAlerts] Fired {len(fired)} alerts")
                for alert in fired:
                    socketio.emit("alert", {"title": f"Technical Alert: {alert['symbol']}",
                                            "message": alert["message"], "level": "info"})
        except Exception as e:
            print(f"[TechAlerts] Error: {e}")

    def job_update_check():
        """Poll GitHub every 6h for new FredAI commits."""
        try:
            _updater.check_for_updates(emit_event=True)
        except Exception as e:
            print(f"[Updater] Check error: {e}")

    def job_community():
        """Engage with GitHub Issues, Discussions, and PRs every 6h."""
        try:
            from community import run_community_cycle
            summary = run_community_cycle()
            responded = summary.get("responses_posted", 0)
            if responded:
                print(f"[Community] Posted {responded} response(s) to GitHub")
        except Exception as e:
            print(f"[Community] Error: {e}")

    def job_gemini_community():
        """Engage with GitHub Issues, Discussions, and PRs via Gemini every 6h."""
        try:
            from gemini_community import run_gemini_community_cycle
            summary = run_gemini_community_cycle()
            responded = summary.get("responses_posted", 0)
            if responded:
                print(f"[Gemini Community] Posted {responded} response(s) to GitHub")
        except Exception as e:
            print(f"[Gemini Community] Error: {e}")

    def job_agent_debate():
        """Claude and Gemini review each other's open proposal Issues and
        post a stance + weighted consensus score every 6h."""
        try:
            from debate import run_debate_cycle
            summary = run_debate_cycle()
            print(f"[Debate] Checked {summary['issues_checked']} issue(s), "
                  f"posted {summary['stances_posted']} stance(s), {summary['errors']} error(s)")
        except Exception as e:
            print(f"[Debate] Error: {e}")

    def job_correlation_refresh():
        """Recompute 30d/90d rolling cross-asset correlation matrix every 6h (FSI L2)."""
        try:
            from memory_store import get_conn as _gc
            with _gc() as c:
                wl_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
            symbols = list(set(WATCHLIST + wl_rows))
            stored = refresh_correlation_matrix(symbols)
            print(f"[Correlation] Refreshed — {stored}")
        except Exception as e:
            print(f"[Correlation] Refresh error: {e}")

    def job_crypto_spread_refresh():
        """Cross-exchange crypto spread (BTC/ETH) via public exchange
        tickers -- a periodic enrichment signal, not real-time, so this runs
        on its own cadence separate from job_market_refresh's 60s interval."""
        from ccxt_client import get_cross_exchange_spread
        for sym in ("BTC-USD", "ETH-USD"):
            try:
                result = get_cross_exchange_spread(sym)
                if result:
                    _crypto_spread_cache[sym] = result
            except Exception as e:
                print(f"[CryptoSpread] {sym} error: {e}")

    def job_backtest_check():
        """Fill in due 4h/24h/72h price checkpoints for tracked signal
        outcomes (FSI L3 backtesting)."""
        try:
            result = run_backtest_check()
            if result["filled"]:
                print(f"[Backtest] Filled {result['filled']} checkpoint(s), {result['errors']} error(s)")
        except Exception as e:
            print(f"[Backtest] Error: {e}")

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(job_market_refresh, "interval", seconds=MARKET_REFRESH_SECONDS, id="market")
    scheduler.add_job(job_asx_refresh, "interval", seconds=120, id="asx")
    scheduler.add_job(job_scan_cycle, "interval", hours=SCAN_INTERVAL_HOURS, id="scan")
    scheduler.add_job(job_rnd, "interval", hours=6, id="rnd")
    scheduler.add_job(job_gemini_rnd, "interval", hours=6, id="gemini_rnd", jitter=1800)
    scheduler.add_job(job_prune, "cron", hour=2, minute=0, id="prune")
    scheduler.add_job(job_news_refresh, "interval", minutes=30, id="news")
    scheduler.add_job(job_calendar_refresh, "cron", hour=6, minute=0, id="calendar")
    scheduler.add_job(job_short_interest_refresh, "cron", hour=7, minute=0, id="short_interest")
    scheduler.add_job(job_short_volume_refresh, "cron", hour=7, minute=15, id="short_volume")
    scheduler.add_job(job_insider_signals_refresh, "cron", hour=7, minute=30, id="insider_signals")
    scheduler.add_job(job_param_optimizer, "cron", hour=7, minute=45, id="param_optimizer")
    scheduler.add_job(job_tech_alerts, "interval", minutes=5, id="tech_alerts")
    scheduler.add_job(job_update_check, "interval", hours=6, id="update_check")
    scheduler.add_job(job_community, "interval", hours=6, id="community", jitter=300)
    scheduler.add_job(job_gemini_community, "interval", hours=6, id="gemini_community", jitter=2100)
    scheduler.add_job(job_agent_debate, "interval", hours=6, id="agent_debate", jitter=900)
    scheduler.add_job(job_backtest_check, "interval", minutes=30, id="backtest_check")
    scheduler.add_job(job_correlation_refresh, "interval", hours=6, id="correlation", jitter=1200)
    scheduler.add_job(job_crypto_spread_refresh, "interval", minutes=15, id="crypto_spread", jitter=60)
    scheduler.add_job(job_vault_reindex, "interval", hours=6, id="vault_reindex", jitter=600)
    scheduler.start()

    # Auto-install shortcuts on first run (or if missing)
    def _auto_install():
        try:
            result = _installer.install(PORT)
            if result["success"] and result["actions"]:
                print(f"[Install] Shortcuts created: {', '.join(result['actions'])}")
            elif result.get("warnings"):
                print(f"[Install] {'; '.join(result['warnings'])}")
        except Exception as e:
            print(f"[Install] Auto-install skipped: {e}")

    threading.Thread(target=_auto_install, daemon=True).start()

    # Non-blocking startup: fetch market data + scan in background
    def _startup():
        global _quotes_cache
        print("[Init] Fetching initial market data (background)...")
        try:
            _quotes_cache = fetch_quotes()
        except Exception as e:
            print(f"[Init] Market fetch error: {e}")
        # ASX quotes (separate thread — AUD-priced, staggered)
        try:
            asx_q = fetch_asx_quotes()
            _quotes_cache.update(asx_q)
            print(f"[Init] ASX quotes: {len(asx_q)} symbols")
        except Exception as e:
            print(f"[Init] ASX fetch error: {e}")
        # Seed macro calendar events (instant — no network)
        try:
            from calendar_client import _seed_macro_events
            _seed_macro_events()
        except Exception as e:
            print(f"[Init] Calendar seed error: {e}")
        # Fetch earnings calendar for next 7 days
        threading.Thread(target=job_calendar_refresh, daemon=True).start()
        # Fetch initial news
        threading.Thread(target=job_news_refresh, daemon=True).start()
        print("[Init] Triggering initial scan...")
        job_scan_cycle()

    threading.Thread(target=_startup, daemon=True).start()

    print(f"[Init] Dashboard → http://localhost:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)
