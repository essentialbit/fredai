"""Scratch verification for the lot-aware backend CRUD + aggregation (unit 4.2)
-- run against copies of a fresh DB and the real sentinel.db (never the live
file) to confirm: aggregation matches today's single-lot backfilled portfolio
rows exactly, multi-lot weighted-average math, FIFO/specific lot selection for
a hypothetical sale, shortfall raises ValueError, and full CRUD round-trip
(including the portfolio-sync side effect of add_lot/update_lot/remove_lot)."""
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

COPY_SCRATCH_DB = "/tmp/lot_aggregation_verify_copy.db"
FRESH_SCRATCH_DB = "/tmp/lot_aggregation_verify_fresh.db"
LIVE_DB = os.path.join(PROJECT_ROOT, "data", "sentinel.db")

for p in (COPY_SCRATCH_DB, FRESH_SCRATCH_DB):
    if os.path.exists(p):
        os.remove(p)

import memory_store

# ── Test 1: single-lot-matches-portfolio-row regression check ─────────────────
print("=== Test 1: get_aggregated_position matches every real (backfilled) portfolio row ===")
shutil.copy(LIVE_DB, COPY_SCRATCH_DB)
memory_store.DB_PATH = COPY_SCRATCH_DB
memory_store.init_db()

with memory_store.get_conn() as conn:
    portfolio_rows = conn.execute("SELECT user_id, symbol, shares, avg_cost FROM portfolio").fetchall()
    portfolio_rows = [dict(r) for r in portfolio_rows]

assert portfolio_rows, "expected at least one portfolio row in the real DB to check against"
for p in portfolio_rows:
    agg = memory_store.get_aggregated_position(p["user_id"], p["symbol"])
    assert abs(agg["shares"] - p["shares"]) < 1e-9, (
        f"{p['symbol']}: shares mismatch {agg['shares']} != {p['shares']}"
    )
    assert abs(agg["avg_cost"] - p["avg_cost"]) < 1e-9, (
        f"{p['symbol']}: avg_cost mismatch {agg['avg_cost']} != {p['avg_cost']}"
    )
print(f"PASS: {len(portfolio_rows)} portfolio rows all match their aggregated single-lot position")

# ── Fresh DB for the rest of the tests ─────────────────────────────────────────
memory_store.DB_PATH = FRESH_SCRATCH_DB
memory_store.init_db()
UID = 999

# ── Test 2: multi-lot weighted-average case ────────────────────────────────────
print("=== Test 2: multi-lot weighted-average aggregation ===")
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "MSWA", 10, 1000.0, "2025-01-01")
    )
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "MSWA", 5, 750.0, "2025-02-01")
    )
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "MSWA", 3, 600.0, "2025-03-01")
    )

# Independently hand-computed, not re-derived from the formula under test.
expected_shares = 10 + 5 + 3
expected_avg_cost = (1000.0 + 750.0 + 600.0) / (10 + 5 + 3)

agg = memory_store.get_aggregated_position(UID, "MSWA")
assert agg["shares"] == expected_shares, f"shares {agg['shares']} != {expected_shares}"
assert abs(agg["avg_cost"] - expected_avg_cost) < 1e-9, f"avg_cost {agg['avg_cost']} != {expected_avg_cost}"
print(f"PASS: weighted avg_cost={agg['avg_cost']:.4f} matches hand-computed {expected_avg_cost:.4f}")

# ── Fixture for FIFO / specific / shortfall tests ──────────────────────────────
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "FIFO", 10, 1000.0, "2024-01-01")
    )
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "FIFO", 20, 3000.0, "2024-06-01")
    )
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "FIFO", 30, 6000.0, "2024-12-01")
    )

fifo_lots = memory_store.get_lots(UID, "FIFO")
assert len(fifo_lots) == 3
oldest, second, third = fifo_lots  # ordered acquired_date ASC, id ASC
oldest_id, second_id, third_id = oldest["id"], second["id"], third["id"]

# ── Test 3: FIFO selection ─────────────────────────────────────────────────────
print("=== Test 3: FIFO lot selection (oldest fully + second partially) ===")
result = memory_store.select_lots_for_sale(UID, "FIFO", 15, method="fifo")
assert result == [
    {"lot_id": oldest_id, "shares_used": 10},
    {"lot_id": second_id, "shares_used": 5},
], f"unexpected FIFO selection: {result}"
print(f"PASS: FIFO selection = {result}, third lot ({third_id}) untouched")

# ── Test 4: specific-lot selection ─────────────────────────────────────────────
print("=== Test 4: specific-lot selection (newest, middle; oldest excluded) ===")
result = memory_store.select_lots_for_sale(
    UID, "FIFO", 25, method="specific", lot_ids=[third_id, second_id]
)
assert result == [
    {"lot_id": third_id, "shares_used": 25},
], f"unexpected specific selection: {result}"
# Also confirm a sale spanning both named lots, in the order given.
result2 = memory_store.select_lots_for_sale(
    UID, "FIFO", 45, method="specific", lot_ids=[third_id, second_id]
)
assert result2 == [
    {"lot_id": third_id, "shares_used": 30},
    {"lot_id": second_id, "shares_used": 15},
], f"unexpected specific selection: {result2}"
present_ids = {r["lot_id"] for r in result2}
assert oldest_id not in present_ids, "oldest lot must be excluded from a specific-lot selection that didn't name it"
print(f"PASS: specific selection (25 shares) = {result}; (45 shares) = {result2}, oldest lot correctly excluded")

# ── Test 5: shortfall raises ValueError ─────────────────────────────────────────
print("=== Test 5: shortfall raises ValueError (FIFO and specific) ===")
try:
    memory_store.select_lots_for_sale(UID, "FIFO", 1000, method="fifo")
    raise AssertionError("expected ValueError for FIFO shortfall, none raised")
except ValueError as e:
    print(f"  FIFO shortfall correctly raised: {e}")

try:
    memory_store.select_lots_for_sale(UID, "FIFO", 1000, method="specific", lot_ids=[oldest_id])
    raise AssertionError("expected ValueError for specific shortfall, none raised")
except ValueError as e:
    print(f"  specific shortfall correctly raised: {e}")
print("PASS: both selection paths raise ValueError on shortfall rather than partial-filling")

# ── Test 5b: duplicate lot_ids in a specific-lot sale must not double-count shares ──
print("=== Test 5b: duplicate lot_ids don't double-count shares (specific method) ===")
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "DUP", 10, 500.0, "2025-01-01")
    )
dup_lots = memory_store.get_lots(UID, "DUP")
assert len(dup_lots) == 1
dup_lot_id = dup_lots[0]["id"]
try:
    result = memory_store.select_lots_for_sale(
        UID, "DUP", 15, method="specific", lot_ids=[dup_lot_id, dup_lot_id]
    )
    raise AssertionError(
        f"expected ValueError for a duplicate-lot_ids oversell (10 shares available, 15 requested), "
        f"got a result instead: {result}"
    )
except ValueError as e:
    print(f"  duplicate lot_ids correctly raised (no double-counted shares): {e}")
# A duplicate id that's fully covered by the lot's real balance should still
# work and consume the lot only once, not twice.
result = memory_store.select_lots_for_sale(
    UID, "DUP", 10, method="specific", lot_ids=[dup_lot_id, dup_lot_id]
)
assert result == [{"lot_id": dup_lot_id, "shares_used": 10}], (
    f"duplicate lot_ids at exactly the real balance should consume the lot once: {result}"
)
print(f"  duplicate lot_ids within the real balance -> consumed once: {result}")
print("PASS: duplicate lot_ids never double-count a lot's shares")

# ── Test 6: CRUD round-trip + portfolio sync ────────────────────────────────────
print("=== Test 6: add_lot / update_lot / remove_lot round-trip + portfolio sync ===")

new_id = memory_store.add_lot(UID, "crud", 100, 5000.0, "2025-05-01")
lots = memory_store.get_lots(UID, "CRUD")
assert any(l["id"] == new_id for l in lots), "add_lot's new row not visible via get_lots"
added = next(l for l in lots if l["id"] == new_id)
assert added["symbol"] == "CRUD", f"add_lot did not upper-case symbol: {added['symbol']}"

agg = memory_store.get_aggregated_position(UID, "CRUD")
assert agg == {"shares": 100, "avg_cost": 50.0}, f"unexpected aggregation after add_lot: {agg}"
with memory_store.get_conn() as conn:
    prow = conn.execute("SELECT shares, avg_cost FROM portfolio WHERE user_id=? AND symbol=?", (UID, "CRUD")).fetchone()
assert prow is not None, "add_lot did not create/sync a portfolio row"
assert prow["shares"] == 100 and prow["avg_cost"] == 50.0, f"portfolio row not synced by add_lot: {dict(prow)}"
print(f"  add_lot -> id={new_id}, get_lots shows it, portfolio row synced to {dict(prow)}")

ok = memory_store.update_lot(new_id, shares=150)
assert ok is True
lots = memory_store.get_lots(UID, "CRUD")
updated = next(l for l in lots if l["id"] == new_id)
assert updated["shares"] == 150, f"update_lot on whitelisted field not reflected: {updated}"
with memory_store.get_conn() as conn:
    prow = conn.execute("SELECT shares, avg_cost FROM portfolio WHERE user_id=? AND symbol=?", (UID, "CRUD")).fetchone()
assert prow["shares"] == 150, f"portfolio row not re-synced after update_lot: {dict(prow)}"
print(f"  update_lot(shares=150) -> reflected in get_lots and re-synced portfolio row {dict(prow)}")

with memory_store.get_conn() as conn:
    before = dict(conn.execute("SELECT * FROM tax_lots WHERE id=?", (new_id,)).fetchone())
ok = memory_store.update_lot(new_id, user_id=1, symbol="HACK", not_a_real_column="x")
assert ok is True, "update_lot with only disallowed keys should still succeed (lot exists) but change nothing"
with memory_store.get_conn() as conn:
    after = dict(conn.execute("SELECT * FROM tax_lots WHERE id=?", (new_id,)).fetchone())
assert before == after, f"update_lot mutated a non-whitelisted column: before={before} after={after}"
print("  update_lot with a disallowed key: no SQL error, no column changed")

ok = memory_store.update_lot(999999999, shares=1)
assert ok is False, "update_lot on a nonexistent lot_id must return False, not silently succeed"
print("  update_lot on unknown lot_id correctly returns False")

second_id_crud = memory_store.add_lot(UID, "CRUD", 50, 3000.0, "2025-06-01")
ok = memory_store.remove_lot(new_id)
assert ok is True
lots = memory_store.get_lots(UID, "CRUD")
assert all(l["id"] != new_id for l in lots), "remove_lot did not remove the row"
assert any(l["id"] == second_id_crud for l in lots), "remove_lot removed the wrong row"
print(f"  remove_lot(first CRUD lot) -> get_lots no longer shows it, second lot ({second_id_crud}) remains")

ok = memory_store.remove_lot(second_id_crud)
assert ok is True
lots = memory_store.get_lots(UID, "CRUD")
assert lots == [], f"expected zero CRUD lots remaining, got {lots}"
agg = memory_store.get_aggregated_position(UID, "CRUD")
assert agg == {"shares": 0, "avg_cost": 0}, f"unexpected aggregation after removing last lot: {agg}"
with memory_store.get_conn() as conn:
    prow = conn.execute("SELECT shares, avg_cost FROM portfolio WHERE user_id=? AND symbol=?", (UID, "CRUD")).fetchone()
assert prow["shares"] == 0 and prow["avg_cost"] == 0, f"portfolio row not zeroed after last lot removed: {dict(prow)}"

ok = memory_store.remove_lot(999999999)
assert ok is False, "remove_lot on a nonexistent lot_id must return False"
print(f"  remove_lot(last CRUD lot) -> get_lots empty, portfolio row zeroed to {dict(prow)}; remove_lot on unknown id returns False")

print("\nAll lot aggregation / CRUD verification tests passed.")
for p in (COPY_SCRATCH_DB, FRESH_SCRATCH_DB):
    if os.path.exists(p):
        os.remove(p)
