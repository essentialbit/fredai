"""Fuzz coverage for agent._needs_disclaimer() -- the chat-path disclaimer
gate. Unlike the briefing path (agent.py, "Summaries always discuss market
assets" -- unconditional), chat only appends DISCLAIMER_FOOTER when this
heuristic decides the exchange actually touched an asset or market action.
This suite exists to fuzz that heuristic against realistic phrasing an LLM
chat response is likely to produce, not just the obvious "$NVDA buy signal"
case the original keyword list was clearly built around.

Run: python3 -m pytest tests/test_disclaimer_gating.py -v
     (or plain: python3 tests/test_disclaimer_gating.py)
"""
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "test")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from agent import _needs_disclaimer  # noqa: E402


# ── Cases that MUST trigger the disclaimer ─────────────────────────────────
# (user_message, response, description). Each pair is a realistic chat
# exchange where the response discusses a specific asset or market action,
# even when the literal original keyword list (buy/sell/hold/invest/position/
# trade/portfolio/stock/crypto/market/signal/$TICKER) never appears.
POSITIVE_CASES = [
    (
        "what do you think about that chipmaker everyone's talking about",
        "NVIDIA has seen huge demand for its H100 chips, with shares climbing amid AI hype.",
        "indirect company reference resolved via response naming the company",
    ),
    (
        "NVDA to the moon?",
        "NVDA has had a strong run this quarter, up 12% on AI demand.",
        "bare ticker slang (no $ prefix) in both user message and response",
    ),
    (
        "Which is better, Apple or Microsoft?",
        "Apple has stronger services growth while Microsoft leads in cloud infrastructure.",
        "multi-asset comparison, company names only, no ticker or trading verb",
    ),
    (
        "what about it now",
        "Given your existing NVDA exposure, adding more here would increase concentration risk.",
        "follow-up in an ongoing thread that doesn't restate context, only 'exposure'",
    ),
    (
        "aapl vs tsla, which one",
        "Apple has steadier earnings while Tesla is more volatile.",
        "lowercase bare ticker slang for two assets at once",
    ),
    (
        "thoughts on the yellow metal",
        "Gold has been rallying as real yields fall.",
        "indirect commodity reference resolved via response naming the asset + 'rally'",
    ),
    (
        "btc or eth right now",
        "Bitcoin has outperformed Ethereum this month on ETF inflows.",
        "crypto slang resolved via response spelling out full names",
    ),
    (
        "how's my bag doing",
        "Your NVDA shares are up 4% today.",
        "trader slang ('bag') resolved via 'shares' + bare ticker",
    ),
    (
        "what's happening with the s&p",
        "The S&P 500 pulled back slightly amid rate jitters.",
        "index reference via 's&p', no ticker/company keyword involved",
    ),
    (
        "should I go long here",
        "Given the momentum, adding exposure could make sense but comes with downside risk.",
        "trading question answered without any original-list keyword, only 'exposure'",
    ),
    (
        "is now a good entry",
        "Given the pullback, this could be an attractive entry point for accumulation.",
        "entry-point phrasing with no ticker/company named at all",
    ),
    (
        "whats the vibe on the megacap tech names",
        "Big tech has cooled off after the recent rally in growth names.",
        "sector-level question, resolved only via 'rally'",
    ),
    (
        "just curious",
        "Meta's ad revenue beat expectations and shares jumped after hours.",
        "small-talk-shaped user message, asset content lives entirely in the response",
    ),
    (
        "what's driving CSL.AX today",
        "CSL has strong margins that make it a healthcare bellwether on the ASX.",
        "non-US (ASX) ticker slang, tests case-insensitive / non-default-market coverage",
    ),
]

# ── Cases that must NOT trigger the disclaimer ─────────────────────────────
# Genuine small talk with no asset content in either message. Guards against
# the fix over-correcting into disclaimer-spam on every reply.
NEGATIVE_CASES = [
    ("how's the weather today", "It's sunny where I am, though I don't have live weather data.",
     "pure small talk"),
    ("tell me a joke", "Why did the chicken cross the road? To get away from the rooster next door.",
     "unrelated joke, no market/company vocabulary"),
    ("what's your name", "I'm Fred, your assistant.", "identity question"),
    ("thanks!", "Anytime, happy to help.", "gratitude exchange"),
    ("good morning fred", "Good morning! Ready when you are.", "greeting"),
    ("golden retriever puppies are the best", "Agreed, they're wonderful dogs.",
     "regression guard: 'gold' must not fire on 'golden' via the asset-name matcher"),
    ("what's 2+2", "That's 4.", "arbitrary non-financial question"),
]

# Known, honestly-documented residual gap: a ticker/company not in FredAI's
# curated known-asset universe (WATCHLIST + AI Universe sectors + display
# names) still won't be caught by bare-mention detection. Closing this fully
# would need a market-wide ticker database or NER (signal_processor.py's
# extract_and_link_tickers() does this for signal ingestion via spaCy, but
# that's a heavyweight, model-load-dependent path -- wrong tradeoff for a
# per-chat-turn synchronous gate). Documented here rather than silently
# dropped so the gap stays visible, not fixed via keyword-soup guessing.
KNOWN_LIMITATION_CASES = [
    ("is gme still a thing", "GameStop remains a meme favorite but fundamentals haven't caught up.",
     "ticker/company outside the curated known-asset universe"),
]


def test_positive_cases_trigger_disclaimer():
    failures = []
    for user_msg, response, desc in POSITIVE_CASES:
        if not _needs_disclaimer(user_msg, response):
            failures.append(f"{desc!r}: user={user_msg!r} response={response!r}")
    assert not failures, "False negatives found:\n" + "\n".join(failures)


def test_negative_cases_do_not_trigger_disclaimer():
    failures = []
    for user_msg, response, desc in NEGATIVE_CASES:
        if _needs_disclaimer(user_msg, response):
            failures.append(f"{desc!r}: user={user_msg!r} response={response!r}")
    assert not failures, "False positives found:\n" + "\n".join(failures)


def test_known_limitation_cases_documented_not_silently_fixed():
    """Asserts CURRENT (still-gapped) behavior for tickers/companies outside
    FredAI's curated known-asset universe. If this ever flips to True, it's
    because someone widened the universe (e.g. added GME to config.WATCHLIST)
    -- update this test to move the case into POSITIVE_CASES at that point."""
    for user_msg, response, desc in KNOWN_LIMITATION_CASES:
        assert _needs_disclaimer(user_msg, response) is False, (
            f"{desc!r} now passes -- move it into POSITIVE_CASES: "
            f"user={user_msg!r} response={response!r}"
        )


if __name__ == "__main__":
    test_positive_cases_trigger_disclaimer()
    print(f"PASS: {len(POSITIVE_CASES)} positive (should-trigger) cases")
    test_negative_cases_do_not_trigger_disclaimer()
    print(f"PASS: {len(NEGATIVE_CASES)} negative (should-not-trigger) cases")
    test_known_limitation_cases_documented_not_silently_fixed()
    print(f"PASS: {len(KNOWN_LIMITATION_CASES)} known-limitation case(s) documented")
    print("\nAll disclaimer-gating fuzz tests passed.")
