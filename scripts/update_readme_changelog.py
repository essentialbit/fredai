#!/usr/bin/env python3
"""
update_readme_changelog.py — called by the GitHub Actions release job.

Reads recent releases from GitHub and rewrites the
<!-- CHANGELOG_START --> ... <!-- CHANGELOG_END --> block in README.md.

Usage:
    python3 scripts/update_readme_changelog.py

Environment:
    GITHUB_TOKEN   — Actions default token or PAT with contents:read
    GITHUB_REPO    — e.g. essentialbit/fredai
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

REPO     = os.getenv("GITHUB_REPO", "essentialbit/fredai")
TOKEN    = os.getenv("GITHUB_TOKEN", "")
README   = Path(__file__).parents[1] / "README.md"
MAX_RELEASES = 5

_START = "<!-- CHANGELOG_START -->"
_END   = "<!-- CHANGELOG_END -->"


def _gh_get(path: str) -> list | dict | None:
    headers = {"Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        r = requests.get(
            f"https://api.github.com/{path.lstrip('/')}",
            headers=headers, timeout=20
        )
        if r.status_code == 200:
            return r.json()
        print(f"[readme] GH {path} → {r.status_code}")
    except Exception as e:
        print(f"[readme] GH error: {e}")
    return None


def build_changelog_block() -> str:
    releases = _gh_get(f"repos/{REPO}/releases?per_page={MAX_RELEASES}") or []

    lines = [
        _START,
        "## What's New",
        "",
        f"See the full list at [github.com/{REPO}/releases](https://github.com/{REPO}/releases).",
        "",
    ]

    for rel in releases:
        tag   = rel.get("tag_name", "")
        name  = rel.get("name", tag)
        body  = (rel.get("body") or "").strip()

        # Extract bullet points from the body (lines starting with - or *)
        bullets = [
            line.strip() for line in body.splitlines()
            if re.match(r"^[-*]\s", line.strip())
        ][:6]  # cap at 6 bullets per release

        lines.append(f"### {name}")
        if bullets:
            lines.extend(bullets)
        else:
            lines.append(f"- See [release notes](https://github.com/{REPO}/releases/tag/{tag})")
        lines.append("")

    lines.append(_END)
    return "\n".join(lines)


def update_readme(new_block: str) -> bool:
    text = README.read_text()
    start_idx = text.find(_START)
    end_idx   = text.find(_END)

    if start_idx == -1 or end_idx == -1:
        print("[readme] Markers not found in README — skipping update")
        return False

    updated = text[:start_idx] + new_block + text[end_idx + len(_END):]
    if updated == text:
        print("[readme] No changes needed")
        return False

    README.write_text(updated)
    print(f"[readme] Updated changelog block ({len(releases)} releases)")
    return True


if __name__ == "__main__":
    block = build_changelog_block()
    releases = _gh_get(f"repos/{REPO}/releases?per_page={MAX_RELEASES}") or []
    changed = update_readme(block)
    sys.exit(0 if changed is not None else 1)
