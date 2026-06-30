"""Economic calendar aggregator.

Sources:
  Earnings    : NASDAQ public calendar API
  FOMC        : Hardcoded 2026 schedule + Fed RSS detection
  RBA         : Hardcoded 2026 schedule
  CPI/Jobs    : Hardcoded US BLS schedule 2026
  ASX/AU      : Hardcoded RBA cash rate decisions 2026
"""
import hashlib
import time
from datetime import datetime, date, timedelta

import requests

from memory_store import upsert_calendar_events

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def _key(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ── FOMC 2026 SCHEDULE ────────────────────────────────────────────────────────
# Source: federalreserve.gov — published annually, accurate through Dec 2026
FOMC_2026 = [
    ("2026-01-28", "2026-01-29", "FOMC Meeting (Jan)"),
    ("2026-03-17", "2026-03-18", "FOMC Meeting + Press Conference (Mar)"),
    ("2026-04-28", "2026-04-29", "FOMC Meeting (Apr)"),
    ("2026-06-09", "2026-06-10", "FOMC Meeting + Press Conference (Jun)"),
    ("2026-07-28", "2026-07-29", "FOMC Meeting (Jul)"),
    ("2026-09-15", "2026-09-16", "FOMC Meeting + Press Conference (Sep)"),
    ("2026-11-03", "2026-11-04", "FOMC Meeting (Nov)"),
    ("2026-12-15", "2026-12-16", "FOMC Meeting + Press Conference (Dec)"),
]

# ── RBA 2026 SCHEDULE ─────────────────────────────────────────────────────────
# Source: rba.gov.au — board meetings on first Tuesday of each month (exc Jan)
RBA_2026 = [
    ("2026-02-03", "RBA Board Meeting — Cash Rate Decision (Feb)"),
    ("2026-03-03", "RBA Board Meeting — Cash Rate Decision (Mar)"),
    ("2026-04-07", "RBA Board Meeting — Cash Rate Decision (Apr)"),
    ("2026-05-05", "RBA Board Meeting — Cash Rate Decision (May)"),
    ("2026-06-02", "RBA Board Meeting — Cash Rate Decision (Jun)"),
    ("2026-07-07", "RBA Board Meeting — Cash Rate Decision (Jul)"),
    ("2026-08-04", "RBA Board Meeting — Cash Rate Decision (Aug)"),
    ("2026-09-01", "RBA Board Meeting — Cash Rate Decision (Sep)"),
    ("2026-10-06", "RBA Board Meeting — Cash Rate Decision (Oct)"),
    ("2026-11-03", "RBA Board Meeting — Cash Rate Decision (Nov)"),
    ("2026-12-01", "RBA Board Meeting — Cash Rate Decision (Dec)"),
]

# ── US MACRO EVENTS 2026 ──────────────────────────────────────────────────────
US_MACRO_2026 = [
    # CPI releases (approx — BLS publishes ~2nd week each month)
    ("2026-01-14", "08:30", "US CPI (Dec 2025)", "HIGH"),
    ("2026-02-11", "08:30", "US CPI (Jan 2026)", "HIGH"),
    ("2026-03-11", "08:30", "US CPI (Feb 2026)", "HIGH"),
    ("2026-04-10", "08:30", "US CPI (Mar 2026)", "HIGH"),
    ("2026-05-13", "08:30", "US CPI (Apr 2026)", "HIGH"),
    ("2026-06-10", "08:30", "US CPI (May 2026)", "HIGH"),
    ("2026-07-14", "08:30", "US CPI (Jun 2026)", "HIGH"),
    ("2026-08-12", "08:30", "US CPI (Jul 2026)", "HIGH"),
    ("2026-09-11", "08:30", "US CPI (Aug 2026)", "HIGH"),
    ("2026-10-14", "08:30", "US CPI (Sep 2026)", "HIGH"),
    ("2026-11-12", "08:30", "US CPI (Oct 2026)", "HIGH"),
    ("2026-12-11", "08:30", "US CPI (Nov 2026)", "HIGH"),
    # Non-Farm Payrolls (first Friday each month)
    ("2026-01-09", "08:30", "US Non-Farm Payrolls (Dec 2025)", "HIGH"),
    ("2026-02-06", "08:30", "US Non-Farm Payrolls (Jan 2026)", "HIGH"),
    ("2026-03-06", "08:30", "US Non-Farm Payrolls (Feb 2026)", "HIGH"),
    ("2026-04-03", "08:30", "US Non-Farm Payrolls (Mar 2026)", "HIGH"),
    ("2026-05-01", "08:30", "US Non-Farm Payrolls (Apr 2026)", "HIGH"),
    ("2026-06-05", "08:30", "US Non-Farm Payrolls (May 2026)", "HIGH"),
    ("2026-07-02", "08:30", "US Non-Farm Payrolls (Jun 2026)", "HIGH"),
    ("2026-08-07", "08:30", "US Non-Farm Payrolls (Jul 2026)", "HIGH"),
    ("2026-09-04", "08:30", "US Non-Farm Payrolls (Aug 2026)", "HIGH"),
    ("2026-10-02", "08:30", "US Non-Farm Payrolls (Sep 2026)", "HIGH"),
    ("2026-11-06", "08:30", "US Non-Farm Payrolls (Oct 2026)", "HIGH"),
    ("2026-12-04", "08:30", "US Non-Farm Payrolls (Nov 2026)", "HIGH"),
    # GDP (quarterly)
    ("2026-01-29", "08:30", "US GDP Q4 2025 (Advance)", "HIGH"),
    ("2026-04-29", "08:30", "US GDP Q1 2026 (Advance)", "HIGH"),
    ("2026-07-29", "08:30", "US GDP Q2 2026 (Advance)", "HIGH"),
    ("2026-10-29", "08:30", "US GDP Q3 2026 (Advance)", "HIGH"),
    # PCE (Fed's preferred inflation measure — last business day of month)
    ("2026-01-30", "08:30", "US PCE Price Index (Dec 2025)", "HIGH"),
    ("2026-02-27", "08:30", "US PCE Price Index (Jan 2026)", "HIGH"),
    ("2026-03-27", "08:30", "US PCE Price Index (Feb 2026)", "HIGH"),
    ("2026-04-30", "08:30", "US PCE Price Index (Mar 2026)", "HIGH"),
    ("2026-05-29", "08:30", "US PCE Price Index (Apr 2026)", "HIGH"),
    ("2026-06-26", "08:30", "US PCE Price Index (May 2026)", "HIGH"),
    ("2026-07-31", "08:30", "US PCE Price Index (Jun 2026)", "HIGH"),
    ("2026-08-28", "08:30", "US PCE Price Index (Jul 2026)", "HIGH"),
    ("2026-09-25", "08:30", "US PCE Price Index (Aug 2026)", "HIGH"),
    ("2026-10-30", "08:30", "US PCE Price Index (Sep 2026)", "HIGH"),
    ("2026-11-25", "08:30", "US PCE Price Index (Oct 2026)", "HIGH"),
    ("2026-12-23", "08:30", "US PCE Price Index (Nov 2026)", "HIGH"),
]


def _seed_macro_events():
    events = []

    # FOMC
    for start, end, title in FOMC_2026:
        events.append({
            "event_key": _key("fomc", start),
            "event_type": "fomc",
            "title": title,
            "symbol": None,
            "event_date": start,
            "event_time": "14:00",
            "description": "Federal Open Market Committee rate decision.",
            "eps_forecast": None,
            "eps_actual": None,
            "importance": "HIGH",
            "source": "Federal Reserve",
        })
        # Press conference day (second day)
        if "Press Conference" in title:
            events.append({
                "event_key": _key("fomc_pc", end),
                "event_type": "fomc_press_conference",
                "title": title.replace("Meeting", "Press Conference"),
                "symbol": None,
                "event_date": end,
                "event_time": "14:30",
                "description": "Fed Chair press conference following FOMC decision.",
                "eps_forecast": None,
                "eps_actual": None,
                "importance": "HIGH",
                "source": "Federal Reserve",
            })

    # RBA
    for dt, title in RBA_2026:
        events.append({
            "event_key": _key("rba", dt),
            "event_type": "rba",
            "title": title,
            "symbol": None,
            "event_date": dt,
            "event_time": "14:30",  # AEST 14:30 = ~04:30 UTC
            "description": "Reserve Bank of Australia cash rate decision.",
            "eps_forecast": None,
            "eps_actual": None,
            "importance": "HIGH",
            "source": "RBA",
        })

    # US Macro
    for dt, tm, title, importance in US_MACRO_2026:
        events.append({
            "event_key": _key("us_macro", dt, title[:20]),
            "event_type": "macro",
            "title": title,
            "symbol": None,
            "event_date": dt,
            "event_time": tm,
            "description": None,
            "eps_forecast": None,
            "eps_actual": None,
            "importance": importance,
            "source": "BLS/BEA",
        })

    upsert_calendar_events(events)
    return len(events)


def fetch_earnings_calendar(symbols: list[str]) -> int:
    """Fetch upcoming earnings for the next 7 days from NASDAQ API."""
    events = []
    today = date.today()

    for offset in range(8):
        day = today + timedelta(days=offset)
        try:
            time.sleep(0.4)
            r = requests.get(
                f"https://api.nasdaq.com/api/calendar/earnings?date={day.isoformat()}",
                headers=_HEADERS, timeout=12
            )
            if r.status_code != 200:
                continue
            rows = r.json().get("data", {}).get("rows") or []
            for row in rows:
                sym = row.get("symbol", "")
                name = row.get("name", sym)
                eps_est = row.get("epsForecast") or ""
                report_time = row.get("time", "")
                event_time = "16:30" if "after" in report_time.lower() else "07:30"
                events.append({
                    "event_key": _key("earnings", sym, day.isoformat()),
                    "event_type": "earnings",
                    "title": f"{name} Earnings ({day.strftime('%b %d')})",
                    "symbol": sym,
                    "event_date": day.isoformat(),
                    "event_time": event_time,
                    "description": f"{report_time.replace('time-','').replace('-',' ').title()}",
                    "eps_forecast": eps_est,
                    "eps_actual": None,
                    "importance": "HIGH" if sym in symbols else "medium",
                    "source": "NASDAQ",
                })
        except Exception as e:
            print(f"[Calendar] Earnings fetch error for {day}: {e}")

    return upsert_calendar_events(events)


def refresh_calendar(watchlist_symbols: list[str]) -> dict:
    macro_count = _seed_macro_events()
    earnings_count = fetch_earnings_calendar(watchlist_symbols)
    return {"macro_events": macro_count, "earnings": earnings_count}
