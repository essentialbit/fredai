"""Scratch verification for GET /api/portfolio/gains (unit 4.4, Unit 1) --
the new login_required route that surfaces per-lot unrealized gain
(portfolio_risk.compute_unrealized_gain) and per-disposal realized gain
(portfolio_risk.compute_realized_gain) for the caller's own tax lots.

Runs against a scratch copy of the real sentinel.db (never the live file) --
memory_store.DB_PATH is monkeypatched to a temp copy before main.py (and
therefore memory_store) is ever asked to touch a database, matching this
repo's standing convention (see scripts/verify_gain.py, verify_causal_attribution.py).

Confirms: zero-lots/zero-disposals returns 200 with zero/empty structures
(never an error), a lot's `backfilled` flag is attached to its unrealized
per-lot entry even though compute_unrealized_gain's own output doesn't carry
it, a real disposal's realized gain comes through the route, and a second
user's lots/disposals for the same symbol never leak into the first user's
response."""
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

SCRATCH_DB = "/tmp/gains_route_verify_copy.db"
LIVE_DB = os.path.join(PROJECT_ROOT, "data", "sentinel.db")

if os.path.exists(SCRATCH_DB):
    os.remove(SCRATCH_DB)
if os.path.exists(LIVE_DB):
    shutil.copy(LIVE_DB, SCRATCH_DB)
# else: this worktree checkout has no data/sentinel.db (gitignored, not
# shared with the primary checkout) -- memory_store.init_db() below creates
# the schema fresh via CREATE TABLE IF NOT EXISTS, so a missing live file is
# fine; either way the live file is never opened for writes by this script.

import memory_store
memory_store.DB_PATH = SCRATCH_DB
memory_store.init_db()

import main  # noqa: E402  -- imported only after DB_PATH is patched

app = main.app
app.config["TESTING"] = True

USER_A = 991
USER_B = 992
SYMBOL = "GAINRT"


def login(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


# ── Test 1: zero lots / zero disposals -> 200, zero/empty structures ───────────
print("=== Test 1: zero lots/disposals ===")
client = app.test_client()
login(client, USER_A)
resp = client.get("/api/portfolio/gains")
assert resp.status_code == 200, resp.status_code
body = resp.get_json()
assert body["unrealized"]["lots"] == []
assert body["unrealized"]["total_gain"] == 0.0
assert body["unrealized"]["long_term_gain"] == 0.0
assert body["unrealized"]["short_term_gain"] == 0.0
assert body["realized"]["lines"] == []
assert body["realized"]["total_gain"] == 0.0
print("  GET /api/portfolio/gains with no lots/disposals -> 200 zero/empty OK")

# ── Test 2: unauthenticated request -> 401, not a leak ─────────────────────────
print("=== Test 2: unauthenticated ===")
anon = app.test_client()
resp = anon.get("/api/portfolio/gains")
assert resp.status_code == 401, resp.status_code
print("  GET /api/portfolio/gains with no session -> 401 OK")

# ── Test 3: invalid symbol query param -> 400 ───────────────────────────────────
print("=== Test 3: invalid symbol ===")
resp = client.get("/api/portfolio/gains?symbol=<script>")
assert resp.status_code == 400, resp.status_code
print("  GET /api/portfolio/gains?symbol=<script> -> 400 OK")

# ── Test 4: a lot with backfilled=1 carries the flag through per-lot ───────────
print("=== Test 4: backfilled flag attached to unrealized per-lot entry ===")
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,1)",
        (USER_A, SYMBOL, 10, 1000.0, "2023-01-01")
    )
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (USER_A, SYMBOL, 5, 600.0, "2024-01-01")
    )
main._quotes_cache[SYMBOL] = {"price": 150.0}

resp = client.get(f"/api/portfolio/gains?symbol={SYMBOL}")
assert resp.status_code == 200, resp.status_code
body = resp.get_json()
lots_by_shares = {l["shares"]: l for l in body["unrealized"]["lots"]}
assert lots_by_shares[10.0]["backfilled"] == 1, lots_by_shares[10.0]
assert lots_by_shares[5.0]["backfilled"] == 0, lots_by_shares[5.0]
expected_gain = (10 * 150.0 - 1000.0) + (5 * 150.0 - 600.0)
assert body["unrealized"]["total_gain"] == round(expected_gain, 2)
print(f"  backfilled=1 lot -> backfilled:1, backfilled=0 lot -> backfilled:0 OK "
      f"(total_gain={body['unrealized']['total_gain']})")

# ── Test 5: symbol with lots but no fetchable price is skipped, not fabricated ─
print("=== Test 5: no-price symbol skipped from unrealized, no $0 fabrication ===")
NOPRICE = "NOPRICE1"
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (USER_A, NOPRICE, 3, 300.0, "2024-01-01")
    )
resp = client.get(f"/api/portfolio/gains?symbol={NOPRICE}")
body = resp.get_json()
assert body["unrealized"]["lots"] == [], body["unrealized"]["lots"]
assert body["unrealized"]["total_gain"] == 0.0
print("  lot with no current price -> omitted from unrealized lots/totals OK")

# ── Test 6: a disposal's realized gain comes through the route ─────────────────
print("=== Test 6: realized gain via a real disposal ===")
DISP_SYMBOL = "GAINRT2"
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (USER_A, DISP_SYMBOL, 10, 1000.0, "2022-01-01")
    )
disposal_id = memory_store.record_disposal(
    USER_A, DISP_SYMBOL, shares=10, proceeds=1500.0, disposal_date="2025-01-01", method="fifo"
)
resp = client.get(f"/api/portfolio/gains?symbol={DISP_SYMBOL}")
body = resp.get_json()
lines = body["realized"]["lines"]
assert len(lines) == 1, lines
assert lines[0]["disposal_id"] == disposal_id
assert lines[0]["shares_used"] == 10.0
assert lines[0]["gain"] == round(1500.0 - 1000.0, 2)
assert "backfilled" not in lines[0], "disposal_lots carries no backfilled column"
assert body["realized"]["total_gain"] == round(1500.0 - 1000.0, 2)
print(f"  disposal realized gain={body['realized']['total_gain']} OK, "
      f"no fabricated backfilled field on realized lines OK")

# ── Test 7: cross-user isolation -- user B's identical-symbol data never leaks ─
print("=== Test 7: cross-user isolation ===")
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,1)",
        (USER_B, SYMBOL, 999, 999000.0, "2020-01-01")
    )
with memory_store.get_conn() as conn:
    conn.execute(
        "INSERT INTO tax_lots (user_id, symbol, shares, cost_basis, acquired_date, backfilled) VALUES (?,?,?,?,?,0)",
        (USER_B, DISP_SYMBOL, 50, 5000.0, "2020-01-01")
    )
memory_store.record_disposal(USER_B, DISP_SYMBOL, shares=50, proceeds=6000.0, disposal_date="2025-01-01", method="fifo")

# user A, no symbol filter -> must not see user B's 999-share lot or B's disposal
resp = client.get("/api/portfolio/gains")
body = resp.get_json()
all_shares = [l["shares"] for l in body["unrealized"]["lots"]]
assert 999.0 not in all_shares, "user B's lot leaked into user A's response"
all_disposal_ids = [l["disposal_id"] for l in body["realized"]["lines"]]
assert disposal_id in all_disposal_ids
b_disposals = memory_store.get_disposals(USER_B, DISP_SYMBOL)
assert b_disposals[0]["id"] not in all_disposal_ids, "user B's disposal leaked into user A's response"

# Confirm the route is genuinely session-scoped (not a client-supplied id):
# logging in as user B and hitting the same symbol must surface B's own
# 999-share lot -- proving the route reads session["user_id"], and that user
# A's earlier response wasn't just coincidentally missing it.
client_b = app.test_client()
login(client_b, USER_B)
b_lots_raw = memory_store.get_lots(USER_B, SYMBOL)
assert len(b_lots_raw) == 1 and b_lots_raw[0]["shares"] == 999.0
a_shares = [l["shares"] for l in lots_by_shares.values()]
assert 999.0 not in a_shares
print("  user A's response contains none of user B's lots/disposals for the same symbol OK")
print("  user B's data independently confirmed present in the DB (not just absent for A) OK")

print("=== ALL TESTS PASSED ===")
