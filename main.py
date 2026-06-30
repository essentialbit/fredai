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

from config import SECRET_KEY, PORT, SCAN_INTERVAL_HOURS, MARKET_REFRESH_SECONDS, WATCHLIST, DISPLAY_SYMBOLS
from memory_store import (
    init_db, get_signals, get_latest_summary, get_summaries,
    get_sentiment_timeline, get_recent_alerts, insert_summary,
    get_watchlist, add_to_watchlist, remove_from_watchlist,
    get_portfolio, upsert_portfolio,
    get_user_interests, bump_interest, decay_interests,
    get_trending_assets,
    verify_user, create_user, get_user,
    log_consent, has_consent, export_user_data, delete_user_data, prune_old_data,
)
from market_data import fetch_quotes, fetch_history, get_sector_snapshot, calculate_portfolio_value
from twitter_client import fetch_signals
from trend_detector import compute_sentiment_stats, detect_trends, get_risk_level
from agent import chat, generate_summary, generate_recommendations
from obsidian_bridge import write_summary_to_vault, write_signal_digest, vault_available
from nasdaq_client import get_macro_snapshot
from memory_store import (
    get_all_proposals, insert_feature_proposal,
    get_news, count_news, upsert_news_items,
    get_calendar_events, upsert_calendar_events,
    get_tech_alerts, create_tech_alert, delete_tech_alert,
    get_ticker_info, upsert_ticker_info,
)
from news_client import fetch_all_news, fetch_ticker_info
from calendar_client import refresh_calendar
from technical_alerts import run_technical_alerts, get_technicals
from graph_engine import build_graph, generate_assessment, _ai_assessment_cache
from cascade_engine import cascade_for_event, run_cascade_check, detect_major_moves
from signal_density import compute_signal_density, invalidate as invalidate_density
from config import PRIVACY_POLICY_VERSION, PRIVACY_MODE, STRIP_PORTFOLIO_FROM_AI, DATA_RETENTION_DAYS

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
        "tickers": ["TSLA", "UBER", "LYFT", "RIVN", "LCID", "GM", "F", "MOBILEYE", "MBLY"],
    },
    "Consumer AI": {
        "color": "#00ff88",
        "desc": "AI-powered consumer products, media, and entertainment",
        "tickers": ["AAPL", "AMZN", "GOOGL", "NFLX", "SPOT", "META", "SNAP", "PINS", "RBLX"],
    },
}

app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

_quotes_cache: dict = {}
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
        data = request.json or request.form
        user = verify_user(data.get("username", ""), data.get("password", ""))
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["display_name"] = user.get("display_name") or user["username"]
            return jsonify({"status": "ok", "display_name": session["display_name"]})
        return jsonify({"error": "Invalid credentials"}), 401
    return render_template("dashboard.html")


@app.route("/register", methods=["POST"])
def register():
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


@app.route("/")
def index():
    return render_template("dashboard.html")


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
    signals = get_signals(hours=4, limit=50)
    stats = compute_sentiment_stats(signals)
    summary = get_latest_summary()
    timeline = get_sentiment_timeline(hours=24)
    alerts = get_recent_alerts(limit=20)
    sector = get_sector_snapshot(quotes)
    risk = get_risk_level(stats, alerts)
    interests = get_user_interests(uid, limit=10)
    trending = get_trending_assets(hours=4, limit=15)
    next_scan = (_last_scan + timedelta(hours=SCAN_INTERVAL_HOURS)).isoformat() if _last_scan > datetime.min else None

    news_preview = get_news(hours=24, limit=6)
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
    period = request.args.get("period", "5d")
    interval = request.args.get("interval", "30m")
    return jsonify(fetch_history(symbol.upper(), period=period, interval=interval))


@app.route("/api/summaries")
@login_required
def api_summaries():
    return jsonify(get_summaries(limit=10))


@app.route("/api/trending")
@login_required
def api_trending():
    hours = int(request.args.get("hours", 4))
    trending = get_trending_assets(hours=hours, limit=20)
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
        add_to_watchlist(uid, sym, data.get("notes"))
        return jsonify({"status": "ok", "symbol": sym})
    if request.method == "DELETE":
        sym = (request.json or {}).get("symbol", "").upper()
        remove_from_watchlist(uid, sym)
        return jsonify({"status": "ok"})
    wl = get_watchlist(uid)
    quotes = _quotes_cache or {}
    result = []
    for w in wl:
        entry = dict(w)
        q = quotes.get(w["symbol"])
        if q:
            entry.update(q)
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
        upsert_portfolio(uid, sym, float(data.get("shares", 0)), float(data.get("avg_cost", 0)))
        return jsonify({"status": "ok"})
    if request.method == "DELETE":
        sym = (request.json or {}).get("symbol", "").upper()
        upsert_portfolio(uid, sym, 0, 0)
        return jsonify({"status": "ok"})
    holdings = get_portfolio(uid)
    portfolio = calculate_portfolio_value(holdings, _quotes_cache or {})
    return jsonify(portfolio)


@app.route("/api/scan", methods=["POST"])
@login_required
def api_manual_scan():
    socketio.start_background_task(job_scan_cycle)
    return jsonify({"status": "scan started"})


@app.route("/api/rnd/backlog")
@login_required
def api_rnd_backlog():
    return jsonify(get_all_proposals(limit=50))


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
    """Trigger a full R&D + implementation cycle (async)."""
    def _run():
        try:
            from improve import run_improvement_cycle
            results = run_improvement_cycle()
            socketio.emit("rnd_complete", results)
        except Exception as e:
            socketio.emit("rnd_complete", {"error": str(e)})
    socketio.start_background_task(_run)
    return jsonify({"status": "R&D cycle started"})


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
    # Require password re-confirmation before erasure
    import hashlib
    pw_hash = hashlib.sha256(data.get("password", "").encode()).hexdigest()
    if pw_hash != user["password_hash"]:
        return jsonify({"error": "Password confirmation required"}), 403
    ok = delete_user_data(uid)
    if ok:
        session.clear()
        return jsonify({"status": "deleted", "message": "All personal data has been permanently erased."})
    return jsonify({"error": "Deletion failed"}), 500


@app.route("/news")
@login_required
def news_page():
    return render_template("news.html")


@app.route("/graph")
@login_required
def graph_page():
    return render_template("graph.html")


@app.route("/api/news")
@login_required
def api_news():
    category = request.args.get("category", "all")
    ticker = request.args.get("ticker", "")
    hours = int(request.args.get("hours", 24))
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 30))
    offset = (page - 1) * limit
    items = get_news(category=category, ticker=ticker or None, hours=hours, limit=limit, offset=offset)
    total = count_news(category=category, ticker=ticker or None, hours=hours)
    return jsonify({"items": items, "total": total, "page": page, "limit": limit})


@app.route("/api/calendar")
@login_required
def api_calendar():
    days = int(request.args.get("days", 7))
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

    # Add quotes for all AI universe tickers present in cache
    for name, meta in AI_UNIVERSE.items():
        tickers = []
        for sym in meta["tickers"]:
            q = _quotes_cache.get(sym, {})
            tickers.append({
                "symbol": sym,
                "name": q.get("name", sym),
                "price": q.get("price", 0),
                "change_pct": q.get("change_pct", 0),
                "change": q.get("change", 0),
            })
        sectors.append({
            "name": name,
            "color": meta["color"],
            "desc": meta["desc"],
            "tickers": tickers,
        })
    return jsonify({"sectors": sectors})


@app.route("/api/graph")
@login_required
def api_graph():
    """Return stock relationship graph for D3 force-directed layout."""
    uid = session["user_id"]
    wl_rows = get_watchlist(uid)
    portfolio_rows = get_portfolio(uid)
    watchlist = [r["symbol"] for r in wl_rows] if wl_rows else WATCHLIST
    portfolio_syms = [r["symbol"] for r in portfolio_rows]
    focus = list(set(watchlist + portfolio_syms))
    # Include AI universe symbols
    for meta in AI_UNIVERSE.values():
        focus.extend(meta["tickers"])
    graph = build_graph(symbols=focus, quotes=_quotes_cache)
    return jsonify(graph)


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
            max_tokens=800,
        )
        import re
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        result = __import__("json").loads(clean)
    except Exception as e:
        result = {
            "interpretation": query,
            "results": [],
            "summary": f"Query processing error: {e}",
        }

    # Augment results with live quote data
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

def job_market_refresh():
    global _quotes_cache, _macro_cache
    try:
        quotes = fetch_quotes()
        _quotes_cache = quotes
        signals_4h = get_signals(hours=4)
        stats = compute_sentiment_stats(signals_4h)
        alerts = get_recent_alerts(limit=5)
        risk = get_risk_level(stats, alerts)
        sector = get_sector_snapshot(quotes)
        trending = get_trending_assets(hours=4, limit=15)

        # Nasdaq macro data (cached 1h)
        try:
            macro = get_macro_snapshot()
            if macro:
                _macro_cache = macro
        except Exception:
            macro = _macro_cache

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
            for alert in alerts:
                socketio.emit("alert", alert)

            all_signals = get_signals(hours=4)
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

            trending = get_trending_assets(hours=4, limit=15)
            timeline = get_sentiment_timeline(hours=24)

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
    if not user_msg:
        return
    history = _chat_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": user_msg})

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

    def job_rnd():
        try:
            from improve import run_improvement_cycle
            run_improvement_cycle()
        except Exception as e:
            print(f"[RnD] Cycle error: {e}")

    def job_prune():
        """Data retention enforcement — GDPR Art.5 / APP 11.2 data minimisation."""
        from config import DATA_RETENTION_DAYS
        result = prune_old_data(DATA_RETENTION_DAYS)
        total = sum(result["deleted"].values())
        if total:
            print(f"[Prune] Removed {total} records older than {DATA_RETENTION_DAYS}d: {result['deleted']}")

    def job_news_refresh():
        """Refresh news from all sources every 30 minutes."""
        try:
            wl_rows = []
            # Pull all unique watchlist symbols across all users
            from memory_store import get_conn as _gc
            with _gc() as c:
                wl_rows = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()]
            symbols = list(set(WATCHLIST + wl_rows))
            count = fetch_all_news(symbols)
            print(f"[News] Refreshed — {count} new items")
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

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(job_market_refresh, "interval", seconds=MARKET_REFRESH_SECONDS, id="market")
    scheduler.add_job(job_scan_cycle, "interval", hours=SCAN_INTERVAL_HOURS, id="scan")
    scheduler.add_job(job_rnd, "interval", hours=6, id="rnd")
    scheduler.add_job(job_prune, "cron", hour=2, minute=0, id="prune")
    scheduler.add_job(job_news_refresh, "interval", minutes=30, id="news")
    scheduler.add_job(job_calendar_refresh, "cron", hour=6, minute=0, id="calendar")
    scheduler.add_job(job_tech_alerts, "interval", minutes=5, id="tech_alerts")
    scheduler.start()

    # Non-blocking startup: fetch market data + scan in background
    def _startup():
        global _quotes_cache
        print("[Init] Fetching initial market data (background)...")
        try:
            _quotes_cache = fetch_quotes()
        except Exception as e:
            print(f"[Init] Market fetch error: {e}")
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
