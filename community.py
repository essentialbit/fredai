#!/usr/bin/env python3
"""
community.py — FredAI GitHub Community Engagement

Monitors Issues, Discussions, and open PRs every 6h.
Classifies interactions with Claude and responds to productive ones.
Silently ignores spam, off-topic, hostile, or low-value content
(no engagement is the correct response to unproductive interactions).

Requires:
    GITHUB_TOKEN  — PAT with `repo` scope (or Actions default token in CI)
    GITHUB_REPO   — "owner/repo" e.g. "essentialbit/fredai"
    ANTHROPIC_API_KEY — for Claude classification + response generation

Run standalone:  python3 community.py
Called from:     improve.py Phase 0 and APScheduler job_community (every 6h)
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, UTC
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO  = os.getenv("GITHUB_REPO", "essentialbit/fredai")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

_GH_API  = "https://api.github.com"
_GH_GQL  = "https://api.github.com/graphql"
_TIMEOUT = 20

# Maximum comments Fred posts per engagement cycle (avoid spam bursts)
MAX_RESPONSES_PER_CYCLE = 8

# ── Persistence (SQLite community_log table) ──────────────────────────────────

_DB_PATH = Path(__file__).parent / "data" / "sentinel.db"


@contextmanager
def _db():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_table():
    with _db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS community_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type   TEXT NOT NULL,      -- issue | discussion | pr
                item_id     TEXT NOT NULL,      -- number or graphql node_id
                action      TEXT NOT NULL,      -- responded | labeled | ignored
                category    TEXT,               -- bug_report | feature_request | ...
                responded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(item_type, item_id)
            )
        """)


def _already_handled(item_type: str, item_id: str) -> bool:
    with _db() as c:
        row = c.execute(
            "SELECT 1 FROM community_log WHERE item_type=? AND item_id=?",
            (item_type, str(item_id))
        ).fetchone()
    return row is not None


def _mark_handled(item_type: str, item_id: str, action: str, category: str = ""):
    with _db() as c:
        c.execute(
            "INSERT OR IGNORE INTO community_log (item_type, item_id, action, category) VALUES (?,?,?,?)",
            (item_type, str(item_id), action, category)
        )


# ── GitHub REST helpers ───────────────────────────────────────────────────────

def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FredAI-Community-Bot/1.0",
    }


def _gh_get(path: str, params: dict | None = None) -> list | dict | None:
    try:
        r = requests.get(
            f"{_GH_API}/{path.lstrip('/')}",
            headers=_gh_headers(), params=params, timeout=_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
        print(f"  [GH] GET {path} → {r.status_code}")
    except Exception as e:
        print(f"  [GH] GET error {path}: {e}")
    return None


def _gh_post(path: str, body: dict) -> dict | None:
    try:
        r = requests.post(
            f"{_GH_API}/{path.lstrip('/')}",
            headers=_gh_headers(), json=body, timeout=_TIMEOUT
        )
        if r.status_code in (200, 201):
            return r.json()
        print(f"  [GH] POST {path} → {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"  [GH] POST error {path}: {e}")
    return None


def _gh_delete(path: str) -> bool:
    try:
        r = requests.delete(
            f"{_GH_API}/{path.lstrip('/')}",
            headers=_gh_headers(), timeout=_TIMEOUT
        )
        if r.status_code in (200, 204):
            return True
        # 404 means the label was already gone — treat as success, not an error.
        if r.status_code == 404:
            return True
        print(f"  [GH] DELETE {path} → {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"  [GH] DELETE error {path}: {e}")
    return False


def _post_issue_comment(number: int, body: str) -> bool:
    result = _gh_post(f"repos/{GITHUB_REPO}/issues/{number}/comments", {"body": body})
    return result is not None


def _add_labels(number: int, labels: list[str]) -> bool:
    result = _gh_post(f"repos/{GITHUB_REPO}/issues/{number}/labels", {"labels": labels})
    return result is not None


def _get_open_issues() -> list[dict]:
    """Fetch open issues (excludes PRs which have a pull_request key)."""
    data = _gh_get(f"repos/{GITHUB_REPO}/issues", {
        "state": "open", "per_page": 50, "sort": "created", "direction": "desc"
    })
    if not data:
        return []
    return [i for i in data if not i.get("pull_request")]


def _get_open_prs() -> list[dict]:
    data = _gh_get(f"repos/{GITHUB_REPO}/pulls", {
        "state": "open", "per_page": 20, "sort": "created", "direction": "desc"
    })
    return data or []


def _get_discussions() -> list[dict]:
    """Fetch open discussions via GraphQL."""
    if not GITHUB_TOKEN:
        return []
    owner, repo = GITHUB_REPO.split("/", 1)
    query = """
    query($owner: String!, $repo: String!, $first: Int!) {
      repository(owner: $owner, name: $repo) {
        discussions(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes {
            id
            number
            title
            body
            category { name }
            author { login }
            createdAt
            comments(first: 1) { totalCount }
            isAnswered
          }
        }
      }
    }
    """
    try:
        r = requests.post(
            _GH_GQL,
            headers=_gh_headers(),
            json={"query": query, "variables": {"owner": owner, "repo": repo, "first": 30}},
            timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            return (data.get("data", {})
                        .get("repository", {})
                        .get("discussions", {})
                        .get("nodes", []))
    except Exception as e:
        print(f"  [GH] Discussions GraphQL error: {e}")
    return []


def _post_discussion_comment(discussion_id: str, body: str) -> bool:
    mutation = """
    mutation($discussionId: ID!, $body: String!) {
      addDiscussionComment(input: {discussionId: $discussionId, body: $body}) {
        comment { id }
      }
    }
    """
    try:
        r = requests.post(
            _GH_GQL,
            headers=_gh_headers(),
            json={"query": mutation, "variables": {"discussionId": discussion_id, "body": body}},
            timeout=_TIMEOUT,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"  [GH] Discussion comment error: {e}")
    return False


# ── Claude classification + response ─────────────────────────────────────────

_SYSTEM = """\
You are the community engagement AI for FredAI, an open-source financial intelligence dashboard.
Your job is to classify GitHub community interactions and, where appropriate, draft a warm,
direct, technically competent response.

Engagement philosophy:
- Respond helpfully to genuine bug reports, feature ideas, questions, and contributions.
- Keep responses concise — 2–5 sentences for simple items, structured markdown for complex ones.
- Tone: friendly and direct. Not sycophantic. Not corporate.
- NEVER engage with spam, hostility, off-topic content, or low-effort noise.
  Silence is the correct response to those.
- Do not promise specific timelines. Do not make financial recommendations.
- Sign off as "— Fred" (the AI persona), not with a name or role title.

Return a JSON object with exactly these fields:
{
  "category": "<bug_report|feature_request|data_source|question|contribution|ignore>",
  "engage": <true|false>,
  "reason": "<one line why — for internal log>",
  "response": "<markdown response text, or empty string if engage=false>",
  "labels": ["<label-name>", ...]
}

Valid label names (only include if clearly applicable):
bug, enhancement, data-source, good first issue, help wanted, question, ui, platform:pi, platform:docker, platform:windows

Respond with raw JSON only — no code fences, no explanation outside the JSON.
"""

def _classify_and_respond(title: str, body: str, item_type: str, context: str = "") -> dict:
    """Call Claude to classify an interaction and generate a response."""
    if not ANTHROPIC_API_KEY:
        return {"category": "ignore", "engage": False, "reason": "no API key", "response": "", "labels": []}

    user_content = f"""
Item type: {item_type}
{f'Context: {context}' if context else ''}

Title: {title}

Body:
{body[:2000] if body else '(empty)'}
""".strip()

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = msg.content[0].text.strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [Community] JSON parse error: {e} — raw: {raw[:120]}")
        return {"category": "ignore", "engage": False, "reason": "parse error", "response": "", "labels": []}
    except Exception as e:
        print(f"  [Community] Claude error: {e}")
        return {"category": "ignore", "engage": False, "reason": str(e), "response": "", "labels": []}


# ── Per-item handlers ─────────────────────────────────────────────────────────

def _handle_issue(issue: dict, budget: list) -> bool:
    """Returns True if a response was posted."""
    number = issue["number"]
    item_id = str(number)
    if _already_handled("issue", item_id):
        return False

    title = issue.get("title", "")
    body  = issue.get("body") or ""
    user  = issue.get("user", {}).get("login", "someone")

    print(f"  Issue #{number}: {title[:60]}")
    result = _classify_and_respond(title, body, "GitHub Issue")
    category = result.get("category", "ignore")
    engage   = result.get("engage", False)

    if engage and result.get("response") and budget:
        ok = _post_issue_comment(number, result["response"])
        if ok:
            budget.pop()
            print(f"    → responded ({category})")

    labels = result.get("labels", [])
    if labels:
        _add_labels(number, labels)
        print(f"    → labeled: {labels}")

    action = "responded" if (engage and result.get("response")) else "ignored"
    _mark_handled("issue", item_id, action, category)
    return action == "responded"


def _handle_pr(pr: dict, budget: list) -> bool:
    number = pr["number"]
    item_id = str(number)
    if _already_handled("pr", item_id):
        return False

    title = pr.get("title", "")
    body  = pr.get("body") or ""
    user  = pr.get("user", {}).get("login", "contributor")
    branch = pr.get("head", {}).get("ref", "unknown")

    print(f"  PR #{number}: {title[:60]} (from {user})")
    result = _classify_and_respond(
        title, body, "Pull Request",
        context=f"Contributor: {user}, branch: {branch}"
    )
    engage = result.get("engage", False)

    if engage and result.get("response") and budget:
        ok = _post_issue_comment(number, result["response"])
        if ok:
            budget.pop()
            print(f"    → acknowledged PR ({result.get('category')})")

    action = "responded" if (engage and result.get("response")) else "ignored"
    _mark_handled("pr", item_id, action, result.get("category", ""))
    return action == "responded"


def _handle_discussion(disc: dict, budget: list) -> bool:
    node_id = disc.get("id", "")
    number  = disc.get("number", "")
    item_id = str(number)
    if _already_handled("discussion", item_id):
        return False

    title    = disc.get("title", "")
    body     = disc.get("body") or ""
    category = disc.get("category", {}).get("name", "")
    author   = (disc.get("author") or {}).get("login", "someone")

    print(f"  Discussion #{number} [{category}]: {title[:55]}")
    result = _classify_and_respond(
        title, body, f"GitHub Discussion ({category})",
        context=f"Category: {category}, Author: {author}"
    )
    engage = result.get("engage", False)

    if engage and result.get("response") and budget and node_id:
        ok = _post_discussion_comment(node_id, result["response"])
        if ok:
            budget.pop()
            print(f"    → responded to discussion ({result.get('category')})")

    action = "responded" if (engage and result.get("response")) else "ignored"
    _mark_handled("discussion", item_id, action, result.get("category", ""))
    return action == "responded"


# ── Main entry point ──────────────────────────────────────────────────────────

def run_community_cycle() -> dict:
    """
    Main community engagement cycle.
    Returns a summary dict for logging.
    """
    summary = {
        "issues_checked": 0, "discussions_checked": 0, "prs_checked": 0,
        "responses_posted": 0, "skipped": 0, "errors": [],
    }

    if not GITHUB_TOKEN:
        print("  [Community] GITHUB_TOKEN not set — skipping community check")
        summary["errors"].append("GITHUB_TOKEN not configured")
        return summary

    if not ANTHROPIC_API_KEY:
        print("  [Community] ANTHROPIC_API_KEY not set — skipping community check")
        summary["errors"].append("ANTHROPIC_API_KEY not configured")
        return summary

    _ensure_table()

    # Shared response budget — limits total posts this cycle
    budget = list(range(MAX_RESPONSES_PER_CYCLE))

    print(f"\n  Checking {GITHUB_REPO} community interactions...")

    # ── Issues ────────────────────────────────────────────────────────────────
    issues = _get_open_issues()
    summary["issues_checked"] = len(issues)
    for issue in issues:
        if not budget:
            break
        try:
            posted = _handle_issue(issue, budget)
            if posted:
                summary["responses_posted"] += 1
            else:
                summary["skipped"] += 1
            time.sleep(1.0)  # be polite to the API
        except Exception as e:
            summary["errors"].append(f"issue #{issue.get('number')}: {e}")

    # ── Discussions ───────────────────────────────────────────────────────────
    discussions = _get_discussions()
    summary["discussions_checked"] = len(discussions)
    for disc in discussions:
        if not budget:
            break
        try:
            posted = _handle_discussion(disc, budget)
            if posted:
                summary["responses_posted"] += 1
            else:
                summary["skipped"] += 1
            time.sleep(1.0)
        except Exception as e:
            summary["errors"].append(f"discussion #{disc.get('number')}: {e}")

    # ── Open PRs ──────────────────────────────────────────────────────────────
    prs = _get_open_prs()
    summary["prs_checked"] = len(prs)
    for pr in prs:
        if not budget:
            break
        try:
            posted = _handle_pr(pr, budget)
            if posted:
                summary["responses_posted"] += 1
            else:
                summary["skipped"] += 1
            time.sleep(1.0)
        except Exception as e:
            summary["errors"].append(f"pr #{pr.get('number')}: {e}")

    print(f"\n  Community cycle done: "
          f"{summary['responses_posted']} responded, "
          f"{summary['skipped']} skipped, "
          f"{len(summary['errors'])} errors")
    return summary


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    # Re-read after load_dotenv
    GITHUB_TOKEN      = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPO       = os.getenv("GITHUB_REPO", "essentialbit/fredai")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    run_community_cycle()
