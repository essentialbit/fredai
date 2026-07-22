"""Bitcoin on-chain network health -- hash rate, active addresses, tx volume.

MISSION.md L2 checklist item ("Bitcoin on-chain metrics"). Glassnode gates
almost everything behind a paid key; blockchain.info exposes the equivalent
core network-health series with no key and no rate-limit gate at all. Gives
Fred a network-fundamentals read on BTC that's uncorrelated with the existing
X/news/Reddit sentiment pipeline.

Two speculative market-value-ratio chart slugs were probed and 404'd -- out
of scope for this first cut, only the three confirmed series are used.
"""
import statistics

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FredAI/1.0)"}
_TIMEOUT = 15

_SERIES = {
    "hash_rate": "https://api.blockchain.info/charts/hash-rate?timespan=60days&format=json",
    "active_addresses": "https://api.blockchain.info/charts/n-unique-addresses?timespan=60days&format=json",
}
_TX_COUNT_URL = "https://blockchain.info/q/24hrtransactioncount"


def _fetch_chart_series(url: str) -> list[float]:
    r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    values = r.json().get("values", [])
    return [v["y"] for v in values if v.get("y") is not None]


def _trend(series: list[float]) -> dict | None:
    """Latest value + rolling z-score/trend direction against the trailing
    window (excluding the latest point, so the z-score isn't self-referential)."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "rising"
    elif z < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"latest": latest, "mean": mean, "z_score": round(z, 2), "direction": direction}


def fetch_onchain_snapshot() -> dict | None:
    """{"hash_rate": {...}, "active_addresses": {...}, "tx_count_24h": int}
    or None if every series failed (network down / API change) -- caller
    should treat that as "no data", not fabricate a reading."""
    result = {}
    for name, url in _SERIES.items():
        try:
            series = _fetch_chart_series(url)
            trend = _trend(series)
            if trend:
                result[name] = trend
        except Exception as e:
            print(f"[BitcoinOnchain] {name} fetch failed: {e}")

    try:
        r = requests.get(_TX_COUNT_URL, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        result["tx_count_24h"] = int(r.text.strip())
    except Exception as e:
        print(f"[BitcoinOnchain] tx count fetch failed: {e}")

    return result or None
