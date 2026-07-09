"""
Tavily — provider-agnostic live-search grounding.

agent.py's grounding=True path was hardcoded to Gemini's native search
grounding, meaning live-search silently stops working entirely if Gemini
isn't the active provider (exactly what happened when Gemini's credits were
depleted this session). This gives agent.py a search layer that works
regardless of which provider ends up serving the completion.
"""
import requests

from config import TAVILY_API_KEY

_TAVILY_URL = "https://api.tavily.com/search"


def search_context(query: str, max_results: int = 3) -> str | None:
    """Returns a compact text block (answer + top result snippets) suitable
    for folding into a system prompt, or None if unavailable/no key set --
    never raises, since grounding is a best-effort enrichment, not a
    required part of completing a request."""
    if not TAVILY_API_KEY:
        return None
    try:
        r = requests.post(
            _TAVILY_URL,
            json={
                "query": query,
                "max_results": max_results,
                "include_answer": True,
                "search_depth": "basic",
            },
            headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        parts = []
        if data.get("answer"):
            parts.append(data["answer"])
        for res in data.get("results", [])[:max_results]:
            title, content = res.get("title", ""), res.get("content", "")
            if title or content:
                parts.append(f"- {title}: {content[:300]}")
        return "\n".join(parts) if parts else None
    except Exception:
        return None
