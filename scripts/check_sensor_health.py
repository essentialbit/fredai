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
LINE_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

# launchd's StartInterval is 3600s (hourly). Every firing -- whether it runs
# a full cycle or short-circuits via the heartbeat/lock skip guards --
# writes a timestamped line to watchdog.log. So under a healthy launchd job,
# consecutive lines should never be more than ~1-2x that interval apart. A
# bigger gap means launchd itself didn't fire (job unloaded, machine asleep
# past its wake window, etc.) -- a distinct failure mode from "fired but the
# cycle errored" (rc!=0), and the existing streak/verdict logic can't see it
# at all if the gap sits *before* the tail window or ends in a success.
SILENT_GAP_THRESHOLD_HOURS = 2.0

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


def find_silent_gaps(path: Path, threshold_hours: float = SILENT_GAP_THRESHOLD_HOURS):
    """Find gaps between consecutive watchdog.log lines wider than expected.

    Scans every line's leading timestamp (start-cycle, skip, and finish
    lines all qualify), not just successful/failed cycle markers, so a
    launchd job that stopped firing entirely shows up even when it isn't
    adjacent to a run failure.
    """
    timestamps = []
    for line in path.read_text(errors="replace").splitlines():
        m = LINE_TS_RE.match(line)
        if m:
            timestamps.append(datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S"))

    gaps = []
    for prev, cur in zip(timestamps, timestamps[1:]):
        delta_hours = (cur - prev).total_seconds() / 3600
        if delta_hours >= threshold_hours:
            gaps.append((prev, cur, delta_hours))
    return gaps


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
    parser.add_argument(
        "--gap-threshold-hours", type=float, default=SILENT_GAP_THRESHOLD_HOURS,
        help="flag a silent gap (launchd never fired) wider than this many hours",
    )
    parser.add_argument(
        "--max-gaps", type=int, default=5, help="max number of silent gaps to print, largest first",
    )
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

    gaps = find_silent_gaps(WATCHDOG_LOG, args.gap_threshold_hours)
    if gaps:
        gaps.sort(key=lambda g: -g[2])
        print(f"\nSILENT_GAP: launchd appears to have not fired for >= {args.gap_threshold_hours:g}h "
              f"({len(gaps)} such gap(s) in the full log, distinct from any rc!=0 streak above):")
        for prev, cur, hours in gaps[: args.max_gaps]:
            print(f"  {prev} -> {cur}  ({hours:.1f}h, no watchdog.log activity)")
    else:
        print(f"\nSILENT_GAP: none (no watchdog.log gap >= {args.gap_threshold_hours:g}h found)")


if __name__ == "__main__":
    main()
