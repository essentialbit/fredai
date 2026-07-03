"""Named Entity Recognition ticker linking -- catches company-name mentions
("Apple reported strong earnings") that cashtag/raw-ticker regex matching
("$AAPL", "AAPL") misses entirely. News prose especially rarely uses cashtags.

Complements, doesn't replace, the existing regex-based extraction in
twitter_client.py/news_client.py: those run first (cheap, no model inference),
this only runs as a fallback when they find nothing.
"""
import re

import psutil

from config import DISPLAY_SYMBOLS

HAS_SPACY = False
_nlp = None

# Hardware-check lite mode (Raspberry Pi Zero / 512MB RAM) -- same threshold
# and pattern as finbert_sentiment.py, for the same reason: real NLP model
# inference isn't viable on that class of device.
RAM_GB = psutil.virtual_memory().total / 1e9
LITE_MODE = RAM_GB < 1.0

if not LITE_MODE:
    try:
        import spacy
        HAS_SPACY = True
    except ImportError:
        HAS_SPACY = False

_SUFFIX_RE = re.compile(r"\s+(Inc\.?|Corp\.?|Corporation|Ltd\.?|Group|Co\.?)$", re.IGNORECASE)

# Reverse-lookup built from the existing DISPLAY_SYMBOLS map -- reuses data
# already maintained for quote display rather than a new company database.
# Only real, sufficiently-distinctive company names are useful match targets;
# generic labels like "S&P 500 ETF" or "EUR/USD" would never appear as an
# NER ORG entity anyway, so leaving them in the map is harmless.
_NAME_TO_TICKER = {name.lower(): ticker for ticker, name in DISPLAY_SYMBOLS.items()}


def _load_model():
    global _nlp
    if _nlp is not None:
        return _nlp
    if not HAS_SPACY:
        return None
    try:
        _nlp = spacy.load("en_core_web_sm")
    except OSError:
        # spacy installed but `python -m spacy download en_core_web_sm` never ran
        print("[NER] en_core_web_sm model not downloaded -- NER ticker linking disabled")
        _nlp = False
    return _nlp or None


def extract_and_link_tickers(text: str) -> list[str]:
    """Return tickers for company names mentioned by name in text (via NER),
    not already reachable through cashtag/raw-ticker matching. Returns []
    if spaCy/the model isn't available (lite mode, or not yet downloaded)."""
    nlp = _load_model()
    if nlp is None or not text:
        return []

    try:
        doc = nlp(text)
    except Exception as e:
        print(f"[NER] Processing error: {e}")
        return []

    found = set()
    for ent in doc.ents:
        if ent.label_ != "ORG":
            continue
        name = _SUFFIX_RE.sub("", ent.text).strip().lower()
        ticker = _NAME_TO_TICKER.get(name)
        if ticker:
            found.add(ticker)

    return sorted(found)
