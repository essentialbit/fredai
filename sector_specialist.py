"""Sector Specialist Agents (FSI L5) -- persona-framed reasoning lens per GICS sector.

Distinct from the generic per-asset Bull/Bear debate (any ticker, no sector framing) and
from the sector-rotation price badge (pure price data, no reasoning): this gives Fred a
persistent, narrower reasoning lens per sector, reusing the same agent.py provider path
every other AI feature already goes through.
"""

from agent import _provider

PERSONAS = {
    "tech": (
        "You are Fred's Technology & Communications sector specialist. You reason about "
        "tech/communications names through AI capex cycles, semiconductor supply, cloud/software "
        "growth, open-source engineering velocity, and hiring-signal momentum -- weigh those over "
        "generic macro noise. State data, then a short thesis, then the key risk. Under 150 words."
    ),
    "energy": (
        "You are Fred's Energy & Materials sector specialist. You reason about energy, utilities, "
        "and materials names through commodity price cycles, the dollar index, inflation "
        "expectations, and supply-chain stress signals -- weigh those over software-style growth "
        "narratives. State data, then a short thesis, then the key risk. Under 150 words."
    ),
    "financials": (
        "You are Fred's Financials & Real Estate sector specialist. You reason about banks, "
        "insurers, asset managers, and REITs through credit spreads, the yield curve, Fed policy, "
        "and financial-conditions indices -- weigh those over top-line growth stories. State data, "
        "then a short thesis, then the key risk. Under 150 words."
    ),
    "macro": (
        "You are Fred's Macro generalist specialist, covering sectors without a narrower lens "
        "(health care, consumer, industrials) and any unmapped ticker. You reason through the "
        "broad macro regime -- growth, inflation, consumer strength, and policy -- rather than a "
        "single sector-specific driver. State data, then a short thesis, then the key risk. "
        "Under 150 words."
    ),
}

SECTOR_TO_PERSONA = {
    "Information Technology": "tech",
    "Communication Services": "tech",
    "Energy": "energy",
    "Utilities": "energy",
    "Materials": "energy",
    "Financials": "financials",
    "Real Estate": "financials",
    "Health Care": "macro",
    "Consumer Discretionary": "macro",
    "Consumer Staples": "macro",
    "Industrials": "macro",
}

# Hand-curated ticker -> GICS sector map, well-known large-cap membership.
# Deliberately a fresh static map, not imported from the still-unmerged
# sector_rotation.py (#159/PR #161) -- matches the standing pattern of not
# depending on unmerged sibling branches.
SECTOR_MAP = {
    # Information Technology
    "AAPL": "Information Technology", "MSFT": "Information Technology",
    "NVDA": "Information Technology", "AVGO": "Information Technology",
    "ORCL": "Information Technology", "CSCO": "Information Technology",
    "ADBE": "Information Technology", "CRM": "Information Technology",
    "AMD": "Information Technology", "INTC": "Information Technology",
    "QCOM": "Information Technology", "IBM": "Information Technology",
    # Communication Services
    "GOOGL": "Communication Services", "GOOG": "Communication Services",
    "META": "Communication Services", "NFLX": "Communication Services",
    "DIS": "Communication Services", "CMCSA": "Communication Services",
    "TMUS": "Communication Services", "VZ": "Communication Services",
    "T": "Communication Services",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy",
    "EOG": "Energy", "MPC": "Energy", "PSX": "Energy", "OXY": "Energy",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
    "D": "Utilities", "AEP": "Utilities", "EXC": "Utilities",
    # Materials
    "LIN": "Materials", "APD": "Materials", "SHW": "Materials",
    "FCX": "Materials", "NEM": "Materials", "ECL": "Materials",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials",
    "GS": "Financials", "MS": "Financials", "C": "Financials",
    "BLK": "Financials", "SCHW": "Financials", "AXP": "Financials",
    "V": "Financials", "MA": "Financials",
    # Real Estate
    "PLD": "Real Estate", "AMT": "Real Estate", "EQIX": "Real Estate",
    "SPG": "Real Estate", "PSA": "Real Estate", "O": "Real Estate",
    # Health Care
    "UNH": "Health Care", "JNJ": "Health Care", "LLY": "Health Care",
    "PFE": "Health Care", "ABBV": "Health Care", "MRK": "Health Care",
    "TMO": "Health Care", "ABT": "Health Care", "DHR": "Health Care",
    "BMY": "Health Care",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "SBUX": "Consumer Discretionary",
    "LOW": "Consumer Discretionary", "BKNG": "Consumer Discretionary",
    "TGT": "Consumer Discretionary",
    # Consumer Staples
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "WMT": "Consumer Staples", "COST": "Consumer Staples", "PM": "Consumer Staples",
    "MO": "Consumer Staples", "CL": "Consumer Staples",
    # Industrials
    "BA": "Industrials", "CAT": "Industrials", "HON": "Industrials",
    "UPS": "Industrials", "GE": "Industrials", "LMT": "Industrials",
    "RTX": "Industrials", "UNP": "Industrials", "DE": "Industrials",
}


def get_sector_take(ticker: str, context_block: str) -> dict:
    """Return one sector-specialist's paragraph take on `ticker`.

    Falls back to the Macro persona for any ticker not in SECTOR_MAP.
    """
    ticker = (ticker or "").upper().strip()
    sector = SECTOR_MAP.get(ticker)
    persona_key = SECTOR_TO_PERSONA.get(sector, "macro")
    system = PERSONAS[persona_key]

    prompt = f"{context_block}\n\nGive your sector-specialist take on {ticker}."
    take = _provider.complete(
        messages=[{"role": "user", "content": prompt}],
        system=system,
        tier="chat",
        max_tokens=400,
    )

    return {
        "ticker": ticker,
        "sector": sector or "Unmapped",
        "specialist": persona_key,
        "take": take,
    }
