import os
import time
import requests
import sys
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "essentialbit/fredai"
PR_NUMBER = int(sys.argv[1]) if len(sys.argv) > 1 else 60

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {TOKEN}" if TOKEN else ""
}

def attempt_merge():
    # Check PR mergeable state
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Error fetching PR: {r.status_code}")
        return False
        
    pr_data = r.json()
    mergeable_state = pr_data.get("mergeable_state")
    merged = pr_data.get("merged", False)
    
    if merged:
        print(f"PR #{PR_NUMBER} is already merged!")
        return True
        
    print(f"PR mergeable state: {mergeable_state}")
    
    if mergeable_state == "clean":
        # Attempt merge
        merge_payload = {
            "commit_title": f"Merge pull request #{PR_NUMBER} from docs/sync-readme-changelog-v1.3.18",
            "merge_method": "merge"
        }
        mres = requests.put(f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/merge", json=merge_payload, headers=headers)
        if mres.status_code == 200:
            print("PR merged successfully!")
            return True
        else:
            print(f"Merge attempt failed: {mres.status_code} - {mres.text}")
    elif mergeable_state == "blocked":
        print("PR is still blocked (waiting for status checks to pass...)")
    elif mergeable_state == "unstable":
        print("PR is unstable or checks failed. Let's see if we can still try to merge or wait.")
    else:
        print(f"Other mergeable state: {mergeable_state}")
        
    return False

if __name__ == "__main__":
    max_attempts = 15
    for attempt in range(max_attempts):
        print(f"Attempt {attempt + 1}/{max_attempts} to merge PR #{PR_NUMBER}...")
        if attempt_merge():
            exit(0)
        time.sleep(20)
    print("Failed to merge PR within time limit.")
    exit(1)
