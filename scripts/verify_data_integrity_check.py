"""Scratch verification for run_data_integrity_checks() -- not part of the
test suite, run manually with PYTHONPATH set to the repo root. Uses a temp
DB so it never touches the live one.

Note: as of this writing, get_signals() on `main` still has the exact
.isoformat()-cutoff-vs-CURRENT_TIMESTAMP-column bug described in issue #123
(the fix already exists, unmerged, in PR #122). So a real signals row
written in the last hour is expected to produce an "alert" result below --
that is this check correctly doing its job, not a test failure. news_items
already has the fix on main, so it's expected to stay "ok"."""
import os
import tempfile

fd, path = tempfile.mkstemp(suffix=".db")
os.close(fd)

import memory_store as ms

ms.DB_PATH = path
ms.init_db()

with ms.get_conn() as conn:
    conn.execute(
        "INSERT INTO signals (source, asset, content, sentiment_score, signal_type) "
        "VALUES ('twitter', 'AAPL', 'test', 0.5, 'bullish')"
    )
    conn.execute(
        "INSERT INTO news_items (guid, title, source, published_at) "
        "VALUES ('g1', 'headline', 'yahoo', datetime('now'))"
    )

results = {r["check"]: r for r in ms.run_data_integrity_checks()}
print(results)

assert results["news_items"]["status"] == "ok", "news_items' fixed read path should not alert"
assert results["signals"]["status"] == "alert", (
    "expected the still-open get_signals bug (issue #123's whole reason for "
    "existing) to be caught -- if this now reads 'ok', PR #122 has likely "
    "merged and fixed get_signals; re-run this script to confirm the check "
    "itself still works by temporarily reintroducing the old cutoff bug."
)

# Confirm the "ok" path too: a table with zero recent writes should never
# alert just because it's quiet (that's the whole point -- only flag
# insert>0-but-read==0, not "nothing happened").
with ms.get_conn() as conn:
    conn.execute("DELETE FROM signals")
quiet_results = {r["check"]: r for r in ms.run_data_integrity_checks()}
assert quiet_results["signals"]["status"] == "ok", "an empty table must not be treated as an anomaly"
print(quiet_results["signals"])

os.remove(path)
print("OK")
