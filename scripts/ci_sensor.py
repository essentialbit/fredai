#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

STATE_FILE = PROJECT_ROOT / "data" / "ci_sensor_state.json"

def get_github_runs() -> list:
    """Fetch recent runs via gh CLI."""
    try:
        res = subprocess.run(
            ["gh", "run", "list", "-R", "essentialbit/fredai", "--limit", "10", "--json", "databaseId,status,conclusion,headBranch,name,event,createdAt"],
            capture_output=True, text=True, check=True
        )
        # Map databaseId to id to keep the rest of the code clean
        runs = json.loads(res.stdout)
        for r in runs:
            r["id"] = r.pop("databaseId", "")
        return runs
    except subprocess.CalledProcessError as e:
        print(f"[CI Sensor] Error querying GitHub CLI: {e}\nStderr: {e.stderr}")
        return []
    except Exception as e:
        print(f"[CI Sensor] Error querying GitHub CLI: {e}")
        return []

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"runs": {}}

def save_state(state: dict):
    os.makedirs(STATE_FILE.parent, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def check_and_sync_git():
    """Check if the local repository is behind origin/main, and pull updates if clean."""
    try:
        # Fetch latest
        subprocess.run(["git", "fetch", "origin", "main"], cwd=str(PROJECT_ROOT), capture_output=True, check=True)
        
        # Check count behind
        res = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, check=True
        )
        behind = int(res.stdout.strip())
        if behind > 0:
            print(f"[Collaboration Sensor] Sync: Behind origin/main by {behind} commit(s). Checking tree cleanliness...")
            # Check if working tree is clean
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, check=True
            )
            if not status_res.stdout.strip():
                print(f"[Collaboration Sensor] Sync: Working tree is clean. Pulling updates from Claude's merges...")
                pull_res = subprocess.run(
                    ["git", "pull", "origin", "main", "--rebase"],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, check=True
                )
                print(f"[Collaboration Sensor] Sync Success: {pull_res.stdout.strip()}")
            else:
                print(f"[Collaboration Sensor] Sync Warning: Working tree is dirty. Skipping auto-pull to avoid conflicts.")
    except Exception as e:
        print(f"[Collaboration Sensor] Error syncing git: {e}")

def run_debate_check():
    """Run debate cycle to automatically review any new proposals from Claude."""
    try:
        import dotenv
        dotenv.load_dotenv(str(PROJECT_ROOT / ".env"))
        
        import debate
        summary = debate.run_debate_cycle()
        if summary.get("stances_posted", 0) > 0:
            print(f"[Collaboration Sensor] Debate: Posted {summary['stances_posted']} stance(s) on Claude's proposals!")
        else:
            print(f"[Collaboration Sensor] Debate: Checked {summary['issues_checked']} proposal(s). No new reviews posted.")
    except Exception as e:
        print(f"[Collaboration Sensor] Error running debate check: {e}")

def check_open_prs():
    """Scan open PRs to see if there are any from Claude awaiting our review/comment."""
    try:
        res = subprocess.run(
            ["gh", "pr", "list", "-R", "essentialbit/fredai", "--json", "number,title,headRefName"],
            capture_output=True, text=True, check=True
        )
        prs = json.loads(res.stdout)
        for pr in prs:
            branch = pr["headRefName"]
            if branch.startswith("agent/claude-") or branch.startswith("infra/"):
                num = pr["number"]
                c_res = subprocess.run(
                    ["gh", "pr", "view", str(num), "-R", "essentialbit/fredai", "--json", "comments"],
                    capture_output=True, text=True, check=True
                )
                comments_data = json.loads(c_res.stdout)
                comments = comments_data.get("comments", [])
                
                reviewed = False
                for c in comments:
                    body = c.get("body", "").lower()
                    if "gemini" in body or "lgtm!" in body:
                        reviewed = True
                        break
                
                if not reviewed:
                    print(f"[Collaboration Sensor] REVIEW REQUIRED: Claude's PR #{num} ({pr['title']}) is awaiting review!")
    except Exception as e:
        print(f"[Collaboration Sensor] Error checking PRs: {e}")

def main():
    print("=== FRED AI COLLABORATION & CI SENSOR ===")
    
    # 1. Sync Git with remote changes/merges
    check_and_sync_git()
    
    # 2. Check for CI/CD runs
    runs = get_github_runs()
    if runs:
        state = load_state()
        prev_runs = state.get("runs", {})
        new_runs = {}

        active_claude_runs = []
        completed_reports = []

        for run in runs:
            run_id = str(run["id"])
            status = run["status"]
            conclusion = run.get("conclusion", "")
            branch = run["headBranch"]
            name = run["name"]

            new_runs[run_id] = {
                "status": status,
                "conclusion": conclusion,
                "branch": branch,
                "name": name
            }

            is_claude_branch = branch.startswith("agent/claude-") or branch.startswith("infra/")
            if is_claude_branch:
                if status in ("in_progress", "queued"):
                    active_claude_runs.append(run)
                
                prev = prev_runs.get(run_id)
                if prev and prev["status"] in ("in_progress", "queued") and status == "completed":
                    completed_reports.append((run, conclusion))

        state["runs"] = new_runs
        save_state(state)

        if active_claude_runs:
            print(f"[CI Sensor] ACTIVE activity detected on Claude branches:")
            for r in active_claude_runs:
                print(f"  - Run #{r['id']} ({r['name']}) on branch [{r['headBranch']}] is {r['status']}")
            print("[CI Sensor] WARNING: Do not interrupt or push changes until Claude's CI run finishes.")
        else:
            print("[CI Sensor] No active Claude CI/CD runs detected. Safe to collaborate/push.")

        if completed_reports:
            print("\n[CI Sensor] COMPLETED recently:")
            for r, conclusion in completed_reports:
                print(f"  - Run #{r['id']} ({r['name']}) on branch [{r['headBranch']}] completed with conclusion: {conclusion}")
    else:
        print("[CI Sensor] No runs found or GitHub API check failed.")

    # 3. Check open PRs for pending reviews
    check_open_prs()

    # 4. Check and participate in debate cycle (reviewing Claude's proposals)
    run_debate_check()

if __name__ == "__main__":
    main()
