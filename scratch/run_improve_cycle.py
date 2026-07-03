import subprocess
import re
import os
import sys

def main():
    print("=== STARTING AUTONOMOUS SELF-IMPROVEMENT CYCLE ===")
    
    # Run gemini_improve.py and capture stdout line-by-line
    cmd = ["venv/bin/python3", "gemini_improve.py"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    pr_number = None
    pr_url_pattern = re.compile(r"\[Git\] Opened PR: https://github.com/[^/]+/[^/]+/pull/(\d+)")
    
    for line in iter(process.stdout.readline, ""):
        sys.stdout.write(line)
        sys.stdout.flush()
        
        # Search for opened PR
        match = pr_url_pattern.search(line)
        if match:
            pr_number = int(match.group(1))
            
    process.stdout.close()
    return_code = process.wait()
    
    print(f"\nImprovement cycle finished with exit code: {return_code}")
    
    if pr_number:
        print(f"\nDetected newly opened PR: #{pr_number}")
        print("Starting merge_pr.py background task for this PR...")
        # Run merge_pr.py to poll and merge
        merge_cmd = ["python3", "scratch/merge_pr.py", str(pr_number)]
        subprocess.run(merge_cmd)
    else:
        print("\nNo new PR was created during this cycle.")

if __name__ == "__main__":
    main()
