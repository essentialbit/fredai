"""NY Fed Global Supply Chain Pressure Index (GSCPI) -- composite supply-chain
stress signal (FSI L2/L5).

GSCPI is a factor-model composite (transportation costs, delivery times,
backlogs, PMI supply-chain components across US/China/EU/Japan/Korea/Taiwan/
UK) published monthly by the New York Fed. Distinct from the already-shipped
sector rotation / dark pool / short interest signals -- this is the first
global-supply-chain-stress angle. The series is not on FRED at all (confirmed
via direct probe: GSCPI/NYFEDGSCPI/FRBNYGSCPI all 404 on fredgraph.csv) --
NY Fed only publishes it via its own site as an .xls download.

The index is itself already a standardized z-score (designed mean 0, std 1
over its 1998-present history), so unlike most macro badges here the raw
`latest` value is already interpretable on its own; `_trend()` still adds a
rolling 12-month z-score/direction read for consistency with every other
badge on the macro strip.
"""
import io
import statistics
import time

import requests

_GSCPI_URL = "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xls"
_CACHE_TTL_S = 3600  # monthly-updated series, 1h TTL matches other FRED-cadence badges
_cache: dict = {"computed_at": 0.0, "data": None}


def _trend(series: list[float]) -> dict | None:
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
    return {"latest": round(latest, 4), "mean": round(mean, 4), "z_score": round(z, 2), "direction": direction}


def compute_gscpi() -> dict | None:
    """{"latest": float, "trend_12mo": {...}, "regime"} or None on fetch failure.

    `regime` is "elevated_stress"/"easing"/"neutral", derived from whether
    the index's own absolute level plus its 12mo trend direction agree the
    index is standardized (0 = historical average, positive = more stress)."""
    resp = requests.get(_GSCPI_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code != 200:
        return None

    import pandas as pd  # local import: only this module needs the xlrd engine path

    xls = pd.ExcelFile(io.BytesIO(resp.content))
    df = xls.parse(xls.sheet_names[0]).dropna()
    series = [float(v) for v in df["GSCPI"].tolist()]
    if len(series) < 13:
        return None

    trend_12mo = _trend(series[-13:])
    if trend_12mo is None:
        return None

    latest = round(series[-1], 4)
    if latest > 0.5:
        regime = "elevated_stress"
    elif latest < -0.5:
        regime = "easing"
    else:
        regime = "neutral"

    return {"latest": latest, "trend_12mo": trend_12mo, "regime": regime}


def get_gscpi(force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["computed_at"] > _CACHE_TTL_S:
        data = compute_gscpi()
        if data:
            _cache["data"] = data
            _cache["computed_at"] = now
    return _cache["data"]
