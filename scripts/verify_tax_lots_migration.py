"""Scratch verification for the tax_lots schema + backfill migration (unit 4.1)
-- run against copies of a fresh DB and the real sentinel.db (never the live
file) to confirm: fresh-DB table creation, backfill correctness against real
pre-4.1 portfolio rows, and idempotency across repeated init_db() calls."""
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

FRESH_SCRATCH_DB = "/tmp/tax_lots_verify_fresh.db"
COPY_SCRATCH_DB = "/tmp/tax_lots_verify_copy.db"
LIVE_DB = os.path.join(PROJECT_ROOT, "data", "sentinel.db")

for p in (FRESH_SCRATCH_DB, COPY_SCRATCH_DB):
    if os.path.exists(p):
        os.remove(p)

import memory_store

print("=== Test 1: fresh-DB creation ===")
memory_store.DB_PATH = FRESH_SCRATCH_DB
memory_store.init_db()
with memory_store.get_conn() as conn:
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(tax_lots)").fetchall()]
    expected_cols = ["id", "user_id", "symbol", "shares", "cost_basis",
                      "acquired_date", "backfilled", "created_at"]
    assert cols == expected_cols, f"unexpected column shape: {cols}"
    idx_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_tax_lots_user_symbol'"
    ).fetchone()
    assert idx_sql is not None, "idx_tax_lots_user_symbol missing"
    count = conn.execute("SELECT COUNT(*) AS c FROM tax_lots").fetchone()["c"]
    assert count == 0, f"fresh DB should have zero tax_lots rows (no portfolio rows to backfill), got {count}"
print("PASS: tax_lots created on fresh DB with correct columns, index, and zero rows")

print("=== Test 2: backfill correctness against a copy of the real DB ===")
shutil.copy(LIVE_DB, COPY_SCRATCH_DB)
memory_store.DB_PATH = COPY_SCRATCH_DB
memory_store.init_db()

with memory_store.get_conn() as conn:
    portfolio_rows = conn.execute("SELECT user_id, symbol, shares, avg_cost FROM portfolio").fetchall()
    portfolio_count = len(portfolio_rows)
    lots_count_after_first = conn.execute("SELECT COUNT(*) AS c FROM tax_lots").fetchone()["c"]
    backfilled_count = conn.execute("SELECT COUNT(*) AS c FROM tax_lots WHERE backfilled=1").fetchone()["c"]

    assert lots_count_after_first == portfolio_count, (
        f"expected {portfolio_count} tax_lots rows (one per portfolio row), got {lots_count_after_first}"
    )
    assert backfilled_count == portfolio_count, (
        f"expected all {portfolio_count} tax_lots rows to be backfilled=1, got {backfilled_count}"
    )

    import datetime as _dt
    today = _dt.datetime.now().strftime("%Y-%m-%d")

    for p in portfolio_rows:
        lot = conn.execute(
            "SELECT * FROM tax_lots WHERE user_id=? AND symbol=?",
            (p["user_id"], p["symbol"])
        ).fetchone()
        assert lot is not None, f"missing tax_lots row for {p['user_id']}/{p['symbol']}"
        assert lot["shares"] == p["shares"], (
            f"{p['symbol']}: shares mismatch {lot['shares']} != {p['shares']}"
        )
        expected_cost_basis = p["shares"] * p["avg_cost"]
        assert abs(lot["cost_basis"] - expected_cost_basis) < 1e-9, (
            f"{p['symbol']}: cost_basis mismatch {lot['cost_basis']} != {expected_cost_basis}"
        )
        assert lot["acquired_date"] == today, (
            f"{p['symbol']}: acquired_date {lot['acquired_date']} != today {today}"
        )
        assert lot["backfilled"] == 1

print(f"PASS: {portfolio_count} portfolio rows each have exactly one correct backfilled=1 tax_lots row")

print("=== Test 3: idempotency across a second init_db() call ===")
with memory_store.get_conn() as conn:
    portfolio_count_before = conn.execute("SELECT COUNT(*) AS c FROM portfolio").fetchone()["c"]

memory_store.init_db()

with memory_store.get_conn() as conn:
    lots_count_after_second = conn.execute("SELECT COUNT(*) AS c FROM tax_lots").fetchone()["c"]
    portfolio_count_after = conn.execute("SELECT COUNT(*) AS c FROM portfolio").fetchone()["c"]

assert lots_count_after_second == lots_count_after_first, (
    f"second init_db() changed tax_lots row count: {lots_count_after_first} -> {lots_count_after_second}"
)
assert portfolio_count_after == portfolio_count_before, (
    f"second init_db() mutated portfolio row count: {portfolio_count_before} -> {portfolio_count_after}"
)
print(f"PASS: tax_lots row count stable at {lots_count_after_second}, portfolio row count stable at {portfolio_count_after}")

print("\nAll tax_lots migration tests passed.")
for p in (FRESH_SCRATCH_DB, COPY_SCRATCH_DB):
    if os.path.exists(p):
        os.remove(p)
