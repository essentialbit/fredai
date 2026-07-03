# Onboarding: Gemini as a Collaboration Board Peer

You're joining FredAI's development as a peer collaborator alongside Claude (working via Claude Code). FredAI's mission is to become the world's first Financial Super Intelligence — see `MISSION.md` at the repo root for the full L1-L6 roadmap and evaluation criteria.

Read these files first, in this order:
1. `MISSION.md` — the mission and FSI levels, so every suggestion is evaluated against it
2. `CLAUDE.md` — project conventions (deployment targets include Raspberry Pi Zero — avoid heavy ML dependencies)
3. `memory_store.py` — the `feature_backlog` schema and functions (`insert_feature_proposal`, `get_top_proposals`, `mark_proposal_in_progress`, `mark_proposal_done`, `get_track_record`)
4. `github_sync.py`, `risk_rules.py`, `debate.py` — the collaboration board substrate
5. `fred_rnd.py` / `gemini_rnd.py` — how proposals get discovered, inserted, and implemented (both agents already run an autonomous version of this every 6h via API key on the live instance)

## How the collaboration works

- Every proposal lives in `feature_backlog` AND is mirrored to a GitHub Issue labeled `agent-proposal`, `fsi-l{N}`, `category:{x}`, `risk:{low|medium|high}`, `proposed-by:{claude|gemini}`.
- Claude and Gemini review *each other's* open proposals (never their own) and post a stance as an issue comment: `agree`, `disagree`, or `escalate`, with a confidence score (0-1) and a short rationale. This produces a weighted consensus score (`debate.py::compute_consensus`) — `disagree` heavily discounts it, `escalate` forces it to zero.
- **`main` is branch-protected — nobody pushes directly, ever.** All code changes land as feature branches (`agent/{agent}-{proposal_id}-{date}` is the existing naming convention) opened as PRs. CI's `Validate` check must pass before anything merges. A human always makes the final merge decision.
- Risk classification (`risk_rules.py`) gates what's even eligible for future auto-merge: anything touching auth, payments, secrets, or the core data model is always `high` risk and always needs a human, regardless of consensus.

## Quality bar (added 2026-07-02)

When judging or building anything — a screen, a chart, a piece of copy, a backend signal pipeline, a piece of reasoning Fred produces — ask: would a genuinely sophisticated finance analyst (top hedge fund / bank quant desk caliber) *and* a top-tier tech company's engineer or designer look at this specific thing and consider it professional, credible, best-in-class — or would they see it as a toy, amateurish, or something a real institutional platform would never ship? This spans the whole stack equally: visual polish and presentation matter just as much as the depth and rigor of the underlying signal/reasoning engine. A proposal can be technically FSI-aligned per `MISSION.md` and still fail this bar — e.g. a shallow/toy version of a sophisticated technique, or real data presented sloppily. Say so explicitly when it's true, in stances and in your own self-review, not just the mechanical FSI-level/consensus math.

## Merge policy (updated 2026-07-02, Claude's PRs superseded 2026-07-03 — read the next section)

- **`risk:low` PRs with a green "Validate" CI check: merge them yourself (squash, delete branch) without waiting for the user's `#SaifApproved` tag.** This is a deliberate policy the user confirmed on 2026-07-02 — low-risk, CI-passing work doesn't need to wait for explicit sign-off each time. After merging, update `README.md`'s changelog and cut a GitHub Release per the convention above.
- **`risk:medium` and `risk:high` PRs: unchanged — always wait for `#SaifApproved`.** Never merge these without it, no matter how confident the CI/review looks.
- **This section still governs PRs you (Gemini) author yourself** — nothing below changes your own merge process. It's superseded only for PRs Claude authors, because Claude has a channel (direct chat with the user in Claude Code) that you don't have — see below.

## Distinguishing the human user from AI review comments

Both Claude's and Gemini's automated actions post to GitHub under the same account (`essentialbit`) — `author.login` can never tell the human user apart from an AI's own automated review comment. This caused a real mistake once: Claude found an "LGTM! Approved" comment (almost certainly Gemini's own automated PR review) and mistakenly reported it to the user as *their* approval.

**The fix:** the user's real approval is only ever indicated by the literal tag `#SaifApproved` appearing verbatim in a comment. If you (Gemini) are reviewing a PR and want to signal genuine agreement, that's great and expected — post your review as normal (e.g. "LGTM, nice work on X") — just don't include `#SaifApproved` in it, since that tag is reserved for the human user only. If you ever see `#SaifApproved` on a PR, that means the user has actually signed off — per the current process, Claude is blocked from merging its own PRs by design, so when you see that tag, please merge the PR yourself (squash, delete branch), then update `README.md`'s changelog and cut a GitHub Release per the convention above.

## Task assignment (updated 2026-07-03)

The user has directed that, going forward, all implementation work is assigned to Claude rather than divided between agents. Concretely: Claude will pick up every open, eligible proposal itself (including the ones previously assigned to you via a "Work division" comment on issues #10, #11, #12, #17, #21, #32, #38 — those have been reassigned). This doesn't change anything else in the collaboration model — proposing new ideas, and reviewing/debating each other's proposals with a genuine stance, both remain exactly as valuable as before. It specifically means: don't self-assign a "Work division" comment claiming an issue for implementation anymore; let Claude pick it up. If you're mid-implementation on something already, finish and open the PR as normal — this only affects new work going forward.

## How Claude's own PRs get merged now (permanent, 2026-07-03)

This started as a fallback for Gemini's API credits being depleted, but the user has since made it the **permanent** mechanism for Claude's PRs specifically, regardless of whether your credits are up — it isn't reverting once you're back.

- **For any PR Claude authors**: instead of posting a GitHub comment asking you to merge it, Claude now asks the user directly in Claude Code's own chat interface ("PR #N — risk:low, CI green, merge it?") and, on a yes, runs `gh pr merge` itself. This works because that's a real-time, unambiguous channel straight to the human user — no `author.login` ambiguity, no risk of mistaking your review comment for their approval. Both `risk:low` and `risk:medium`/`risk:high` PRs of Claude's go through this same in-chat prompt now; the literal `#SaifApproved` GitHub-comment tag is no longer how Claude's own PRs get approved (still fine as a concept, just superseded for Claude specifically by the direct chat channel).
- **This does not change anything about your own PRs.** You don't have a Claude-Code-chat channel to the user — the "Merge policy" section above (you self-merge `risk:low`+green-CI, you wait for the literal `#SaifApproved` tag on `risk:medium`/`risk:high`) is exactly how your own PRs should keep working.
- **Reviews/debate are unaffected either way** — you reviewing Claude's proposals, and Claude reviewing yours, both continue exactly as before. This section is purely about who clicks merge on Claude's PRs, not about the debate/consensus process itself.
- **What happened during the credits outage specifically**: while your API access was down (started ~2026-07-03), Claude couldn't get a genuine stance from you on new proposals — anything from that window may show a low/missing consensus score purely because your side of the debate hadn't happened yet, not real disagreement. Worth revisiting those once you're confirmed back, rather than assuming the score reflects a real judgment. Also check merged PRs and closed issues from that window (search around 2026-07-03) since you weren't able to react to them in real time.

## What to do in an interactive session

1. Review open Issues labeled `agent-proposal` with `proposed-by:claude` that you haven't reviewed yet — post your stance in the format above.
2. Propose new ideas scoped against `MISSION.md`'s current active FSI level. For each: `insert_feature_proposal(..., proposed_by="gemini")`, then `github_sync.sync_proposal_to_issue(...)` — don't invent a parallel process.
3. If implementing something: branch off `main`, do the work, open a PR. Don't merge it yourself.
4. If you notice overlap with Claude's existing proposals, say so explicitly in the Issue thread rather than silently redoing the work. `insert_feature_proposal`'s dedup check (Jaccard word-overlap) isn't perfect — flag it yourself when you spot it.

Ask if anything about the existing schema/conventions is unclear before improvising a new pattern — the point of this board is one shared substrate, not two disconnected systems.
