# Specification: Real-Time WebSocket Debate & Decision Engine (Method B)

This spec defines a local WebSocket-based IPC mechanism to enable real-time, interactive debates, rapid consensus resolution, and decision-logging for Claude and Gemini, complete with a futuristic Web UI for the user.

---

## 1. Core Principles

1. **Minimize Mean Time to Decision (MTTD)**: Limit debate turns to a maximum of 3 per agent per topic. If no consensus is reached, fall back to the highest track-record agent's decision.
2. **Action Over Contemplation**: Pragmatic testing only. Run tests once to verify compile and basic execution. No endless test loops.
3. **Traceability & Rollback**: Every resolved decision must log the active Git Commit Hash, enabling a one-click rollback (`git revert` or `git reset`).
4. **Memory-Driven Optimization**: Store every decision in the decision matrix to index variables (turns taken, MTTD, success/failure outcomes) to optimize future MTTD.

---

## 2. Architecture & Components

### A. The WebSocket Relay (`debate_relay.py`)
A lightweight, local server running on `ws://localhost:9000`. It broadcasts messages between the connected client agents (Claude and Gemini) and any connected Web UI client.

### B. Protocol Messages (JSON)
Agents exchange structured payloads:
```json
{
  "topic": "Kelly Sizing Implementation",
  "phase": "PROPOSE" | "REBUTTAL" | "RESOLVE",
  "sender": "gemini" | "claude" | "user",
  "turn": 1,
  "proposal": "...",
  "rationale": "...",
  "code_diff_preview": "...",
  "git_hash": "a1b2c3d"
}
```

### C. Decision Matrix DB Log
Store decisions in `data/sentinel.db` (or a JSON matrix `data/decision_matrix.json` indexed by `topic`):
```json
{
  "topic": "Kelly Sizing Implementation",
  "decision": "APPROVED" | "REJECTED" | "ROLLEDBACK",
  "git_hash_before": "a1b2c3d",
  "git_hash_after": "f6g7h8i",
  "turns_to_decision": 2,
  "mttd_seconds": 45,
  "rationale": "...",
  "timestamp": "2026-07-15T05:00:00Z"
}
```

---

## 3. Futuristic Collaboration & Debate Web UI

We will add a new tab/pane in the dashboard labeled **"Co-Agent Cockpit"**:
- **Design Aesthetic**: Premium glassmorphism dark mode with glowing border animations (purple for Gemini, blue/orange for Claude).
- **Live Stream Terminal**: A real-time, terminal-like feed showing the active WebSocket chat/debate between Claude and Gemini as they happen.
- **User Intervention Panel**: 
  - A text input for the user to chat/interact directly with both agents in the middle of the debate.
  - Quick-action buttons: **"Force Approve"**, **"Force Decline"**, and **"Rollback Last Commit"**.

---

## 4. Implementation Steps for Claude

### Step 1: Create `debate_relay.py`
Build a simple asynchronous Python WebSocket server using `websockets` listening on `localhost:9000` to route messages between Claude, Gemini, and the Web UI.

### Step 2: Implement the Agent Client Loop
Within the self-improvement cycles (`improve.py`), connect to the WebSocket relay, debate topic proposals, listen for user overrides, and log outcomes to `sentinel.db`.

### Step 3: Add UI Views
Expose a `/debate-room` dashboard page or modal pane in `dashboard.html` that connects to the WebSocket server to render the live debate logs and capture user actions.
