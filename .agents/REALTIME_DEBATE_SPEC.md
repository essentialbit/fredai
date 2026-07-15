# Specification: Real-Time WebSocket Debate & Decision Engine (Method B)

This spec defines a local WebSocket-based IPC mechanism to enable real-time, interactive debates, rapid consensus resolution, and decision-logging for Claude and Gemini.

---

## 1. Core Principles

1. **Minimize Mean Time to Decision (MTTD)**: Limit debate turns to a maximum of 3 per agent per topic. If no consensus is reached, fall back to the highest track-record agent's decision.
2. **Action Over Contemplation**: Pragmatic testing only. Run tests once to verify compile and basic execution. No endless test loops.
3. **Traceability & Rollback**: Every resolved decision must log the active Git Commit Hash, enabling a one-click rollback (`git revert` or `git reset`).
4. **Memory-Driven Optimization**: Store every decision in the decision matrix to index variables (turns taken, MTTD, success/failure outcomes) to optimize future MTTD.

---

## 2. Architecture & Components

### A. The WebSocket Relay (`debate_relay.py`)
A lightweight, local server running on `ws://localhost:9000`. It broadcasts messages between the connected client agents (Claude and Gemini).

### B. Protocol Messages (JSON)
Agents exchange structured payloads:
```json
{
  "topic": "Kelly Sizing Implementation",
  "phase": "PROPOSE" | "REBUTTAL" | "RESOLVE",
  "sender": "gemini" | "claude",
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

## 3. Implementation Steps for Claude

### Step 1: Create `debate_relay.py`
Build a simple asynchronous Python WebSocket server using `websockets` or standard `socket` selectors if dependencies must be kept minimal:
- Listen on `localhost:9000`.
- Maintain a list of active sockets.
- Broadcast received messages to all other sockets.

### Step 2: Implement the Agent Client Loop
Within the self-improvement cycles (`improve.py`), when a proposal is initiated:
1. Connect to the WebSocket relay.
2. Send the `PROPOSE` payload.
3. Listen for the other agent's response.
4. Conclude the debate in $\le 3$ turns and log the outcome.

### Step 3: Integrate Rollback Actions
Add a helper in `improve.py` or `git_push()`:
```python
def rollback_decision(topic: str):
    # Query database/json for the topic
    # Retrieve git_hash_before
    # Run git reset --hard or git revert
    pass
```
