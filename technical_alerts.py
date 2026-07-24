"""Technical alert engine — MA, RSI, volume spike, price cross.

Alert types:
  price_above   : current price > threshold
  price_below   : current price < threshold
  ma_cross_above: price crosses above N-period MA
  ma_cross_below: price crosses below N-period MA
  rsi_above     : RSI(period) > threshold (overbought)
  rsi_below     : RSI(period) < threshold (oversold)
  volume_spike  : today's volume > threshold × avg_volume
"""
from __future__ import annotations

from datetime import datetime

from market_data import fetch_history, _chart
from memory_store import (
    get_all_tech_alerts_enabled,
    mark_tech_alert_triggered,
)
from regime_detector import get_regime

# Alert types read as trend-confirmation (breakout-style) vs mean-reversion.
# Weighted higher (level="warning") when the ticker's own regime agrees with
# the alert's underlying assumption -- MA crosses are more actionable in a
# trending regime, RSI overbought/oversold is more actionable range-bound.
_TREND_ALERT_TYPES = {"ma_cross_above", "ma_cross_below"}
_MEAN_REVERSION_ALERT_TYPES = {"rsi_above", "rsi_below"}


def _regime_weighted_level(symbol: str, alert_type: str) -> str:
    if alert_type not in _TREND_ALERT_TYPES and alert_type not in _MEAN_REVERSION_ALERT_TYPES:
        return "info"
    regime_data = get_regime(symbol)
    regime = regime_data["regime"] if regime_data else "unknown"
    if alert_type in _TREND_ALERT_TYPES and regime == "trending":
        return "warning"
    if alert_type in _MEAN_REVERSION_ALERT_TYPES and regime == "ranging":
        return "warning"
    return "info"

def _insert_system_alert(title, message, level="info", asset=None):
    from memory_store import insert_alert
    insert_alert(level=level, title=title, message=message, asset=asset)


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-period + i] - closes[-period + i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _calc_sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def _get_price_data(symbol: str, period: int = 50) -> dict | None:
    """Return recent OHLCV data needed for technical calculations."""
    candles = fetch_history(symbol, period="3mo", interval="1d")
    if not candles:
        return None
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    if not closes:
        return None
    current = closes[-1]
    avg_vol = sum(volumes[-20:]) / max(len(volumes[-20:]), 1)
    today_vol = volumes[-1] if volumes else 0
    return {
        "closes": closes,
        "current": current,
        "prev": closes[-2] if len(closes) > 1 else current,
        "volumes": volumes,
        "today_vol": today_vol,
        "avg_vol_20": avg_vol,
    }


def _check_alert(alert: dict, data: dict) -> tuple[bool, str]:
    """Return (triggered, message)."""
    atype = alert["alert_type"]
    threshold = float(alert.get("threshold") or 0)
    period = int(alert.get("period") or 20)
    closes = data["closes"]
    current = data["current"]
    prev = data["prev"]

    if atype == "price_above":
        if current > threshold:
            return True, f"{alert['symbol']} at ${current:.2f} — above alert level ${threshold:.2f}"
        return False, ""

    if atype == "price_below":
        if current < threshold:
            return True, f"{alert['symbol']} at ${current:.2f} — below alert level ${threshold:.2f}"
        return False, ""

    if atype == "ma_cross_above":
        ma_now = _calc_sma(closes, period)
        ma_prev = _calc_sma(closes[:-1], period)
        if ma_now and ma_prev and prev <= ma_prev and current > ma_now:
            return True, f"{alert['symbol']} crossed above {period}-period MA at ${ma_now:.2f}"
        return False, ""

    if atype == "ma_cross_below":
        ma_now = _calc_sma(closes, period)
        ma_prev = _calc_sma(closes[:-1], period)
        if ma_now and ma_prev and prev >= ma_prev and current < ma_now:
            return True, f"{alert['symbol']} crossed below {period}-period MA at ${ma_now:.2f}"
        return False, ""

    if atype == "rsi_above":
        rsi = _calc_rsi(closes, period)
        if rsi and rsi > threshold:
            return True, f"{alert['symbol']} RSI({period})={rsi:.1f} — overbought above {threshold:.0f}"
        return False, ""

    if atype == "rsi_below":
        rsi = _calc_rsi(closes, period)
        if rsi and rsi < threshold:
            return True, f"{alert['symbol']} RSI({period})={rsi:.1f} — oversold below {threshold:.0f}"
        return False, ""

    if atype == "volume_spike":
        if data["avg_vol_20"] > 0:
            ratio = data["today_vol"] / data["avg_vol_20"]
            if ratio > threshold:
                return True, f"{alert['symbol']} volume spike {ratio:.1f}× average (threshold {threshold:.1f}×)"
        return False, ""

    return False, ""


def get_technicals(symbol: str) -> dict:
    """Compute SMA20, SMA50, RSI14, volume for display on dashboard."""
    data = _get_price_data(symbol, 60)
    if not data:
        return {}
    closes = data["closes"]
    return {
        "symbol": symbol,
        "current": data["current"],
        "sma20": _calc_sma(closes, 20),
        "sma50": _calc_sma(closes, 50),
        "rsi14": _calc_rsi(closes, 14),
        "volume": data["today_vol"],
        "volume_ratio": round(data["today_vol"] / max(data["avg_vol_20"], 1), 2),
    }


def run_technical_alerts() -> list[dict]:
    """Check all enabled alerts and fire any that trigger. Returns fired list."""
    alerts = get_all_tech_alerts_enabled()
    fired = []

    # Group by symbol to avoid repeat fetches
    by_symbol: dict[str, list] = {}
    for a in alerts:
        by_symbol.setdefault(a["symbol"], []).append(a)

    for symbol, sym_alerts in by_symbol.items():
        data = _get_price_data(symbol)
        if not data:
            continue

        for alert in sym_alerts:
            try:
                triggered, msg = _check_alert(alert, data)
                if triggered:
                    mark_tech_alert_triggered(alert["id"])
                    level = _regime_weighted_level(symbol, alert["alert_type"])
                    try:
                        _insert_system_alert(
                            title=f"Technical Alert: {alert['symbol']}",
                            message=msg,
                            level=level,
                            asset=alert["symbol"],
                        )
                    except Exception:
                        pass
                    fired.append({"alert_id": alert["id"], "symbol": symbol, "message": msg})
            except Exception as e:
                print(f"[TechAlerts] Error checking alert {alert['id']}: {e}")

    return fired
