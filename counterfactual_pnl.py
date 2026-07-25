"""Counterfactual P&L (FSI L3) -- honest simulated equity curve of "what if
you had traded on Fred's signals", drawdowns and costs included.

Intellectual honesty is the spec, not a nice-to-have:
- Entry uses the close on the first trading day STRICTLY AFTER the signal's
  predicted_at date -- never the same-bar price signal_outcomes.price_at_t0
  records (that price is captured concurrently with the prediction itself,
  see backtesting_engine.log_scan_outcomes, so using it here would be
  lookahead bias).
- Every entry and exit pays COST_BPS.
- max_drawdown is always reported alongside total_return, never omitted.
- This is a hypothetical simulation, not advice -- callers must append
  agent.DISCLAIMER_FOOTER wherever these numbers are surfaced to a user.

Reuses portfolio_risk.py's daily-close fetch/cache (market_data.fetch_history
-> Nasdaq fallback) and Sharpe/drawdown math -- zero new data dependencies,
same reasoning as every other FSI module in this codebase.
"""
from datetime import datetime, timedelta

from memory_store import (
    get_signal_outcomes_for_simulation, insert_counterfactual_run,
    get_latest_counterfactual_results,
)
from portfolio_risk import _daily_closes, _mean, _stdev, _max_drawdown, TRADING_DAYS

METHODOLOGY_VERSION = 1

START_CAPITAL = 100.0
MAX_CONCURRENT_POSITIONS = 10
SLOT_SIZE = START_CAPITAL / MAX_CONCURRENT_POSITIONS
COST_BPS = 10  # 10bps per side (entry AND exit), applied to the traded price
COST_FRAC = COST_BPS / 10_000.0

# Signals with a reported avg_sentiment must clear this magnitude to be
# "actionable above a confidence threshold" -- deliberately stricter than
# backtesting_engine._direction's own +/-0.05 bullish/bearish cutoff, since
# that cutoff exists to bucket a direction label, not to gate real capital.
# Sources that log no magnitude at all (insider/short_interest/technical --
# see backtesting_engine.py) are binary calls with no confidence dial;
# they're already only logged when a real signal fired, so they always pass.
CONFIDENCE_THRESHOLD = 0.15

# Long-only + cash by default (playbook's documented default). Flip to True
# to open an inverse (short) position on bearish signals instead of skipping
# them -- kept as a constant, not a runtime toggle, so a run's methodology
# is fully determined by METHODOLOGY_VERSION alone.
ALLOW_SHORTS = False

# "Exit = signal horizon or opposing signal" (playbook, section 8) doesn't
# pin an exact horizon length. Chosen to mirror backtesting_engine's own
# longest checkpoint (72h) scaled from intraday to daily-bar granularity --
# a comparable "did this call play out" window for a market that only gives
# us one close per day.
EXIT_HORIZON_DAYS = 5

BENCHMARK = "SPY"
WINDOWS = {"30d": 30, "90d": 90, "365d": 365, "all": None}

# Surfaced verbatim by get_counterfactual_report() -- always shown alongside
# the numbers, never hidden behind a tooltip (playbook's explicit ask).
METHODOLOGY_DISCLOSURE = (
    f"Hypothetical simulation, not investment advice. Each signal source "
    f"trades independently starting from {START_CAPITAL:.0f} notional units. "
    f"Entries use the close on the first trading day after the signal "
    f"(never same-bar). {COST_BPS}bps cost charged on both entry and exit. "
    f"Long-only by default (bearish signals hold cash unless shorting is "
    f"explicitly enabled); positions exit after {EXIT_HORIZON_DAYS} trading "
    f"days or on an opposing signal for the same asset, whichever comes "
    f"first. Max {MAX_CONCURRENT_POSITIONS} concurrent positions per source; "
    f"signals beyond that cap are skipped, not queued. Signals with a "
    f"reported confidence below {CONFIDENCE_THRESHOLD} are excluded. "
    f"Benchmarked against {BENCHMARK} buy-and-hold over the same dates."
)


def _next_trading_date(closes: dict, after_date: str) -> str | None:
    """First key in `closes` strictly greater than after_date, or None."""
    later = sorted(d for d in closes if d > after_date)
    return later[0] if later else None


def _n_trading_dates_after(closes: dict, start_date: str, n: int) -> str:
    """The n-th trading date at or after start_date; if the calendar runs out,
    returns the last available date (simulation exits at the data horizon
    rather than fabricating a future price)."""
    later = sorted(d for d in closes if d >= start_date)
    if not later:
        return start_date
    idx = min(n, len(later) - 1)
    return later[idx]


def _is_actionable(row: dict) -> bool:
    if row["predicted_direction"] not in ("bullish", "bearish"):
        return False
    sentiment = row.get("avg_sentiment")
    if sentiment is None:
        return True
    return abs(sentiment) >= CONFIDENCE_THRESHOLD


def simulate_source(source: str, rows: list[dict]) -> dict:
    """Runs one independent START_CAPITAL-unit simulation for a single
    signal source. `rows` must be signal_outcomes rows for that source,
    each with asset/predicted_direction/avg_sentiment/predicted_at, ordered
    by predicted_at ascending.

    Returns {"equity_curve": [{"date", "equity"}], "trades": [...],
    "skipped_overflow": int, "methodology_version": int}. Equity is marked
    to market daily against the traded asset's close -- cash plus every
    still-open position's current value.
    """
    signals = [r for r in rows if _is_actionable(r)]

    closes_cache: dict[str, dict] = {}

    def closes_for(asset: str) -> dict:
        if asset not in closes_cache:
            closes_cache[asset] = _daily_closes(asset)
        return closes_cache[asset]

    # Pre-resolve every actionable signal's entry date (None if the asset has
    # no tradeable close after the signal). ALL directions are kept here
    # (even bearish ones when ALLOW_SHORTS is off) because a bearish call
    # must still be able to trigger an early exit on an existing long --
    # "opposing signal" exit logic is independent of whether the opposing
    # signal itself is tradeable. `scheduled` (below) is the narrower set
    # that actually opens a NEW position.
    all_actionable: list[dict] = []
    for row in signals:
        asset_closes = closes_for(row["asset"])
        signal_date = row["predicted_at"][:10]
        entry_date = _next_trading_date(asset_closes, signal_date)
        if entry_date is None:
            continue
        all_actionable.append({
            "asset": row["asset"],
            "direction": row["predicted_direction"],
            "source": source,
            "signal_date": signal_date,
            "entry_date": entry_date,
            "entry_price_raw": asset_closes[entry_date],
        })
    all_actionable.sort(key=lambda s: s["entry_date"])

    scheduled = [
        s for s in all_actionable
        if s["direction"] == "bullish" or ALLOW_SHORTS
    ]
    skipped_overflow = 0

    if not scheduled:
        return {
            "equity_curve": [], "trades": [], "skipped_overflow": 0,
            "methodology_version": METHODOLOGY_VERSION,
        }

    all_dates = sorted({d["entry_date"] for d in scheduled} | {
        d for s in scheduled for d in closes_for(s["asset"])
        if d >= s["entry_date"]
    })

    cash = START_CAPITAL
    open_positions: list[dict] = []  # {asset, direction, shares, entry_price, exit_by}
    trades: list[dict] = []
    equity_curve: list[dict] = []
    pending = list(scheduled)

    for today in all_dates:
        # 1) Exits: horizon reached, OR a fresher opposing signal on the
        # same asset+source has since been scheduled (exits early into that
        # reversal rather than holding a thesis Fred himself has reversed).
        still_open = []
        for pos in open_positions:
            reversed_signal = any(
                s["asset"] == pos["asset"] and s["direction"] != pos["direction"]
                and s["entry_date"] > pos["entry_date"] and s["entry_date"] <= today
                for s in all_actionable
            )
            if today >= pos["exit_by"] or reversed_signal:
                asset_closes = closes_for(pos["asset"])
                exit_price_raw = asset_closes.get(today)
                if exit_price_raw is None:
                    still_open.append(pos)
                    continue
                if pos["direction"] == "bullish":
                    proceeds = pos["shares"] * exit_price_raw * (1 - COST_FRAC)
                    pnl = proceeds - pos["cost_basis"]
                else:
                    # Short: profit when price fell. shares here is the
                    # notional/entry_price sized at open; P&L is the mirror
                    # of a long over the same price move.
                    move = (pos["entry_price"] - exit_price_raw) / pos["entry_price"]
                    proceeds = pos["cost_basis"] * (1 + move) * (1 - COST_FRAC)
                    pnl = proceeds - pos["cost_basis"]
                cash += proceeds
                trades.append({
                    "asset": pos["asset"], "direction": pos["direction"],
                    "entry_date": pos["entry_date"], "exit_date": today,
                    "pnl": round(pnl, 4),
                })
            else:
                still_open.append(pos)
        open_positions = still_open

        # 2) Entries scheduled for today.
        still_pending = []
        for s in pending:
            if s["entry_date"] != today:
                still_pending.append(s)
                continue
            if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
                skipped_overflow += 1
                continue
            entry_price = s["entry_price_raw"] * (1 + COST_FRAC)
            shares = SLOT_SIZE / entry_price
            asset_closes = closes_for(s["asset"])
            exit_by = _n_trading_dates_after(asset_closes, s["entry_date"], EXIT_HORIZON_DAYS)
            cash -= SLOT_SIZE
            open_positions.append({
                "asset": s["asset"], "direction": s["direction"],
                "entry_price": entry_price, "shares": shares,
                "cost_basis": SLOT_SIZE, "entry_date": s["entry_date"],
                "exit_by": exit_by,
            })
        pending = still_pending

        # 3) Mark to market.
        mtm = cash
        for pos in open_positions:
            price_today = closes_for(pos["asset"]).get(today, pos["entry_price"])
            if pos["direction"] == "bullish":
                mtm += pos["shares"] * price_today
            else:
                move = (pos["entry_price"] - price_today) / pos["entry_price"]
                mtm += pos["cost_basis"] * (1 + move)
        equity_curve.append({"date": today, "equity": round(mtm, 4)})

    return {
        "equity_curve": equity_curve,
        "trades": trades,
        "skipped_overflow": skipped_overflow,
        "methodology_version": METHODOLOGY_VERSION,
    }


def _window_slice(equity_curve: list[dict], days: int | None) -> list[dict]:
    if days is None or not equity_curve:
        return equity_curve
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    sliced = [p for p in equity_curve if p["date"] >= cutoff]
    return sliced or equity_curve[-1:]


def _stats_for_window(equity_curve: list[dict], trades: list[dict], days: int | None) -> dict | None:
    curve = _window_slice(equity_curve, days)
    if len(curve) < 2:
        return None
    values = [p["equity"] for p in curve]
    returns = [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1] > 0]
    if not returns:
        return None
    total_return_pct = round((values[-1] / values[0] - 1.0) * 100, 2)
    max_dd_pct = round(_max_drawdown(returns) * 100, 2)
    ann_return = _mean(returns) * TRADING_DAYS
    ann_vol = _stdev(returns) * (TRADING_DAYS ** 0.5)
    sharpe = round(ann_return / ann_vol, 2) if ann_vol > 0 else None

    window_start, window_end = curve[0]["date"], curve[-1]["date"]
    window_trades = [t for t in trades if window_start <= t["exit_date"] <= window_end]
    wins = [t for t in window_trades if t["pnl"] > 0]
    losses = [t for t in window_trades if t["pnl"] < 0]
    win_rate_pct = round(100 * len(wins) / len(window_trades), 1) if window_trades else None

    return {
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_dd_pct,
        "sharpe": sharpe,
        "win_rate_pct": win_rate_pct,
        "avg_win": round(_mean([t["pnl"] for t in wins]), 3) if wins else None,
        "avg_loss": round(_mean([t["pnl"] for t in losses]), 3) if losses else None,
        "trade_count": len(window_trades),
        "start_date": window_start,
        "end_date": window_end,
        "start_equity": values[0],
        "end_equity": values[-1],
    }


def _benchmark_return_pct(days: int | None, start_date: str, end_date: str) -> float | None:
    closes = _daily_closes(BENCHMARK)
    if not closes:
        return None
    dates = sorted(d for d in closes if start_date <= d <= end_date)
    if len(dates) < 2:
        return None
    return round((closes[dates[-1]] / closes[dates[0]] - 1.0) * 100, 2)


def _benchmark_curve(equity_curve: list[dict]) -> list[dict]:
    """SPY buy-and-hold, rebased to the same start_capital and dates as
    `equity_curve`, for the dashboard's overlay chart."""
    if not equity_curve:
        return []
    closes = _daily_closes(BENCHMARK)
    dates = [p["date"] for p in equity_curve if p["date"] in closes]
    if not dates:
        return []
    base = closes[dates[0]]
    return [{"date": d, "equity": round(START_CAPITAL * closes[d] / base, 4)} for d in dates]


def run_simulation() -> dict:
    """Simulates every source independently (each with its own fresh
    START_CAPITAL pool) and computes per-window headline stats + a
    benchmark overlay for each. This is the expensive call -- meant to be
    invoked once per nightly job run, not per page load."""
    by_source = get_signal_outcomes_for_simulation()
    result = {"methodology_version": METHODOLOGY_VERSION, "sources": {}}
    for source, rows in by_source.items():
        sim = simulate_source(source, rows)
        windows_out = {}
        for label, days in WINDOWS.items():
            stats = _stats_for_window(sim["equity_curve"], sim["trades"], days)
            if stats:
                stats["benchmark_return_pct"] = _benchmark_return_pct(
                    days, stats["start_date"], stats["end_date"]
                )
            windows_out[label] = stats
        result["sources"][source] = {
            "windows": windows_out,
            "equity_curve": sim["equity_curve"],
            "skipped_overflow": sim["skipped_overflow"],
        }
    return result


def job_counterfactual_refresh():
    """Scheduled nightly: runs the full simulation and persists headline
    metrics per source/window as a new row, never overwriting prior runs
    (methodology_version travels with every row so a future rule change is
    visible in the history, not silently rewritten)."""
    try:
        result = run_simulation()
        for source, data in result["sources"].items():
            for window, stats in data["windows"].items():
                if stats is None:
                    continue
                insert_counterfactual_run(
                    source=source, window=window,
                    methodology_version=result["methodology_version"],
                    total_return_pct=stats["total_return_pct"],
                    max_drawdown_pct=stats["max_drawdown_pct"],
                    sharpe=stats["sharpe"],
                    win_rate_pct=stats["win_rate_pct"],
                    benchmark_return_pct=stats["benchmark_return_pct"],
                    trade_count=stats["trade_count"],
                )
    except Exception as e:
        print(f"[Job] counterfactual_pnl error: {e}")


def get_counterfactual_report() -> dict:
    """Dashboard/API-facing read: latest persisted per-source/per-window
    headline stats (cheap -- no live daily-close fetching) for the
    attribution table, plus a live-recomputed equity curve + SPY overlay
    for the 'aggregate' source only -- same reasoning as
    calibration_engine.get_calibration_report's curve-on-read (cheap
    thanks to portfolio_risk._daily_closes' 12h cache, and avoids a second
    stale-cache surface). Empty sources dict until
    job_counterfactual_refresh() has run at least once; the live curve
    still renders even then."""
    results = get_latest_counterfactual_results()

    by_source = get_signal_outcomes_for_simulation()
    agg_rows = by_source.get("aggregate", [])
    agg_sim = simulate_source("aggregate", agg_rows) if agg_rows else {"equity_curve": [], "skipped_overflow": 0}

    return {
        "methodology_version": METHODOLOGY_VERSION,
        "methodology": METHODOLOGY_DISCLOSURE,
        "benchmark": BENCHMARK,
        "sources": results,
        "aggregate_equity_curve": agg_sim["equity_curve"],
        "aggregate_benchmark_curve": _benchmark_curve(agg_sim["equity_curve"]),
    }
