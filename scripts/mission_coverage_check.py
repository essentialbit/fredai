#!/usr/bin/env python3
"""
Flags MISSION.md checklist items that read as open/next-step but whose
capability already exists in the codebase -- the manual version of this
check (grep each line individually) has been done by hand every R&D dive
and has twice found MISSION.md sections stale by weeks (L2 priority queue,
Q3 2026 next steps both fully shipped while still listed as open).

Heuristic only: keyword-matches item text against .py filenames and
main.py identifiers/strings. A "LIKELY SHIPPED" verdict still needs a
human/agent glance at the matched file before treating the item as done --
this narrows the manual-grep list, it doesn't replace judgment.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "using", "via", "over",
    "that", "this", "than", "then", "your", "such", "each", "next", "not",
    "are", "was", "were", "has", "have", "will", "can", "all", "any", "who",
}

# Sections known (or suspected) to drift stale -- checked/unchecked boxes
# elsewhere in the doc are assumed current and skipped.
SECTION_HEADERS = (
    "### L2 Priority queue",
    "### 4. Next Implementation Steps",
)

ITEM_RE = re.compile(r"^\d+\.\s+(.*)$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
PAREN_RE = re.compile(r"\(([^)]+)\)")
BACKTICK_RE = re.compile(r"`([^`]+)`")


def extract_section_items(text):
    lines = text.splitlines()
    items = []
    current_header = None
    capturing = False
    for line in lines:
        if line.startswith("#"):
            capturing = any(line.startswith(h) for h in SECTION_HEADERS)
            current_header = line.strip()
            continue
        if capturing:
            m = ITEM_RE.match(line.strip())
            if m:
                items.append((current_header, m.group(1).strip()))
    return items


def keywords_for(item_text):
    hints = set()
    for m in BACKTICK_RE.finditer(item_text):
        hints.add(m.group(1).split("/")[-1].split(".")[0])
    for m in PAREN_RE.finditer(item_text):
        for w in re.split(r"[\s,]+", m.group(1)):
            w = w.strip("()").lower()
            if len(w) >= 4:
                hints.add(w)
    stripped = BOLD_RE.sub(r"\1", item_text)
    stripped = PAREN_RE.sub("", stripped)
    stripped = BACKTICK_RE.sub("", stripped)
    for w in re.split(r"[^A-Za-z0-9]+", stripped):
        w = w.lower()
        if len(w) >= 5 and w not in STOPWORDS:
            hints.add(w)
    return hints


def codebase_signal(keywords):
    py_files = [
        p for p in ROOT.rglob("*.py")
        if "venv" not in p.parts and ".claude" not in p.parts
        and "__pycache__" not in p.parts
    ]
    filenames = {p.stem.lower(): p for p in py_files}
    main_text = (ROOT / "main.py").read_text(errors="ignore").lower()

    matches = []
    for kw in keywords:
        for stem, path in filenames.items():
            if kw in stem or stem in kw:
                matches.append(f"file:{path.relative_to(ROOT)}")
        if kw in main_text:
            matches.append(f"main.py:{kw}")
    return sorted(set(matches))


def main():
    mission = ROOT / "MISSION.md"
    text = mission.read_text(errors="ignore")
    items = extract_section_items(text)

    if not items:
        print("No numbered items found under tracked sections -- check SECTION_HEADERS still match MISSION.md's headings.")
        return 1

    for header, item in items:
        kws = keywords_for(item)
        matches = codebase_signal(kws)
        verdict = "LIKELY SHIPPED" if matches else "open?"
        print(f"[{verdict}] {header}")
        print(f"    item: {item}")
        if matches:
            print(f"    evidence: {', '.join(matches[:6])}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
