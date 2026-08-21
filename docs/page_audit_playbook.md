# Page audit playbook

Standing checklist for the page-by-page UI audit series (Home #521, Overview
#531, Portfolio #546, Situation Room #547, AI Universe #549, Watchlist #550).
Run all four checks on every page audited from here on. Keep this file
updated if a new standing-check class gets found.

## 1. Widget verdict pass

For every widget/panel on the page, assign one verdict:

- **KEEP** — works correctly, not a duplicate, no action.
- **KEEP-BUT-FIX** — real bug (stale/wrong data source, mislabeled,
  dead/orphaned plumbing) but the widget earns its place. Fix in place.
  Example: Watchlist's Sentiment column bound to a client-side heuristic
  instead of the real `avg_sentiment` field the backend already shipped
  (PR #550).
- **SUPPRESS** — strictly duplicates a live-updating panel that already
  exists elsewhere on the page or on another tab. Remove, don't just hide.
  Example: Home tab's "Latest News"/"Market Ops" mini-widgets duplicating
  Overview's socket-pushed panels (PR #521).

Cross-check every candidate SUPPRESS against every other tab before cutting
it — "duplicate" has to be verified, not assumed from the widget title.

## 2. Tab-scoping-bug-class check

Panels can leak onto every tab instead of just their own if they're missing
from the tab's visibility array (search `switchTab(` and the per-tab arrays
it reads, e.g. `OV`/`PF`/similar lists in `dashboard.html`). This bit
Overview (PR #531): 6 panels rendered on every tab because of one missing
array entry.

- For every panel added or touched, confirm it appears in exactly one
  tab-visibility array (or is intentionally global).
- Trace every entry path into the tab (nav click, deep link, nano/micro-tier
  default-tab logic) — a missing-array bug can be invisible from the normal
  click path and only show up on a different entry point.

## 3. Live-label honesty check

A widget can use 100% real data and still lie about being "live" if it only
fetches once on tab-switch instead of actually refreshing. Check every
"live"/"real-time" label against its actual refresh mechanism:

- Is there a websocket push branch (e.g. `market_update`) wired for this
  tab specifically, or does it only load on `switchTab()`? (AI Universe's
  "live prices" label was accurate only at the instant of tab-switch until
  PR #549 wired the same `market_update` branch Trending already had.)
- Does a polling/auto-refresh timer exist, and is it scoped to only run
  while the tab is actually visible (don't burn fetches on a backgrounded
  tab, don't let a visible tab go stale)?

## 4. Fake-live data sweep

Check for data presented as live/current that's actually fabricated or a
disclosed replay without an honest comment saying so. Real jitter used
purely for animation/visual polish is fine and should be left alone —
this check is about data claims, not motion.

Grep patterns to run (repo root):

```
grep -rn "Math\.random\|Math\.floor(Math\.random\|Math\.round(Math\.random" templates/ static/
grep -rn "Math\.sin(\|Math\.cos(" templates/ static/
grep -rniE "function (rand|fake|mock|simulate|jitter)" templates/ static/
grep -rni "simulat\|canned\|hardcoded\|dummy data\|fake data\|placeholder data" templates/ static/
grep -rniE "\bnoise\(|perlin|generateFake|randomLog|synthetic" templates/ static/
```

Then, by hand: find every UI label containing "live"/"feed"/"HUD"/"stream"
(`grep -ni "live\b\|feed\b\|\bhud\b\|stream"`) and check whether any
hardcoded/literal array sits next to it as the actual data source — a
canned array can fabricate "live" data without ever calling `Math.random`.
Static reference/config data (geocoding lookup tables, channel-ID configs,
color palettes) is not a violation; only content presented to the user as
live/current that's actually fabricated or undisclosed-replay is.

Reference fix pattern (Situation Room HUD, commit `0aa07ad` / PR #547):
replaced a `setInterval` cycling through a hardcoded canned-log array with
one cycling through the real `story_arcs`/`points` already fetched for the
globe that session, plus an explicit code comment disclosing it's a replay
of real ingested signals, not a claim of sub-second live streaming.

If a hit turns out to be a genuine violation, fix it the same way: wire in
the real data already available (don't invent a new fetch if the page
already has the data in memory), and add a comment that honestly states
what the feed actually is.
