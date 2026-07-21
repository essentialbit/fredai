#!/usr/bin/env python3
"""
Structural guard against a recurring bug class: Werkzeug's
`request.args.get(key, default, type=T)` only applies `type` conversion when
the query param is present -- an absent param passes the string `default`
through untouched, so e.g. `type=int` with a string default crashes the
first time a route is hit with no query params.

Hit and fixed independently 3+ times (PRs #157, #168) because it only
surfaces at runtime, on a code path that isn't exercised by every call.
This script fails CI structurally instead of relying on live-testing luck.
"""
import re
import sys
from pathlib import Path

PATTERN = re.compile(r'request\.args\.get\([^)]*?,\s*"[0-9]+(?:\.[0-9]+)?"\s*,\s*type\s*=')
SKIP_DIRS = {"venv", ".venv", "node_modules", "__pycache__", ".git"}


def offending_files():
    root = Path(__file__).resolve().parent.parent
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS or part.startswith(".claude") for part in path.parts):
            continue
        text = path.read_text(errors="ignore")
        for i, line in enumerate(text.splitlines(), start=1):
            if PATTERN.search(line):
                yield path.relative_to(root), i, line.strip()


def main():
    hits = list(offending_files())
    if hits:
        print("Found request.args.get(...) calls with a quoted numeric default alongside type=:")
        for rel_path, lineno, line in hits:
            print(f"  {rel_path}:{lineno}: {line}")
        print("\nFix: use an unquoted numeric default, e.g. request.args.get(\"days\", 90, type=int)")
        sys.exit(1)
    print("OK: no quoted-numeric-default + type= request.args.get(...) calls found")


if __name__ == "__main__":
    main()
