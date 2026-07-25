"""Pre-flight check for a new badge/feature's proposed name against existing
concept names in the codebase (routes, _macro_cache keys, accessor functions,
module filenames).

Closes a real recurring bug class: two independently-implemented features
picking the same human-readable concept ("credit spread" -> PR #485 crashed
`main` via a duplicate `/api/credit-spread` route + `api_credit_spread`
function + `_macro_cache["CREDIT_SPREAD"]` key; "filings" -> filing_intel.py's
route had to be renamed off `/api/filings/<ticker>`, already taken by
sec_8k_client.py). Jaccard-dedup on `feature_backlog` proposal text (see
memory_store._find_similar_proposal) does not catch this -- it only guards
proposal wording, not the route/function/cache-key names chosen later at
implementation time.

Usage:
    PYTHONPATH=. python3 scripts/check_badge_name_collision.py "credit spread" [--threshold 0.3]
"""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_STOPWORDS = {
    "api", "get", "the", "a", "an", "of", "for", "and", "or", "index",
    "client", "data", "badge", "signal", "score", "rate",
}


def _tokenize(name: str) -> set:
    words = re.split(r"[^a-zA-Z0-9]+", name)
    tokens = set()
    for w in words:
        w = w.lower()
        if len(w) < 3 or w in _STOPWORDS:
            continue
        tokens.add(w)
    return tokens


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def collect_existing_names() -> dict:
    main_text = (ROOT / "main.py").read_text()

    routes = sorted(set(re.findall(r'@app\.route\("([^"]+)"', main_text)))

    cache_keys = sorted(set(
        re.findall(r'_macro_cache\["([A-Za-z_0-9]+)"\]', main_text)
        + re.findall(r'_macro_cache = \{\*\*_macro_cache, "([A-Za-z_0-9]+)"', main_text)
    ))

    functions = sorted(set(re.findall(r"^def (api_[a-zA-Z0-9_]+|get_[a-zA-Z0-9_]+)\(", main_text, re.MULTILINE)))

    files = []
    for py in ROOT.glob("*.py"):
        if py.name == "main.py":
            continue
        files.append(py.stem)
        try:
            text = py.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        functions.extend(re.findall(r"^def (get_[a-zA-Z0-9_]+)\(", text, re.MULTILINE))

    return {
        "route": routes,
        "cache_key": cache_keys,
        "function": sorted(set(functions)),
        "file": sorted(set(files)),
    }


def check_collision(concept: str, threshold: float = 0.3) -> list:
    concept_tokens = _tokenize(concept)
    existing = collect_existing_names()

    hits = []
    for kind, names in existing.items():
        for name in names:
            score = _jaccard(concept_tokens, _tokenize(name))
            if score >= threshold:
                hits.append({"kind": kind, "name": name, "score": round(score, 3)})

    hits.sort(key=lambda h: -h["score"])
    return hits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("concept", help='candidate name/concept, e.g. "credit spread" or "options max pain"')
    parser.add_argument("--threshold", type=float, default=0.3)
    args = parser.parse_args()

    hits = check_collision(args.concept, args.threshold)
    if not hits:
        print(f"No collision >= {args.threshold} found for {args.concept!r}. Looks safe to use.")
        return

    print(f"Possible collisions for {args.concept!r} (threshold {args.threshold}):")
    for h in hits:
        print(f"  [{h['score']:.3f}] {h['kind']:10s} {h['name']}")


if __name__ == "__main__":
    main()
