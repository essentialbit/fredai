"""2s10s Treasury yield curve spread -- derived from the macro snapshot's
already-fetched 10Y/2Y yields (nasdaq_client.get_macro_snapshot()). No new
external calls or dependencies.
"""

YIELD_10Y_KEY = "US_TREASURY_YIELD_10Y"
YIELD_2Y_KEY = "US_TREASURY_YIELD_2Y"


def compute_yield_curve_spread(macro_snapshot: dict) -> dict | None:
    """Given the macro snapshot dict from get_macro_snapshot(), derive the
    2s10s spread (10Y yield minus 2Y yield) and inversion flag. Returns None
    if either yield isn't present in the snapshot yet (e.g. Nasdaq API key
    missing or first-fetch not yet completed)."""
    y10 = macro_snapshot.get(YIELD_10Y_KEY)
    y2 = macro_snapshot.get(YIELD_2Y_KEY)
    if not y10 or not y2 or y10.get("value") is None or y2.get("value") is None:
        return None
    try:
        v10 = float(y10["value"])
        v2 = float(y2["value"])
    except (TypeError, ValueError):
        return None
    spread = round(v10 - v2, 4)
    return {
        "yield_10y": v10,
        "yield_2y": v2,
        "spread_2s10s": spread,
        "inverted": spread < 0,
    }
