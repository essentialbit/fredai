"""Diagnose whether the current/last sensor run is genuinely alive, stuck past
its 45-min hard-kill cap, or an orphaned lock left by a process that died
without cleaning up.

Formalizes an ad-hoc PID/PPID-matching check repeated by hand across several
cycles while investigating a confirmed-twice bug where run-sensor.sh's own
MAX_RUN_SECS=2700 kill loop failed to fire (2026-08-16). This script never
touches run-sensor.sh itself (protected, user-fix-only) -- it only reads
run.lock + watchdog.log + `ps` to surface the same live signal a human would
have to reconstruct by hand mid-incident.

Usage: PYTHONPATH=. python3 scripts/check_run_lock_freshness.py
"""
import re
import subprocess
from datetime import datetime
from pathlib import Path

SENSOR_DIR = Path.home() / ".claude" / "fred-sensor"
LOCK = SENSOR_DIR / "run.lock"
WATCHDOG_LOG = SENSOR_DIR / "watchdog.log"

# Mirrors run-sensor.sh's own constant -- kept here only to judge staleness,
# never used to act on the running process.
MAX_RUN_SECS = 2700
GRACE_SECS = 300  # tolerate the watchdog's own 30s poll granularity + slack

START_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) heartbeat stale")
FINISH_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) sensor cycle finished")


def _etime_to_secs(etime: str) -> int:
    """Parse ps(1) ELAPSED format: [[dd-]hh:]mm:ss."""
    days = 0
    if "-" in etime:
        d, etime = etime.split("-", 1)
        days = int(d)
    parts = [int(p) for p in etime.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return days * 86400 + h * 3600 + m * 60 + s


def _ps_elapsed(pid: int):
    try:
        out = subprocess.run(
            ["ps", "-o", "etime=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        return None, f"ps failed: {e}"
    etime = out.stdout.strip()
    if not etime:
        return None, "no such process"
    return _etime_to_secs(etime), None


def _last_watchdog_state():
    if not WATCHDOG_LOG.exists():
        return None, None
    last_start = last_finish = None
    for line in WATCHDOG_LOG.read_text(errors="replace").splitlines():
        m = START_RE.match(line)
        if m:
            last_start = m.group("ts")
            continue
        m = FINISH_RE.match(line)
        if m:
            last_finish = m.group("ts")
    return last_start, last_finish


def main():
    if not LOCK.exists():
        print("verdict: NO_LOCK (no cycle currently running per run.lock)")
        return

    raw = LOCK.read_text(errors="replace").strip()
    try:
        pid = int(raw)
    except ValueError:
        print(f"verdict: MALFORMED_LOCK (contents: {raw!r})")
        return

    elapsed_secs, err = _ps_elapsed(pid)
    last_start, last_finish = _last_watchdog_state()

    if elapsed_secs is None:
        print(f"verdict: STALE_LOCK (pid {pid} not running: {err}) -- lock should have been cleaned up on exit")
        print(f"last watchdog start: {last_start}  last finish: {last_finish}")
        return

    print(f"pid {pid} alive, elapsed {elapsed_secs}s ({elapsed_secs / 60:.1f}m)")
    print(f"last watchdog start: {last_start}  last finish: {last_finish}")

    if elapsed_secs <= MAX_RUN_SECS:
        print(f"verdict: RUNNING (within {MAX_RUN_SECS}s cap)")
    elif elapsed_secs <= MAX_RUN_SECS + GRACE_SECS:
        print(f"verdict: OVERRUN_PENDING (past cap by {elapsed_secs - MAX_RUN_SECS}s -- watchdog kill loop may not have polled yet)")
    else:
        print(
            f"verdict: OVERRUN_NOT_KILLED (past cap by {elapsed_secs - MAX_RUN_SECS}s, "
            f"beyond grace -- run-sensor.sh's MAX_RUN_SECS kill did not fire, matches the "
            f"2026-08-16 confirmed-twice bug; do not kill it from here, report for user review)"
        )


if __name__ == "__main__":
    main()
