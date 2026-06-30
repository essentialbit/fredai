"""
FredAI ↔ Claude Code Agent
===========================
A true agentic loop where Claude has real tools to read, write, and test
FredAI's own codebase. This is the "lock and step" integration — Fred and
Claude collaborate to implement new features autonomously.

Claude is given:
  - read_file / write_file / patch_file  →  codebase access
  - run_shell                            →  test/validate changes
  - list_project                         →  orientation
  - fetch_url                            →  research external resources
  - log_to_obsidian                      →  persist findings

Usage:
    from claude_code_agent import ClaudeCodeAgent
    agent = ClaudeCodeAgent()
    result = agent.implement("Add RSI indicator overlay to the price chart")
"""

import os
import json
import subprocess
import requests
from pathlib import Path
from datetime import datetime
import anthropic

PROJECT_ROOT = Path(__file__).parent
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python3"


SYSTEM_PROMPT = """You are the FredAI engineering agent — Claude Code embedded inside FredAI's self-improvement loop.

Your job: implement the requested feature or improvement directly into the FredAI codebase.

## Project context
FredAI is a Flask + SocketIO financial intelligence dashboard.
- Backend: Python 3.14, Flask, APScheduler, SQLite, yfinance, Anthropic API
- Frontend: Single-file templates/dashboard.html (Vanilla JS, Chart.js, Lightweight Charts)
- Agent: agent.py (FredAI "Fred" persona, long-term investing strategy)
- Soul: soul.md (Fred's identity — do not alter core values)
- X API: twitter_client.py (requests-based, Python 3.14 compatible — NO tweepy)
- Style: Dark finance theme (#03080f bg, #00ff88 green, #ff3b5c red, #00b4ff blue)

## Engineering standards
- No comments unless WHY is non-obvious
- No emojis in code
- Preserve all existing WebSocket event names
- New frontend features go in templates/dashboard.html
- New backend routes follow existing pattern in main.py
- Always validate imports work before declaring success
- When modifying HTML: preserve the existing CSS variable system

## Workflow
1. Read relevant files to understand current state
2. Implement the change (minimal, targeted)
3. Validate with run_shell (python3 import check or syntax check)
4. Report what changed and why it improves FredAI

Be decisive. Make the change. Don't ask for clarification on implementation details."""


# ── TOOL DEFINITIONS ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the FredAI project directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to project root (e.g. 'agent.py', 'templates/dashboard.html')"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the FredAI project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to project root"},
                "content": {"type": "string", "description": "Full file content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "patch_file",
        "description": "Replace a specific string in a file (targeted edit, safer than full rewrite).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string", "description": "Exact string to find and replace"},
                "new_string": {"type": "string", "description": "Replacement string"}
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "run_shell",
        "description": "Run a shell command in the project directory. Use for: syntax validation, import checks, git operations, pip installs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "list_project",
        "description": "List all Python files and key files in the project.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "fetch_url",
        "description": "Fetch content from a URL for research (API docs, GitHub, arxiv).",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 3000)"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "log_progress",
        "description": "Log progress or findings during the implementation. These appear in the improvement report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"}
            },
            "required": ["message"]
        }
    }
]


# ── TOOL EXECUTORS ────────────────────────────────────────────────────────────

def _exec_tool(name: str, inputs: dict, log: list) -> str:
    try:
        if name == "read_file":
            path = PROJECT_ROOT / inputs["path"]
            if not path.exists():
                return f"ERROR: {inputs['path']} does not exist"
            return path.read_text(encoding="utf-8")[:8000]  # Cap at 8k chars

        elif name == "write_file":
            path = PROJECT_ROOT / inputs["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(inputs["content"], encoding="utf-8")
            return f"Written: {inputs['path']} ({len(inputs['content'])} chars)"

        elif name == "patch_file":
            path = PROJECT_ROOT / inputs["path"]
            if not path.exists():
                return f"ERROR: {inputs['path']} does not exist"
            content = path.read_text(encoding="utf-8")
            old = inputs["old_string"]
            if old not in content:
                return f"ERROR: old_string not found in {inputs['path']}"
            new_content = content.replace(old, inputs["new_string"], 1)
            path.write_text(new_content, encoding="utf-8")
            return f"Patched: {inputs['path']}"

        elif name == "run_shell":
            cmd = inputs["command"]
            # Safety: restrict to safe operations
            blocked = ["rm -rf", "sudo", "curl | sh", "wget | sh", ":(){ :|:& };:"]
            for b in blocked:
                if b in cmd:
                    return f"BLOCKED: unsafe command pattern '{b}'"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=str(PROJECT_ROOT), timeout=30,
                env={**os.environ, "PATH": f"{PROJECT_ROOT/'venv'/'bin'}:{os.environ.get('PATH','')}"}
            )
            out = (result.stdout + result.stderr).strip()
            return out[:3000] if out else f"exit code {result.returncode}"

        elif name == "list_project":
            files = []
            for p in sorted(PROJECT_ROOT.iterdir()):
                if p.name.startswith(".") or p.name in ("venv", "__pycache__", "data"):
                    continue
                if p.is_file():
                    files.append(f"  {p.name} ({p.stat().st_size} bytes)")
                elif p.is_dir():
                    files.append(f"  {p.name}/")
                    for sub in sorted(p.iterdir()):
                        if not sub.name.startswith("."):
                            files.append(f"    {sub.name}")
            return "\n".join(files)

        elif name == "fetch_url":
            url = inputs["url"]
            max_chars = inputs.get("max_chars", 3000)
            r = requests.get(url, timeout=10, headers={"User-Agent": "FredAI-Research/1.0"})
            text = r.text[:max_chars]
            return f"[HTTP {r.status_code}]\n{text}"

        elif name == "log_progress":
            msg = inputs["message"]
            log.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
            print(f"  [Claude] {msg}")
            return "logged"

        return f"Unknown tool: {name}"
    except Exception as e:
        return f"TOOL ERROR ({name}): {e}"


# ── AGENT CLASS ───────────────────────────────────────────────────────────────

class ClaudeCodeAgent:
    """Fred's embedded Claude Code agent — implements features in the live codebase."""

    def __init__(self, model: str = "claude-opus-4-8", max_iterations: int = 25):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = model
        self.max_iterations = max_iterations

    def implement(self, task: str, context: str = "") -> dict:
        """
        Run the full agentic loop to implement a task.
        Returns: {success, summary, files_changed, log, iterations}
        """
        print(f"\n[ClaudeCodeAgent] Task: {task[:80]}")
        log = []
        files_changed = []
        messages = []

        user_content = f"""TASK: {task}

{f'ADDITIONAL CONTEXT: {context}' if context else ''}

IMPORTANT: Start by running list_project and reading relevant files, then implement the change, then validate with run_shell.
After implementing, log_progress with a summary of what changed."""

        messages.append({"role": "user", "content": user_content})

        for iteration in range(self.max_iterations):
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Collect assistant turn
            messages.append({"role": "assistant", "content": resp.content})

            # Check stop reason
            if resp.stop_reason == "end_turn":
                # Extract final text summary
                summary = " ".join(b.text for b in resp.content if hasattr(b, "text") and b.text)
                print(f"[ClaudeCodeAgent] Done in {iteration+1} iterations")
                self._auto_commit(files_changed, task)
                return {
                    "success": True,
                    "summary": summary,
                    "files_changed": files_changed,
                    "log": log,
                    "iterations": iteration + 1,
                }

            if resp.stop_reason != "tool_use":
                break

            # Execute all tool calls in this turn
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result = _exec_tool(block.name, block.input, log)
                # Track file writes
                if block.name in ("write_file", "patch_file") and "ERROR" not in result:
                    path = block.input.get("path", "")
                    if path and path not in files_changed:
                        files_changed.append(path)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        return {
            "success": False,
            "summary": "Max iterations reached without completion",
            "files_changed": files_changed,
            "log": log,
            "iterations": self.max_iterations,
        }

    def _auto_commit(self, files: list, task: str):
        if not files:
            return
        try:
            subprocess.run(["git", "add"] + files, cwd=PROJECT_ROOT, capture_output=True)
            msg = f"auto: {task[:60]}"
            subprocess.run(["git", "commit", "-m", msg], cwd=PROJECT_ROOT, capture_output=True)
            print(f"[ClaudeCodeAgent] Committed: {msg}")
        except Exception as e:
            print(f"[ClaudeCodeAgent] Commit failed: {e}")

    def research(self, question: str) -> str:
        """Use Claude to research a topic and return findings (no code changes)."""
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            tools=TOOLS,
            messages=[{"role": "user", "content": f"Research (do not modify any files): {question}"}],
            system=SYSTEM_PROMPT,
        )
        return " ".join(b.text for b in resp.content if hasattr(b, "text") and b.text)
