# Task: Enterprise-grade UI overhaul — all FredAI web pages

Prepared 2026-07-25 (assessment-only session, near token limit). Not started — hand this to `task-manager` first thing next session per the standing orchestration policy (now applies to ALL tasks, see `fredai_orchestration.md` memory note dated 2026-07-25).

## Goal
Bring FredAI's web UI to professional/enterprise financial-software presentation (Bloomberg/Refinitiv/FactSet-tier polish, per CLAUDE.md's own "Step 1 — Research" guidance) across every page. Keep the existing dark finance aesthetic and brand identity — this is a consistency/polish pass, not a redesign from scratch.

## Pages in scope
| File | Lines | Role |
|------|-------|------|
| `templates/dashboard.html` | 7242 | Main app: login, tabs, Fred chat, all panels |
| `templates/news.html` | 783 | News/globe view |
| `templates/timeline.html` | 523 | Event timeline / cascade view |
| `templates/video_popout.html` | 18 | Minimal video popout |

Pure presentation-layer work. Out of scope: backend/route logic, `soul.md`/Fred's personality, WebSocket event names/payloads, any DB schema.

## Assessment findings (live grep/read, 2026-07-25)

1. **No shared stylesheet.** Each template independently declares its own `:root` CSS custom-property block inline — no `static/*.css` file exists at all. Values have drifted between pages for the *same visual role*: `--gold` is `#f5a623` in `dashboard.html` but `#ffb703` in `news.html`/`timeline.html`. Variable naming also diverges: `dashboard.html` uses `--bg0`/`--bg1`.../`--t1`-`--t3`; `news.html`/`timeline.html` use `--bg`/`--bg1`... for the same roles. No single source of truth for design tokens.
2. **Typography inconsistency.** `dashboard.html` imports both "Outfit" and "Inter" webfonts; `news.html` and `timeline.html` import only "Inter". No documented rule for which face is used where.
3. **No persistent shared navigation.** Grepping all 4 templates for `nav`/`navbar`/`header`/`topbar`/`sidebar` class markers returns zero matches. Cross-page movement is a handful of ad hoc one-off links (`dashboard.html` → `/news` "VIEW ALL ↗"; `timeline.html` → `/graph`) rather than a consistent global nav shell. A user landing directly on `/news` or `/timeline` has no way back to the dashboard except the browser back button.
4. **Monolithic single-file templates.** Embedded `<style>`/`<script>` blocks per page, no shared partials/includes, no build step (`dashboard.html` alone is 7242 lines). Makes it structurally hard to guarantee a consistent spacing scale, elevation/shadow system, or button/card/modal component set across pages — each page has reinvented its own.
5. **CLAUDE.md's documented palette is stale.** The repo's own `CLAUDE.md` states the theme is `#03080f, #00ff88, #ff3b5c, #00b4ff` — none of these literals match what's actually in the templates (`--bg0:#020408`, `--green:#00ffaa`, `--red:#ff3366`, `--blue:#00d2ff`). Whatever palette the overhaul lands on should be written back into `CLAUDE.md` so the doc stops lying about the real implementation.
6. **`video_popout.html`** is 18 lines, effectively unstyled relative to the other three — needs an explicit decision (intentional minimal popout vs. neglected), not silent exclusion.

## Recommended decomposition (for task-manager to verify/refine, not gospel)
- Unit A — shared design-token file (fixes finding 1+2): one canonical `static/css/tokens.css` (or Jinja include), single set of CSS custom properties, single font import. Every other unit depends on this landing first.
- Unit B — shared nav/header partial (fixes finding 3): a Jinja include or templated header block, wired into all 4 pages.
- Unit C/D/E — per-page polish pass consuming A+B (dashboard/news/timeline), likely parallel-safe against each other once A+B exist since each touches a disjoint file.
- Unit F — `video_popout.html` decision + minimal consistency pass.
- Unit G — update `CLAUDE.md`'s theme-color documentation to match final shipped tokens.

### Unit F — resolved (remediation cycle 1, 2026-07-26)
`video_popout.html` is intentionally excluded from the shared nav/header rollout. It's a
chromeless popup window opened via `window.open()` (see `main.py`'s `/popout/video` route
docstring: "Standalone floating player window -- opened via window.open() from any video
widget, so it's a genuinely separate browsing context that survives the opener navigating to
a different page/tab"). It's designed to survive the opener navigating away, not to be a
navigable page in its own right — adding back/nav links to it would contradict its purpose as
a disposable floating player. It received Unit A's token-consistency treatment (`tokens.css`
wired in) and nothing further; this is now a recorded decision, not a silent omission.

## Acceptance bar (for approver stage)
- All 4 pages visually verified in a real browser (via `/run` skill or claude-in-chrome), not just source-diffed — dark theme only, no light-mode requirement exists today.
- No functional regression: Fred chat, live chart updates, SocketIO events (`market_update`/`new_signal`/`summary_update`/`alert`/`timeline_update`/`chat_response`) all still fire and render.
- CSS variable names *and* values consistent across all pages — zero drift of the kind found in finding 1.
- Every page reachable from every other page via a consistent nav element.
- `CLAUDE.md` palette section matches the real shipped tokens (closes finding 5).

## Why this file exists
Session hit its token/time limit right after this assessment — no implementation happened. This is a prepared task-manager input, not a completed feature. See `fredai_orchestration.md` and `fredai.md` memory files for the current standing orchestration policy this should route through.
