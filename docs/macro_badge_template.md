# Macro badge template

Every shipped macro-strip badge (Copper/Gold ratio, Fear & Greed, Broad
Dollar Index, NFCI, Treasury auction demand, Trade Balance, Case-Shiller,
Consumer Credit, Savings Rate, Capacity Utilization, ...) follows the same
five-part shape. Re-deriving this pattern from scratch each cycle has been a
recurring cost — use this doc instead.

## The five parts

1. **`_trend(series)` helper** — latest value + rolling z-score/direction
   against the trailing window, *excluding the latest point* (so the
   z-score isn't self-referential):

   ```python
   def _trend(series: list[float]) -> dict | None:
       if len(series) < 8:
           return None
       latest = series[-1]
       baseline = series[:-1]
       mean = statistics.fmean(baseline)
       stdev = statistics.pstdev(baseline)
       z = (latest - mean) / stdev if stdev else 0.0
       if z > 0.5:
           direction = "rising"
       elif z < -0.5:
           direction = "falling"
       else:
           direction = "stable"
       return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}
   ```

   **Sign-convention gotcha**: this assumes a positive-valued series where
   "higher is more of the thing." A negative-valued/deficit-style series
   (e.g. `BOPGSTB` trade balance) needs the comparison flipped — a *lower*
   (more negative) reading is *more* deficit, so `z < -0.5` → "widening" and
   `z > 0.5` → "narrowing", not the other way around. Before shipping any
   new negative-valued badge, sanity-check the computed `direction`/`regime`
   against the plain-English meaning of the raw numbers, not just that the
   function returns cleanly — see `trade_balance_client.py` for the fixed
   example and the project memory entry for the bug this caught live.

2. **`compute_*()` pure function** — fetches raw data, returns a plain dict
   (`{"latest": ..., "trend": {...}, "regime": ...}` or similar), returns
   `None` on any fetch failure. No caching, no side effects.

3. **`get_*(force=False)` TTL-cached accessor**:

   ```python
   _CACHE_TTL_S = 900  # 15min-1h depending on the series' real update cadence
   _cache: dict = {"computed_at": 0.0, "data": None}

   def get_*(force: bool = False) -> dict | None:
       now = time.time()
       if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
           data = compute_*()
           if data:
               _cache["data"] = data
               _cache["computed_at"] = now
       return _cache["data"]
   ```

   Match the TTL to the series' real cadence — a monthly-updated FRED series
   (e.g. `BOPGSTB`) is fine at a 1h TTL; something like Fear & Greed that
   moves intraday wants 15min.

4. **One `_macro_cache["KEY"]` block in `main.py::job_market_refresh()`**:

   ```python
   try:
       x = get_*()
       if x:
           _macro_cache = {**_macro_cache, "KEY": {
               "label": "Short Label", "value": x["latest"], "rating": x["regime"],
           }}
   except Exception as e:
       print(f"[Job] *_client error: {e}")
   ```

5. **One `/api/*` route**, `@login_required`, returning `jsonify(get_*() or {})`.

## Data source patterns

- **FRED series**: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>`,
  fetched with plain `requests.get(url, timeout=15)` — never `curl`, which
  hits a false-positive HTTP/2 stream-reset on this endpoint. Keyless, no
  auth.
- **Yahoo-sourced prices/ETFs**: use `market_data.fetch_history()` /
  `market_data.fetch_quotes()` — the app's own direct Yahoo chart-endpoint
  wrapper. Never call `yfinance.Ticker.fast_info` (reliably crashes the
  process, no catchable exception) or `yfinance.Ticker.history()` for
  dividend-paying tickers (crashes in pandas' tz-localize path).
- **HTML sources without an explicit charset header**: feed `r.content`
  (bytes) to BeautifulSoup, never `r.text` — `requests`' Latin-1 fallback
  silently corrupts UTF-8.

## Dashboard wiring

`renderMacroStrip()` in `templates/dashboard.html` is fully generic — it
reads `_macro_cache`'s `{label, value, rating}` shape directly. A new badge
following this template needs **zero** `dashboard.html` changes, unless you
want a rating-based color hint (add an entry to the `_FG_COLOR` map) or a
non-obvious abbreviated label (add an entry to the `LBL` map). Most badges
need neither.

## Verification

Never call `job_market_refresh()` (or any APScheduler job entrypoint)
directly to smoke-test — slow, no real server, and headless `claude -p`
output is buffered until exit so a timeout kill loses everything. Always
sufficient instead:

```python
from <module> import compute_*, get_*
print(compute_*())  # or get_*(force=True)
```

plus one Flask-test-client hit on the new route to confirm it's wired
(a 401 unauthenticated response is a fine, expected result for this check).

## Proposal-creation conventions (if sourcing a new badge idea)

- `insert_feature_proposal(title, description, category, implementation_spec="", estimated_hours=2, impact_score=5.0, priority=3, proposed_by="claude")`
  has **no `fsi_level` kwarg** — template the description as
  `f"[FSI L{level}] {body}"` instead, or it lands the `fsi-l?` label.
- Always pass `proposed_by="claude"` explicitly for anything self-identified
  (not from the normal R&D discovery cycle) — a copied `"rnd_cycle"` default
  silently no-ops the `agent_track_record` bump.
- `risk_rules.py::classify_risk()` has no negation awareness — any of
  `auth, login, password, session, oauth, token, secret, credential,
  payment, billing, encrypt, decrypt, permission` anywhere in the proposal
  text trips `risk:high` regardless of phrasing. Run the draft text through
  the keyword list as an actual command before calling
  `insert_feature_proposal`, don't eyeball it.
- Never `gh issue create` a proposal by hand — always go through
  `insert_feature_proposal()` + `sync_proposal_to_issue()` (which takes the
  dict from `get_proposal(id)`, not the raw int `insert_feature_proposal()`
  returns).
