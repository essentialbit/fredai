"""Pre-flight check for a draft proposal's title/category/description text
against risk_rules.classify_risk() before calling insert_feature_proposal().

Closes a recurring manual-review gap documented in project memory: eyeballing
draft text for HIGH_RISK_KEYWORDS ("hit twice" -- keywords like "session" or
"token" can appear in an innocuous sentence and get missed by a quick read).
This runs the exact same classify_risk() the rest of the pipeline uses, so a
"low"/"medium" result here is guaranteed to match what github_sync.py would
compute at sync time.

Usage:
    PYTHONPATH=. python3 scripts/check_proposal_risk.py --category "l2_liquidity" \\
        --description "$(cat draft.txt)"

    echo "some draft text" | PYTHONPATH=. python3 scripts/check_proposal_risk.py \\
        --category "l2_liquidity"

Exits 0 for low/medium, 1 for high (so it can gate a script without parsing
stdout).
"""
import argparse
import sys

from risk_rules import HIGH_RISK_KEYWORDS, classify_risk


def check(category: str, description: str) -> dict:
    text = f"{category} {description}".lower()
    matched = [kw for kw in HIGH_RISK_KEYWORDS if kw in text]
    tier = classify_risk(category=category, description=description)
    return {"tier": tier, "matched_keywords": matched}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="")
    parser.add_argument("--description", default=None)
    args = parser.parse_args()

    description = args.description
    if description is None:
        description = sys.stdin.read()

    result = check(args.category, description)
    print(result)
    sys.exit(1 if result["tier"] == "high" else 0)
