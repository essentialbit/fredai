"""Scratch verification for disposal event recording (unit 4.3, Unit 1) --
run against a scratch copy of the real sentinel.db (never the live file) to
confirm: record_disposal reduces/removes the consumed lots and re-syncs
portfolio, get_disposals returns the frozen line items with the correct
per-line cost_basis/acquired_date, an oversell raises ValueError rather than
partial-filling, and a disposal_date predating a consumed lot's
acquired_date raises ValueError without writing anything."""
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

SCRATCH_DB = "/tmp/disposal_verify_copy.db"
LIVE_DB = os.path.join(PROJECT_ROOT, "data", "sentinel.db")

if os.path.exists(SCRATCH_DB):
    os.remove(SCRATCH_DB)
shutil.copy(LIVE_DB, SCRATCH_DB)

import memory_store
memory_store.DB_PATH = SCRATCH_DB
memory_store.init_db()

UID = 999
SYMBOL = "DISP"

with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, SYMBOL, 10, 1000.0, "2024-01-01")
    )
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, SYMBOL, 20, 3000.0, "2024-06-01")
    )
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, SYMBOL, 30, 6000.0, "2024-12-01")
    )

lots_before = memory_store.get_lots(UID, SYMBOL)
assert len(lots_before) == 3
lot_a, lot_b, lot_c = lots_before  # acquired_date ASC, id ASC
lot_a_id, lot_b_id, lot_c_id = lot_a["id"], lot_b["id"], lot_c["id"]
print(f"=== Fixture: lot A(id={lot_a_id}, 10sh/$1000, 2024-01-01), "
      f"B(id={lot_b_id}, 20sh/$3000, 2024-06-01), "
      f"C(id={lot_c_id}, 30sh/$6000, 2024-12-01) ===")

# ── Test 1: record_disposal (FIFO, spans lot A fully + lot B partially) ────────
print("=== Test 1: record_disposal consumes lot A fully + 5sh of lot B (FIFO) ===")
disposal_id = memory_store.record_disposal(
    UID, SYMBOL, shares=15, proceeds=2500.0, disposal_date="2025-01-01", method="fifo"
)
assert isinstance(disposal_id, int)
print(f"  record_disposal -> disposal_id={disposal_id}")

# ── Test 1a: get_lots / get_aggregated_position reflect reduced/removed shares ──
print("=== Test 1a: get_lots / get_aggregated_position reflect the disposal ===")
lots_after = memory_store.get_lots(UID, SYMBOL)
ids_after = {l["id"] for l in lots_after}
assert lot_a_id not in ids_after, f"lot A ({lot_a_id}) should be fully consumed and removed, still present: {lots_after}"
assert lot_c_id in ids_after, "lot C should be untouched"

remaining_b = next(l for l in lots_after if l["id"] == lot_b_id)
assert remaining_b["shares"] == 15, f"lot B should have 15 shares remaining (20-5), got {remaining_b['shares']}"
assert abs(remaining_b["cost_basis"] - 2250.0) < 1e-9, (
    f"lot B cost_basis should shrink proportionally to 3000*(15/20)=2250, got {remaining_b['cost_basis']}"
)

remaining_c = next(l for l in lots_after if l["id"] == lot_c_id)
assert remaining_c["shares"] == 30 and remaining_c["cost_basis"] == 6000.0, (
    f"lot C must be untouched by a disposal that never consumed it: {remaining_c}"
)

agg = memory_store.get_aggregated_position(UID, SYMBOL)
expected_shares = 15 + 30  # remaining B + untouched C
expected_cost = 2250.0 + 6000.0
assert agg["shares"] == expected_shares, f"aggregated shares {agg['shares']} != {expected_shares}"
assert abs(agg["avg_cost"] - expected_cost / expected_shares) < 1e-9, (
    f"aggregated avg_cost {agg['avg_cost']} != {expected_cost / expected_shares}"
)

with memory_store.get_conn() as conn:
    prow = conn.execute(
        "SELECT shares, avg_cost FROM portfolio WHERE user_id=? AND symbol=?", (UID, SYMBOL)
    ).fetchone()
assert prow is not None, "record_disposal did not resync the portfolio table"
assert prow["shares"] == expected_shares, f"portfolio.shares {prow['shares']} != {expected_shares} (resync failed)"
print(f"  lot A removed, lot B -> (shares=15, cost_basis=2250.0), lot C untouched, "
      f"get_aggregated_position={agg}, portfolio row synced to {dict(prow)}")

# ── Test 1b: get_disposals returns the frozen line items ───────────────────────
print("=== Test 1b: get_disposals returns disposal + frozen line items ===")
disposals = memory_store.get_disposals(UID, SYMBOL)
assert len(disposals) == 1, f"expected exactly 1 disposal, got {len(disposals)}"
d = disposals[0]
assert d["id"] == disposal_id
assert d["user_id"] == UID
assert d["symbol"] == SYMBOL
assert d["disposal_date"] == "2025-01-01"
assert d["shares"] == 15
assert d["proceeds"] == 2500.0
assert d["method"] == "fifo"
assert len(d["lots"]) == 2, f"expected 2 line items (lot A full + lot B partial), got {d['lots']}"

line_a, line_b = d["lots"]  # insertion order == consumption order for fifo
assert line_a["lot_id"] == lot_a_id
assert line_a["shares_used"] == 10
# Lot A was fully consumed -- its frozen cost_basis equals its full pre-disposal
# total cost_basis (1000.0), same as its acquired_date (frozen, pre-disposal).
assert abs(line_a["cost_basis"] - 1000.0) < 1e-9, f"lot A line cost_basis {line_a['cost_basis']} != 1000.0"
assert line_a["acquired_date"] == "2024-01-01"

assert line_b["lot_id"] == lot_b_id
assert line_b["shares_used"] == 5
# Lot B was only partially consumed (5 of 20 shares) -- its frozen cost_basis is
# the proportional slice of its pre-disposal total cost_basis: 3000*(5/20)=750,
# NOT the lot's full original 3000 (see record_disposal's documented convention).
assert abs(line_b["cost_basis"] - 750.0) < 1e-9, f"lot B line cost_basis {line_b['cost_basis']} != 750.0"
assert line_b["acquired_date"] == "2024-06-01"
print(f"  disposal row: {({k: v for k, v in d.items() if k != 'lots'})}")
print(f"  line items: {d['lots']}")
print("PASS: get_disposals returns frozen cost_basis/acquired_date exactly matching pre-disposal lot state")

# ── Test 2: oversell raises ValueError, does not partial-fill ──────────────────
print("=== Test 2: selling more than remains raises ValueError, writes nothing ===")
lots_before_oversell = memory_store.get_lots(UID, SYMBOL)
disposals_before_oversell = memory_store.get_disposals(UID, SYMBOL)
try:
    memory_store.record_disposal(UID, SYMBOL, shares=10000, proceeds=1.0, disposal_date="2025-02-01", method="fifo")
    raise AssertionError("expected ValueError for an oversell, none raised")
except ValueError as e:
    print(f"  correctly raised: {e}")
lots_after_oversell = memory_store.get_lots(UID, SYMBOL)
disposals_after_oversell = memory_store.get_disposals(UID, SYMBOL)
assert lots_before_oversell == lots_after_oversell, "an oversell attempt must not mutate tax_lots at all"
assert disposals_before_oversell == disposals_after_oversell, "an oversell attempt must not write a disposal row"
print("PASS: oversell raised without partial-filling or mutating any state")

# ── Test 3: disposal_date predating a consumed lot's acquired_date raises ──────
print("=== Test 3: disposal_date predating a consumed lot's acquired_date raises, writes nothing ===")
lots_before_backdate = memory_store.get_lots(UID, SYMBOL)
disposals_before_backdate = memory_store.get_disposals(UID, SYMBOL)
try:
    # lot C was acquired 2024-12-01; a disposal dated before that consuming it
    # (specific method, so we know exactly which lot is touched) must raise.
    memory_store.record_disposal(
        UID, SYMBOL, shares=5, proceeds=100.0, disposal_date="2024-11-01",
        method="specific", lot_ids=[lot_c_id]
    )
    raise AssertionError("expected ValueError for disposal_date predating acquired_date, none raised")
except ValueError as e:
    print(f"  correctly raised: {e}")
lots_after_backdate = memory_store.get_lots(UID, SYMBOL)
disposals_after_backdate = memory_store.get_disposals(UID, SYMBOL)
assert lots_before_backdate == lots_after_backdate, "a backdated disposal attempt must not mutate tax_lots at all"
assert disposals_before_backdate == disposals_after_backdate, "a backdated disposal attempt must not write a disposal row"
print("PASS: backdated disposal_date raised without mutating any state")

print("\nAll disposal recording verification tests passed.")
if os.path.exists(SCRATCH_DB):
    os.remove(SCRATCH_DB)
