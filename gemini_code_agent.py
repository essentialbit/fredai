"""
FredAI ↔ Gemini Code Agent
===========================
An agentic tool loop using the Google Gemini REST API to autonomously
improve and extend the FredAI codebase.
"""

import os
import json
import subprocess
import requests
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python3"

SYSTEM_PROMPT = """You are the FredAI engineering agent — Gemini Code embedded inside FredAI's self-improvement loop.
Your job: implement the requested feature or improvement directly into the FredAI codebase.

## Project context
FredAI is a Flask + SocketIO financial intelligence dashboard.
- Backend: Python 3.14, Flask, APScheduler, SQLite, yfinance, Anthropic/Gemini APIs
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
4. Call 'done' and report what changed and why it improves FredAI

Be decisive. Make the change. Don't ask for clarification on implementation details."""

# ── TOOL EXECUTORS ────────────────────────────────────────────────────────────

def _exec_tool(name: str, inputs: dict, log: list, files_changed: list) -> str:
    try:
        if name == "read_file":
            path = PROJECT_ROOT / inputs["path"]
            if not path.exists():
                return f"ERROR: {inputs['path']} does not exist"
            return path.read_text(encoding="utf-8")[:8000]

        elif name == "write_file":
            path = PROJECT_ROOT / inputs["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(inputs["content"], encoding="utf-8")
            if inputs["path"] not in files_changed:
                files_changed.append(inputs["path"])
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
            if inputs["path"] not in files_changed:
                files_changed.append(inputs["path"])
            return f"Patched: {inputs['path']}"

        elif name == "run_shell":
            cmd = inputs["command"]
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
            log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            print(f"  [Gemini] {msg}")
            return "logged"

        return f"Unknown tool: {name}"
    except Exception as e:
        return f"TOOL ERROR ({name}): {e}"

# ── AGENT CLASS ───────────────────────────────────────────────────────────────

class GeminiCodeAgent:
    """Fred's embedded Gemini Code agent — implements features in the live codebase."""

    def __init__(self, model: str = "gemini-2.5-flash", max_iterations: int = 25):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = model
        self.max_iterations = max_iterations

    def implement(self, task: str, context: str = "") -> dict:
        if not self.api_key:
            return {"success": False, "summary": "GEMINI_API_KEY not configured", "files_changed": []}

        print(f"\n[GeminiCodeAgent] Task: {task[:80]}")
        log = []
        files_changed = []
        messages = []

        user_content = f"""TASK: {task}

{f'ADDITIONAL CONTEXT: {context}' if context else ''}

IMPORTANT: Start by running list_project and reading relevant files, then implement the change, then validate with run_shell.
After implementing, call 'done' with a summary of what changed."""

        messages.append({"role": "user", "parts": [{"text": user_content}]})

        # Define Schema for JSON validation
        schema = {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "tool_call": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": ["list_project", "read_file", "write_file", "patch_file", "run_shell", "fetch_url", "log_progress", "done"]
                        },
                        "args": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                                "command": {"type": "string"},
                                "url": {"type": "string"},
                                "max_chars": {"type": "integer"},
                                "message": {"type": "string"},
                                "summary": {"type": "string"}
                            }
                        }
                    },
                    "required": ["name", "args"]
                }
            },
            "required": ["thought", "tool_call"]
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        for iteration in range(self.max_iterations):
            body = {
                "contents": messages,
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": schema
                }
            }

            data = None
            try:
                if self.api_key:
                    r = requests.post(url, json=body, timeout=60)
                    if r.status_code == 200:
                        data = r.json()
                    else:
                        print(f"  [Gemini API Error] {r.status_code}: {r.text}")
            except Exception as e:
                print(f"  [Gemini] Request error: {e}")

            if data is None:
                print("  [Gemini Code Agent] Falling back to local Ollama...")
                try:
                    models_res = requests.get("http://localhost:11434/api/tags", timeout=5)
                    available_models = []
                    if models_res.status_code == 200:
                        available_models = [m["name"] for m in models_res.json().get("models", [])]
                    
                    selected_model = None
                    for pref in ["qwen3.5-hermes", "qwen3.5", "qwen3-8b-hermes", "gemma3-hermes", "gemma3:4b", "gemma4", "llama3.2"]:
                        for m in available_models:
                            if m.startswith(pref):
                                selected_model = m
                                break
                        if selected_model:
                            break
                    
                    if not selected_model and available_models:
                        selected_model = available_models[0]
                    if not selected_model:
                        selected_model = "gemma3:4b"

                    # Convert Gemini content format to Ollama messages format
                    ollama_msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
                    for msg in messages:
                        role = msg.get("role", "user")
                        # Gemini roles are 'user' and 'model'. Ollama expects 'user' and 'assistant'
                        if role == "model":
                            role = "assistant"
                        text_parts = []
                        for part in msg.get("parts", []):
                            if "text" in part:
                                text_parts.append(part["text"])
                        ollama_msgs.append({"role": role, "content": "\n".join(text_parts)})

                    # Append schema constraint to user message if it's the last one
                    if ollama_msgs[-1]["role"] == "user":
                        ollama_msgs[-1]["content"] += f"\n\nCRITICAL: Respond ONLY with a raw JSON object matching the requested schema. No markdown wrapping. Schema:\n{json.dumps(schema, indent=2)}"

                    ollama_res = requests.post("http://localhost:11434/api/chat", json={
                        "model": selected_model,
                        "messages": ollama_msgs,
                        "format": "json",
                        "stream": False
                    }, timeout=300)
                    if ollama_res.status_code == 200:
                        reply = ollama_res.json().get("message", {}).get("content", "").strip()
                        action = json.loads(reply)
                    else:
                        return {"success": False, "summary": f"Ollama fallback failed: {ollama_res.status_code}", "files_changed": files_changed}
                except Exception as oe:
                    print(f"  [Ollama Fallback Error] {oe}")
                    return {"success": False, "summary": f"Ollama fallback error: {oe}", "files_changed": files_changed}
            else:
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    action = json.loads(text)
                except Exception as e:
                    print(f"  [Gemini] Parse error: {e}")
                    return {"success": False, "summary": f"Error parsing Gemini response: {e}", "files_changed": files_changed}

            thought = action.get("thought", "")
            tool_call = action.get("tool_call", {})
            name = tool_call.get("name")
            args = tool_call.get("args", {})

            # Log thoughts
            if thought:
                print(f"  [Gemini Thought] {thought}")

            if name == "done":
                summary = args.get("summary", "Complete")
                print(f"[GeminiCodeAgent] Done in {iteration+1} iterations")
                self._auto_commit(files_changed, task)
                return {
                    "success": True,
                    "summary": summary,
                    "files_changed": files_changed,
                    "log": log,
                    "iterations": iteration + 1
                }

            # Run tool
            print(f"  [Gemini Tool Call] {name} ({list(args.keys())})")
            result = _exec_tool(name, args, log, files_changed)

            # Append the model turn and tool result to history
            messages.append({"role": "model", "parts": [{"text": text}]})
            messages.append({"role": "user", "parts": [{"text": f"Tool response from {name}:\n{result}"}]})

        return {
            "success": False,
            "summary": "Max iterations reached without completion",
            "files_changed": files_changed,
            "log": log,
            "iterations": self.max_iterations
        }

    def _auto_commit(self, files: list, task: str):
        if not files:
            return
        try:
            subprocess.run(["git", "add"] + files, cwd=PROJECT_ROOT, capture_output=True)
            msg = f"auto(gemini): {task[:60]}"
            subprocess.run(["git", "commit", "-m", msg], cwd=PROJECT_ROOT, capture_output=True)
            print(f"[GeminiCodeAgent] Committed: {msg}")
        except Exception as e:
            print(f"[GeminiCodeAgent] Commit failed: {e}")
