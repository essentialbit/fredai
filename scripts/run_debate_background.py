"""Launch debate.run_debate_cycle() as a detached background process.

Exists because the sensor cycle's own Bash tool call to run_debate_cycle()
needs an explicit >=300000ms timeout (Gemini-429/Ollama-fallback retry chains
run long) -- a param that has been forgotten 4 separate times despite being
documented in fredai.md and inlined in sensor-prompt.md. This script launches
the cycle detached so the invoking Bash call returns in well under the 120s
default regardless of forgetting a timeout param; the result is read back
from the log file afterward via --check.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path.home() / ".claude" / "fred-sensor" / "logs"


def launch() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"debate_cycle_{int(time.time())}.log"
    with open(log_path, "wb") as log_file:
        subprocess.Popen(
            [sys.executable, "-c",
             "import json; from debate import run_debate_cycle; "
             "print(json.dumps(run_debate_cycle(), indent=2, default=str))"],
            cwd=REPO_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return log_path


def check(log_path: Path, wait_seconds: int) -> bool:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if log_path.exists() and log_path.stat().st_size > 0:
            print(log_path.read_text())
            return True
        time.sleep(2)
    print(f"Not finished yet -- log so far ({log_path}):")
    if log_path.exists():
        print(log_path.read_text())
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", metavar="LOG_PATH", help="Poll an existing log path for completion")
    parser.add_argument("--wait", type=int, default=0, help="Seconds to poll when --check is used (default: 0, one-shot read)")
    args = parser.parse_args()

    if args.check:
        found = check(Path(args.check), args.wait)
        sys.exit(0 if found else 1)
    else:
        path = launch()
        print(f"Launched debate cycle in background. Log: {path}")
