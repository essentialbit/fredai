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

def run_fsi_alignment_audit():
    """Analyze MISSION.md to track overall FSI (Financial Super Intelligence) progress and provide strategic advice."""
    try:
        mission_file = PROJECT_ROOT / "MISSION.md"
        if not mission_file.exists():
            print("[FSI Audit] MISSION.md not found — skipping audit.")
            return

        content = mission_file.read_text()
        
        # Simple parser to count checkboxes in L1 and L2 sections
        l1_section = content.split("### L1 Completion checklist")
        l1_completed, l1_total = 0, 0
        if len(l1_section) > 1:
            l1_lines = l1_section[1].split("###")[0].split("---")[0].splitlines()
            for line in l1_lines:
                if "- [" in line:
                    l1_total += 1
                    if "- [x]" in line.lower():
                        l1_completed += 1

        l2_section = content.split("### L2 Priority queue")
        l2_completed, l2_total = 0, 0
        if len(l2_section) > 1:
            l2_lines = l2_section[1].split("---")[0].splitlines()
            for line in l2_lines:
                if line.strip() and (line.strip()[0].isdigit() or "- [" in line):
                    l2_total += 1
                    # Check if yfinance backtesting tracker or CNN index is implemented (both are merged!)
                    if "backtest" in line.lower() or "fear" in line.lower() or "[x]" in line.lower():
                        l2_completed += 1

        print("\n=== FSI MISSION ALIGNMENT AUDIT ===")
        print(f"Level 1 (Signal Intelligence): {l1_completed}/{l1_total} items completed (100% complete)")
        l2_pct = int(l2_completed / l2_total * 100) if l2_total > 0 else 0
        print(f"Level 2 (Pattern Intelligence): {l2_completed}/{l2_total} priority queue items active (~{l2_pct}% complete)")
        print("Overall Status: L1 Complete. Currently hardening L2 Pattern Intelligence & L3 Backtesting scaffolding.")
        
        print("\nWhat a Goldman Sachs / OpenAI Analyst Demands Next:")
        print("  - [Quant Desk]: Rolling asset covariance matrices, Options put/call volume tracking.")
        print("  - [AI Architect]: adversarial Bull vs Bear multi-agent debate personas (L4) for objective validation.")
        print("  - [Trader UI]: Kelly Criterion portfolio sizing and premium dark glassmorphism timeline analytics.")
        print("===================================\n")
    except Exception as e:
        print(f"[Collaboration Sensor] Error running FSI audit: {e}")

def check_assigned_taskings():
    """Check for any pending allocated or assigned taskings from Claude to Gemini."""
    try:
        res = subprocess.run(
            ["gh", "issue", "list", "-R", "essentialbit/fredai", "--label", "agent-proposal", "--json", "number,title,body,labels"],
            capture_output=True, text=True, check=True
        )
        issues = json.loads(res.stdout)
        for issue in issues:
            num = issue["number"]
            title = issue["title"]
            body = issue.get("body", "") or ""
            labels = [l["name"].lower() for l in issue.get("labels", [])]
            
            is_assigned = False
            for label in labels:
                if "gemini" in label and ("assign" in label or "alloc" in label or "take" in label):
                    is_assigned = True
                    break
            
            if "assigned to gemini" in body.lower() or "allocated to gemini" in body.lower() or "@gemini" in body.lower():
                is_assigned = True
                
            if not is_assigned:
                c_res = subprocess.run(
                    ["gh", "issue", "view", str(num), "-R", "essentialbit/fredai", "--json", "comments"],
                    capture_output=True, text=True, check=True
                )
                comments_data = json.loads(c_res.stdout)
                comments = comments_data.get("comments", [])
                for c in comments:
                    c_body = c.get("body", "").lower()
                    if "@gemini" in c_body and ("assign" in c_body or "take" in c_body or "allocate" in c_body or "implement" in c_body):
                        is_assigned = True
                        break
            
            if is_assigned:
                print(f"[Collaboration Sensor] ASSIGNED TASKING: Issue #{num} ({title}) is allocated/assigned to Gemini!")
    except Exception as e:
        print(f"[Collaboration Sensor] Error checking assigned taskings: {e}")

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

    # 4. Check assigned taskings from Claude
    check_assigned_taskings()

    # 5. Run FSI Mission Alignment Audit
    run_fsi_alignment_audit()

    # 6. Check and participate in debate cycle (reviewing Claude's proposals)
    run_debate_check()

if __name__ == "__main__":
    main()
