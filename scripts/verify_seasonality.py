import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
tmp_db = tempfile.mktemp(suffix=".db")
config.DB_PATH = tmp_db

import memory_store
memory_store.DB_PATH = tmp_db
memory_store.init_db()

import seasonality_engine

# Build 6 years of synthetic daily closes: Septembers trend down, everything
# else drifts up slightly -- so the September monthly bias should come back
# negative with a low hit rate, distinct from other months.
closes = {}
start = datetime(2020, 1, 1)
price = 100.0
d = start
while d < datetime(2026, 1, 1):
    if d.weekday() < 5:  # weekdays only, like real market data
        if d.month == 9:
            price *= 0.995
        else:
            price *= 1.0007
        closes[d.strftime("%Y-%m-%d")] = round(price, 2)
    d += timedelta(days=1)

seasonality_engine._history_cache["TEST"] = (__import__("time").time(), closes)

bias = seasonality_engine.compute_seasonal_bias("TEST")
assert bias["status"] == "ok", bias
sept = next(m for m in bias["months"] if m["period_value"] == 9)
other = next(m for m in bias["months"] if m["period_value"] == 1)
assert sept["avg_return_pct"] < 0, sept
assert other["avg_return_pct"] > 0, other
assert sept["sample_size"] >= 5
print(f"September bias: {sept}")
print(f"January bias: {other}")
assert len(bias["weekdays"]) == 5  # Mon-Fri only, synthetic data has no weekend rows

memory_store.save_seasonal_bias("TEST", bias)

current = memory_store.get_current_seasonality("TEST")
print(f"Current cached lookup: {current}")
assert current["ticker"] == "TEST"
now = datetime.utcnow()
expected_month = next((m for m in bias["months"] if m["period_value"] == now.month), None)
if expected_month:
    assert current["month"] is not None
    assert current["month"]["period_value"] == now.month
else:
    assert current["month"] is None

# Re-run save to confirm the ON CONFLICT upsert path doesn't blow up or duplicate rows.
memory_store.save_seasonal_bias("TEST", bias)
with memory_store.get_conn() as conn:
    count = conn.execute(
        "SELECT COUNT(*) c FROM seasonality_cache WHERE ticker='TEST'"
    ).fetchone()["c"]
assert count == len(bias["months"]) + len(bias["weekdays"]), count

# insufficient_history path
empty_bias = seasonality_engine.compute_seasonal_bias("NOHISTORY")
assert empty_bias["status"] == "insufficient_history"
memory_store.save_seasonal_bias("NOHISTORY", empty_bias)  # must no-op, not crash

os.remove(tmp_db)
print("ALL SEASONALITY CHECKS PASSED")
