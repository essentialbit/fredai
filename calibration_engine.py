"""FredAI Calibration Engine (FSI L4)
=====================================
Turns each signal source's logged prediction into a probabilistic forecast
and measures how well-calibrated it actually is -- not just "was it right"
(backtesting_engine.py already answers that) but "when it said it was
confident, was it actually more often right?"

Builds directly on backtesting_engine.py's signal_outcomes rows (same
price_at_t0/4h/24h/72h checkpoints, same predicted-direction-vs-actual-move
definition of "correct" as memory_store.get_backtest_accuracy) -- this
module adds a probabilistic layer on top, it doesn't duplicate outcome
logging or re-fetch prices.

Computed once daily (job_calibration_refresh in main.py) at the 24h
checkpoint -- matches the checkpoint agent.py's _format_track_record()
already treats as Fred's primary trust signal, and keeps one row per
source (not one per checkpoint) matching the calibration_scores schema.
"""
from memory_store import get_outcome_rows_by_source, upsert_calibration_score, get_calibration_scores, get_calibration_weight

WINDOW_DAYS = 30
_CHECKPOINT = "24h"
_LOW_SAMPLE_THRESHOLD = 20
_WEIGHT_MIN, _WEIGHT_MAX = 0.2, 1.5

# Sources without a continuous signal_count/avg_sentiment magnitude
# (insider/short_interest/technical are hard binary calls in this codebase,
# not a graded strength -- see backtesting_engine.py's log_scan_outcomes)
# get a fixed, documented "moderate confidence" stated probability. There's
# no real magnitude in the data to derive a varying one from; fabricating
# precision the data doesn't have would violate the data-correctness
# standing rule (see fredai memory notes).
FIXED_CONFIDENCE = 0.65


def stated_probability(row: dict) -> float:
    """Map a logged signal_outcomes row to P(predicted_direction is
    correct) in [0.5, 1.0] -- avg_sentiment magnitude when available
    (VADER/FinBERT compound score, roughly -1..1: 0 is a coin flip, ±1 is
    maximum conviction), else FIXED_CONFIDENCE for deterministic sources."""
    sentiment = row.get("avg_sentiment")
    if sentiment is None:
        return FIXED_CONFIDENCE
    return min(1.0, 0.5 + abs(sentiment) * 0.5)


def _actual_correct(row: dict, checkpoint_col: str) -> bool | None:
    price_then = row.get(checkpoint_col)
    price_now = row.get("price_at_t0")
    if price_then is None or price_now is None:
        return None
    change = price_then - price_now
    actual_dir = "bullish" if change > 0 else ("bearish" if change < 0 else "neutral")
    return row["predicted_direction"] == actual_dir


def brier_score(rows: list[dict], checkpoint_col: str) -> dict | None:
    """Mean squared error between stated probability and realized {0,1}
    outcome -- lower is better. 0 = perfect. A forecaster who states 0.5
    every time (pure coin flip) scores 0.25 regardless of actual hit rate;
    that's the reference point reliability_weight treats as neutral."""
    scored = []
    for r in rows:
        correct = _actual_correct(r, checkpoint_col)
        if correct is None:
            continue
        p = stated_probability(r)
        outcome = 1.0 if correct else 0.0
        scored.append((p - outcome) ** 2)
    if not scored:
        return None
    return {"brier": round(sum(scored) / len(scored), 4), "sample_n": len(scored)}


def reliability_weight(brier: float | None, sample_n: int) -> tuple[float, bool]:
    """Map a Brier score to a [0.2, 1.5] multiplier, pivoting on brier=0.25
    (the score a maximally-uncertain p=0.5 forecaster gets against any real
    outcome mix -- the standard "no skill" reference point). Better than
    that amplifies linearly toward 1.5 at brier=0; worse dampens linearly
    toward 0.2 at brier=1.0 (the worst possible: confidently, consistently
    wrong -- exactly the anti-correlated case this is meant to catch).
    Sources with too few samples to trust are pinned to neutral (1.0) with
    a low_sample flag, never rewarded/penalized on noise."""
    if brier is None or sample_n < _LOW_SAMPLE_THRESHOLD:
        return 1.0, True
    if brier <= 0.25:
        weight = 1.0 + (0.25 - brier) / 0.25 * (_WEIGHT_MAX - 1.0)
    else:
        weight = 1.0 - (brier - 0.25) / 0.75 * (1.0 - _WEIGHT_MIN)
    return round(max(_WEIGHT_MIN, min(_WEIGHT_MAX, weight)), 3), False


def calibration_curve(rows: list[dict], checkpoint_col: str) -> list[dict]:
    """Reliability diagram data: for each populated confidence decile, the
    stated midpoint vs the realized frequency of being correct. Deciles
    span the full theoretical [0,1] range (bucket k = [k/10, (k+1)/10)) --
    stated_probability() never returns below 0.5, so only upper-half
    buckets are ever populated; that's expected, not a bug."""
    buckets: dict[int, list[float]] = {}
    for r in rows:
        correct = _actual_correct(r, checkpoint_col)
        if correct is None:
            continue
        p = stated_probability(r)
        bucket = min(9, int(p * 10))
        buckets.setdefault(bucket, []).append(1.0 if correct else 0.0)
    curve = []
    for bucket in sorted(buckets):
        outcomes = buckets[bucket]
        curve.append({
            "confidence_range": f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}",
            "stated_midpoint": round((bucket + 0.5) / 10, 2),
            "realized_frequency": round(sum(outcomes) / len(outcomes), 3),
            "sample_n": len(outcomes),
        })
    return curve


def compute_calibration(window_days: int = WINDOW_DAYS) -> dict:
    """Recompute + persist Brier scores and reliability weights for every
    source with at least one completed 24h outcome in the window. Never
    raises on sparse data -- a source with zero completed outcomes simply
    isn't touched (its prior row, if any, stays as-is rather than being
    reset to a misleading zero-sample state)."""
    by_source = get_outcome_rows_by_source(_CHECKPOINT, hours=24 * window_days)
    col = f"price_at_{_CHECKPOINT}"
    results = {}
    for source, rows in by_source.items():
        scored = brier_score(rows, col)
        if scored is None:
            continue
        weight, low_sample = reliability_weight(scored["brier"], scored["sample_n"])
        upsert_calibration_score(
            source=source, window_days=window_days, brier=scored["brier"],
            sample_n=scored["sample_n"], reliability_weight=weight, low_sample=low_sample,
        )
        results[source] = {
            "brier": scored["brier"], "sample_n": scored["sample_n"],
            "reliability_weight": weight, "low_sample": low_sample,
            "curve": calibration_curve(rows, col),
        }
    return results


def get_calibration_report() -> dict:
    """Dashboard/API-facing read: persisted scores plus a freshly-computed
    curve per source (curve isn't persisted -- cheap enough to recompute on
    read, and staying live avoids a second stale-cache surface)."""
    scores = get_calibration_scores()
    by_source = get_outcome_rows_by_source(_CHECKPOINT, hours=24 * WINDOW_DAYS)
    col = f"price_at_{_CHECKPOINT}"
    report = []
    for row in scores:
        rows = by_source.get(row["source"], [])
        report.append({
            **row,
            "low_sample": bool(row["low_sample"]),
            "curve": calibration_curve(rows, col) if rows else [],
        })
    return {"checkpoint": _CHECKPOINT, "sources": report}
