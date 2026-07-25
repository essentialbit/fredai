"""Diagnose gaps in the hourly headless sensor's run history.

The watchdog (memory/fred-sensor/run-sensor.sh) logs one line per attempted
cycle to ~/.claude/fred-sensor/watchdog.log, but a cycle that fails before
Claude ever starts writing a report (e.g. the account hits its weekly usage
limit) leaves no trace anywhere else -- reports/YYYY-MM.md simply has a gap,
indistinguishable at a glance from "nothing needed reporting." Confirmed
real: a 2026-07-22 -> 2026-07-24 outage (30+ consecutive rc=1 failures, all
"You've hit your weekly limit") went undetected until manually diagnosed.

Usage: PYTHONPATH=. python3 scripts/check_sensor_health.py [--tail N]
"""
import argparse
import re
from datetime import datetime
from pathlib import Path

SENSOR_DIR = Path.home() / ".claude" / "fred-sensor"
WATCHDOG_LOG = SENSOR_DIR / "watchdog.log"
LOGS_DIR = SENSOR_DIR / "logs"

CYCLE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) sensor cycle finished rc=(?P<rc>\d+) \((?P<dur>\d+)s\)$"
)
START_RE = re.compile(r"-> .*/logs/(?P<name>\d{8}-\d{6})\.log$")

SIGNATURES = [
    ("weekly_limit", re.compile(r"weekly limit", re.IGNORECASE)),
    ("cert_error", re.compile(r"CERTIFICATE_VERIFICATION|certificate", re.IGNORECASE)),
    ("rate_limit", re.compile(r"rate.?limit", re.IGNORECASE)),
]


def classify(log_path: Path) -> str:
    if not log_path.exists():
        return "log_missing"
    text = log_path.read_text(errors="replace").strip()
    if not text:
        return "empty_log"
    for name, pattern in SIGNATURES:
        if pattern.search(text):
            return name
    return f"other: {text[:80]!r}"


def parse_watchdog(path: Path):
    cycles = []
    pending_log_name = None
    for line in path.read_text(errors="replace").splitlines():
        start_m = START_RE.search(line)
        if start_m:
            pending_log_name = start_m.group("name")
            continue
        m = CYCLE_RE.match(line)
        if m:
            cycles.append({
                "ts": datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S"),
                "rc": int(m.group("rc")),
                "dur": int(m.group("dur")),
                "log_name": pending_log_name,
            })
            pending_log_name = None
    return cycles


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tail", type=int, default=200, help="only consider the last N logged cycles")
    args = parser.parse_args()

    if not WATCHDOG_LOG.exists():
        print(f"NO_DATA: watchdog log not found at {WATCHDOG_LOG}")
        return

    cycles = parse_watchdog(WATCHDOG_LOG)[-args.tail:]
    if not cycles:
        print("NO_DATA: watchdog log exists but no cycle entries parsed")
        return

    now = datetime.now()
    last = cycles[-1]

    streak = 0
    for c in reversed(cycles):
        if c["rc"] != 0:
            streak += 1
        else:
            break

    last_success = next((c for c in reversed(cycles) if c["rc"] == 0), None)
    gap_hours = (now - last_success["ts"]).total_seconds() / 3600 if last_success else None

    if streak == 0:
        verdict = "OK"
    elif streak <= 2:
        verdict = "DEGRADED"
    else:
        verdict = "OUTAGE"

    print(f"verdict: {verdict}")
    print(f"last cycle: {last['ts']} rc={last['rc']} dur={last['dur']}s")
    print(f"consecutive non-zero-rc streak: {streak}")
    if last_success:
        print(f"last successful (rc=0) cycle: {last_success['ts']} ({gap_hours:.1f}h ago)")
    else:
        print("no successful (rc=0) cycle found in tail window")

    if streak:
        print("\nfailure signatures in current streak:")
        counts = {}
        for c in cycles[len(cycles) - streak:]:
            log_path = LOGS_DIR / f"{c['log_name']}.log" if c["log_name"] else None
            sig = classify(log_path) if log_path else "no_log_captured"
            counts[sig] = counts.get(sig, 0) + 1
        for sig, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:3d}x  {sig}")


if __name__ == "__main__":
    main()
