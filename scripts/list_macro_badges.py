"""Dump every wired macro badge (key + label) and the dashboard's rating->color
map, so a new-idea R&D pass can dedup-check concept names without hand-grepping
main.py/dashboard.html every cycle.

Usage: PYTHONPATH=. python3 scripts/list_macro_badges.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BADGE_BLOCK_RE = re.compile(
    r'_macro_cache = \{\*\*_macro_cache, "([A-Za-z_0-9]+)":\s*\{([^}]*)\}\}',
    re.DOTALL,
)
LABEL_RE = re.compile(r'"label":\s*"([^"]*)"')
FG_COLOR_RE = re.compile(r"const _FG_COLOR=\{([^}]*)\};")
FG_KEY_RE = re.compile(r"'([^']+)':")


def list_badges():
    text = (ROOT / "main.py").read_text()
    badges = []
    for match in BADGE_BLOCK_RE.finditer(text):
        key, body = match.group(1), match.group(2)
        label_match = LABEL_RE.search(body)
        badges.append((key, label_match.group(1) if label_match else ""))
    return sorted(set(badges))


def list_fg_colors():
    text = (ROOT / "templates" / "dashboard.html").read_text()
    match = FG_COLOR_RE.search(text)
    if not match:
        return []
    return sorted(set(FG_KEY_RE.findall(match.group(1))))


def main():
    badges = list_badges()
    print(f"# {len(badges)} macro badges wired in main.py\n")
    for key, label in badges:
        print(f"{key:<30} {label}")

    ratings = list_fg_colors()
    print(f"\n# {len(ratings)} rating strings colored in dashboard.html's _FG_COLOR\n")
    for r in ratings:
        print(f"  {r}")


if __name__ == "__main__":
    main()
