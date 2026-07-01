"""
FredAI Collaboration Board — Risk Classification
==================================================
Crude, editable rules for gating which agent-proposed PRs are even
eligible for auto-merge once Phase 1's consensus scoring lands. Anything
touching auth, payments, secrets, or the core data model always requires
a human, regardless of consensus score — this is intentionally simple
(keyword/path matching, no ML) so it stays auditable and easy to extend.
"""

HIGH_RISK_KEYWORDS = (
    "auth", "login", "password", "session", "oauth", "token", "secret",
    "credential", "payment", "billing", "encrypt", "decrypt", "permission",
)

HIGH_RISK_FILES = (
    "memory_store.py",   # schema changes ripple everywhere
    "config.py",          # credential/env wiring
    "crypto_utils.py",
    "main.py",            # routes, auth decorators, session config
    ".github/workflows",  # CI/CD itself
)


def classify_risk(category: str, description: str = "", estimated_hours: float = 0,
                   files_changed: list[str] | None = None) -> str:
    """Return 'high', 'medium', or 'low'. High-risk proposals/PRs are never
    eligible for auto-merge no matter the consensus score; medium requires
    a higher consensus threshold; low is the only tier where the default
    threshold applies."""
    text = f"{category} {description}".lower()
    if any(kw in text for kw in HIGH_RISK_KEYWORDS):
        return "high"

    for f in (files_changed or []):
        if any(hf in f for hf in HIGH_RISK_FILES):
            return "high"

    if estimated_hours > 8:
        return "medium"

    return "low"
