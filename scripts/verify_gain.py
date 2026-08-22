"""Scratch verification for realized/unrealized gain computation (unit 4.3,
Unit 2) -- portfolio_risk.compute_unrealized_gain / compute_realized_gain /
_is_long_term. Runs against a scratch copy of the real sentinel.db (never
the live file) purely to exercise memory_store.record_disposal/get_disposals
for a faithful multi-lot fixture; the gain functions themselves are pure and
take dicts, so most of this doesn't need a DB at all.

Confirms: the shared 365/366-day boundary rule, a multi-lot disposal's
proceeds allocation + total realized gain reconciling exactly to
proceeds - sum(cost_basis_used), and honest zero/empty results on empty
input -- no exceptions."""
import os
import shutil
import sys
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

SCRATCH_DB = "/tmp/gain_verify_copy.db"
LIVE_DB = os.path.join(PROJECT_ROOT, "data", "sentinel.db")

if os.path.exists(SCRATCH_DB):
    os.remove(SCRATCH_DB)
shutil.copy(LIVE_DB, SCRATCH_DB)

import memory_store
memory_store.DB_PATH = SCRATCH_DB
memory_store.init_db()

import portfolio_risk as pr

UID = 998
SYMBOL = "GAIN"


def d(base: str, days: int) -> str:
    return (datetime.strptime(base, "%Y-%m-%d").date() + timedelta(days=days)).strftime("%Y-%m-%d")


# ── Test 1: _is_long_term boundary (365 days == short-term, 366 == long-term) ──
print("=== Test 1: _is_long_term 365/366-day boundary ===")
acquired = "2023-01-10"
as_of_365 = d(acquired, 365)
as_of_366 = d(acquired, 366)
assert pr._is_long_term(acquired, as_of_365) is False, "365 days must be short-term"
assert pr._is_long_term(acquired, as_of_366) is True, "366 days must be long-term"
print(f"  acquired={acquired} as_of={as_of_365} (365d) -> short_term OK")
print(f"  acquired={acquired} as_of={as_of_366} (366d) -> long_term OK")

# ── Test 2: compute_unrealized_gain uses the same boundary rule ────────────────
print("=== Test 2: compute_unrealized_gain 365/366-day boundary ===")
lots = [
    {"id": 1, "symbol": SYMBOL, "shares": 10.0, "cost_basis": 1000.0, "acquired_date": acquired},
    {"id": 2, "symbol": SYMBOL, "shares": 5.0, "cost_basis": 400.0, "acquired_date": acquired},
]
res_365 = pr.compute_unrealized_gain(lots, {SYMBOL: 150.0}, as_of_date=as_of_365)
res_366 = pr.compute_unrealized_gain(lots, {SYMBOL: 150.0}, as_of_date=as_of_366)
assert res_365["lots"][0]["term"] == "short_term"
assert res_366["lots"][0]["term"] == "long_term"
assert res_365["long_term_gain"] == 0.0 and res_365["short_term_gain"] != 0.0
assert res_366["short_term_gain"] == 0.0 and res_366["long_term_gain"] != 0.0
expected_gain = 10.0 * 150.0 - 1000.0 + (5.0 * 150.0 - 400.0)
assert res_365["short_term_gain"] == round(expected_gain, 2)
print(f"  as_of={as_of_365}: term=short_term, short_term_gain={res_365['short_term_gain']} OK")
print(f"  as_of={as_of_366}: term=long_term, long_term_gain={res_366['long_term_gain']} OK")

# ── Test 3: multi-lot disposal -- proceeds allocation + total reconciliation ───
print("=== Test 3: multi-lot disposal realized-gain reconciliation ===")
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, SYMBOL, 10, 1000.0, "2023-01-01")   # long-term relative to disposal below
    )
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, SYMBOL, 20, 2400.0, "2024-06-01")   # short-term relative to disposal below
    )

disposal_id = memory_store.record_disposal(
    UID, SYMBOL, shares=25, proceeds=5000.0, disposal_date="2025-01-01", method="fifo"
)
disposals = memory_store.get_disposals(UID, SYMBOL)
assert len(disposals) == 1
disposal = disposals[0]
assert disposal["id"] == disposal_id
assert len(disposal["lots"]) == 2, "FIFO disposal of 25 must span both lots (10 + 15)"

gain_result = pr.compute_realized_gain(disposals)
lines = gain_result["lines"]
assert len(lines) == 2

total_cost_basis = sum(line["cost_basis"] for line in disposal["lots"])
total_proceeds_allocated = sum(l["proceeds"] for l in lines)
total_gain_from_lines = sum(l["gain"] for l in lines)
expected_total_gain = disposal["proceeds"] - total_cost_basis

assert abs(total_proceeds_allocated - disposal["proceeds"]) < 1e-6, \
    f"allocated proceeds {total_proceeds_allocated} != disposal proceeds {disposal['proceeds']}"
assert abs(total_gain_from_lines - expected_total_gain) < 1e-6, \
    f"summed line gains {total_gain_from_lines} != proceeds-cost_basis {expected_total_gain}"
assert abs(gain_result["total_gain"] - round(expected_total_gain, 2)) < 1e-6

# lot 1 (10sh @ $1000, acquired 2023-01-01) is long-term vs 2025-01-01 disposal
# lot 2 (15sh used of 20sh @ $2400, acquired 2024-06-01) is short-term vs 2025-01-01
lt_line = next(l for l in lines if l["acquired_date"] == "2023-01-01")
st_line = next(l for l in lines if l["acquired_date"] == "2024-06-01")
assert lt_line["term"] == "long_term"
assert st_line["term"] == "short_term"
assert lt_line["shares_used"] == 10.0
assert st_line["shares_used"] == 15.0
assert gain_result["long_term_gain"] == lt_line["gain"], "sole LT line must equal the LT aggregate"
assert gain_result["short_term_gain"] == st_line["gain"], "sole ST line must equal the ST aggregate"
print(f"  disposal proceeds=${disposal['proceeds']} cost_basis=${total_cost_basis} "
      f"-> total_gain=${gain_result['total_gain']} (expected {round(expected_total_gain, 2)}) OK")
print(f"  lt_line term={lt_line['term']} shares_used={lt_line['shares_used']} gain={lt_line['gain']}")
print(f"  st_line term={st_line['term']} shares_used={st_line['shares_used']} gain={st_line['gain']}")
assert abs((gain_result["long_term_gain"] + gain_result["short_term_gain"]) - gain_result["total_gain"]) < 1e-6

# ── Test 4: realized-gain 365/366-day boundary via a real disposal ─────────────
print("=== Test 4: compute_realized_gain 365/366-day boundary ===")
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "BND1", 1, 100.0, "2022-01-01")
    )
disp_365 = memory_store.record_disposal(UID, "BND1", shares=1, proceeds=150.0, disposal_date=d("2022-01-01", 365), method="fifo")
disposals_365 = memory_store.get_disposals(UID, "BND1")
r365 = pr.compute_realized_gain(disposals_365)
assert r365["lines"][0]["term"] == "short_term"
assert r365["short_term_gain"] == round(150.0 - 100.0, 2) and r365["long_term_gain"] == 0.0
print(f"  disposal_date={d('2022-01-01', 365)} (365d) -> short_term OK")

with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (UID, "BND2", 1, 100.0, "2022-01-01")
    )
disp_366 = memory_store.record_disposal(UID, "BND2", shares=1, proceeds=150.0, disposal_date=d("2022-01-01", 366), method="fifo")
disposals_366 = memory_store.get_disposals(UID, "BND2")
r366 = pr.compute_realized_gain(disposals_366)
assert r366["lines"][0]["term"] == "long_term"
assert r366["long_term_gain"] == round(150.0 - 100.0, 2) and r366["short_term_gain"] == 0.0
print(f"  disposal_date={d('2022-01-01', 366)} (366d) -> long_term OK")

# ── Test 5: empty inputs return honest zero/empty, not exceptions ──────────────
print("=== Test 5: empty inputs ===")
empty_unrealized = pr.compute_unrealized_gain([], {})
assert empty_unrealized == {
    "as_of": empty_unrealized["as_of"],
    "lots": [],
    "long_term_gain": 0.0,
    "short_term_gain": 0.0,
    "total_gain": 0.0,
}
empty_realized = pr.compute_realized_gain([])
assert empty_realized == {"lines": [], "long_term_gain": 0.0, "short_term_gain": 0.0, "total_gain": 0.0}
print("  compute_unrealized_gain([], {}) -> zero/empty, no exception OK")
print("  compute_realized_gain([]) -> zero/empty, no exception OK")

print("=== ALL TESTS PASSED ===")
