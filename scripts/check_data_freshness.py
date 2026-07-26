"""Reports staleness of Fred's live data-ingestion tables against their
scheduled job cadence (main.py's APScheduler `add_job` intervals).

Distinct from check_sensor_health.py, which watches the sensor's own `claude
-p` process health -- this watches whether the *application's* scheduled
jobs are actually landing rows, which only happens while main.py's own
Flask/APScheduler process is running continuously. The sensor cycle itself
never boots main.py (see fredai.md's booting-from-worktree hazard note), so
this is a read-only diagnostic, not a fix.

Usage: PYTHONPATH=. python3 scripts/check_data_freshness.py
"""
import sqlite3
from datetime import datetime, timezone

from memory_store import get_conn

# (table, timestamp_column, human label, job cadence hours, stale-after hours)
# Stale-after is set generously (>=3x cadence) to avoid false positives from
# jitter/weekend cron gaps -- this flags "job hasn't run in a long time",
# not "job is a few minutes late".
CHECKS = [
    ("signals", "timestamp", "Signal ingestion (twitter/reddit/filing/divergence/committee)", 1, 24),
    ("news_items", "fetched_at", "News refresh (30min cadence)", 0.5, 12),
    ("signal_outcomes", "predicted_at", "Backtest outcome logging (30min cadence)", 0.5, 48),
    ("trends", "timestamp", "Trend detection (daily cron)", 24, 72),
    ("rag_chunks", "indexed_at", "Fred Recall embed backlog (hourly)", 1, 48),
]

# Tables that can legitimately sit empty for long stretches (rare-event /
# quarterly-cadence data) -- reported for visibility only, never flagged.
INFORMATIONAL = [
    ("filings", "filed_date", "Filing Intelligence (10-K/10-Q, quarterly-ish)"),
    ("divergence_events", "started_at", "Divergence Radar episodes (rare by design)"),
    ("counterfactual_runs", None, "Counterfactual P&L nightly stats"),
    ("calibration_scores", None, "Calibration Engine daily refresh"),
]


def _age_hours(ts_str):
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            ts = datetime.strptime(ts_str[:19], fmt).replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        except ValueError:
            continue
    return None


def main():
    stale = []

    print("=== Freshness (actionable) ===")
    with get_conn() as conn:
        for table, col, label, cadence_h, stale_after_h in CHECKS:
            try:
                row = conn.execute(f"SELECT COUNT(*), MAX({col}) FROM {table}").fetchone()
                count, latest = row[0], row[1]
            except sqlite3.OperationalError as e:
                print(f"[ERR ] {table}: {e}")
                continue
            age = _age_hours(latest)
            if count == 0:
                status = "EMPTY (never populated)"
            elif age is None:
                status = f"UNKNOWN (unparseable timestamp {latest!r})"
            elif age > stale_after_h:
                status = f"STALE ({age:.0f}h since last row, cadence {cadence_h}h, threshold {stale_after_h}h)"
                stale.append((table, age, stale_after_h))
            else:
                status = f"OK ({age:.1f}h old, cadence {cadence_h}h)"
            print(f"[{'STALE' if status.startswith('STALE') else 'ok   '}] {table:20s} {label:55s} {status}")

        print("\n=== Informational (legitimately sparse, not flagged) ===")
        for table, col, label in INFORMATIONAL:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError as e:
                print(f"[ERR ] {table}: {e}")
                continue
            latest = None
            if col and count:
                try:
                    latest = conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
                except sqlite3.OperationalError:
                    pass
            print(f"[info] {table:20s} {label:55s} rows={count} latest={latest}")

    if stale:
        print(f"\n{len(stale)} table(s) stale -- likely means main.py's live "
              "APScheduler process isn't currently running (scheduled jobs "
              "never fire from one-off script invocations). This script "
              "does not attempt to start it.")
    else:
        print("\nAll checked tables within their staleness threshold.")


if __name__ == "__main__":
    main()
