"""Open-source engineering velocity signal (FSI L5, issue #208) -- weekly
commit-count and contributor-count trend for a small curated set of publicly
traded, open-source-native companies where the ticker maps unambiguously to
one flagship repo (the company's core product literally is the named repo,
unlike picking a single repo to represent a diversified mega-cap).

GitHub's public REST API needs no signup for read-only public-repo data
(same trust boundary as this project's own CI/release flow, which already
shells out to `gh`) and the anonymous 60/hr rate limit comfortably covers a
daily refresh of 6 repos.
"""
import statistics
import time

import requests

TRACKED_REPOS = {
    "MDB": ("mongodb", "mongo"),
    "ESTC": ("elastic", "elasticsearch"),
    "GTLB": ("gitlab-org", "gitlab"),
    "HCP": ("hashicorp", "terraform"),
    "CFLT": ("apache", "kafka"),
    "NET": ("cloudflare", "workerd"),
}

_CACHE_TTL_S = 86400  # 24h, daily cron -- matches jobless-claims/EPU macro badges
_cache: dict = {}  # ticker -> {"computed_at": float, "data": dict}

_HEADERS = {"Accept": "application/vnd.github+json"}
_TIMEOUT_S = 15


def fetch_commit_activity(owner: str, repo: str) -> list[int] | None:
    """Weekly total commit counts over the trailing 52 weeks, oldest first.
    GitHub caches these stats server-side and returns 202 with an empty body
    while a first-time computation is in flight -- retry once after a short
    delay, matching GitHub's own documented pattern."""
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/commit_activity"
    for attempt in range(2):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        except requests.RequestException:
            return None
        if r.status_code == 200:
            weeks = r.json()
            if not weeks:
                return None
            return [w["total"] for w in weeks]
        if r.status_code == 202 and attempt == 0:
            time.sleep(3)
            continue
        return None
    return None


def fetch_contributor_count(owner: str, repo: str) -> int | None:
    """Total contributor count via the Link header's last-page number
    (per_page=1 keeps this to a single cheap request instead of paginating
    the full contributor list)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contributors"
    try:
        r = requests.get(
            url, headers=_HEADERS, timeout=_TIMEOUT_S,
            params={"per_page": 1, "anon": "true"},
        )
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    link = r.headers.get("Link", "")
    for part in link.split(","):
        if 'rel="last"' in part:
            try:
                return int(part.split("page=")[-1].split(">")[0])
            except (ValueError, IndexError):
                break
    data = r.json()
    return len(data) if isinstance(data, list) else None


def _trend(series: list[float]) -> dict | None:
    """Same shape as copper_gold_ratio.py/bitcoin_onchain_client.py's
    _trend() -- rolling z-score/direction vs. the trailing window, excluding
    the latest point from its own baseline."""
    if len(series) < 8:
        return None
    latest = series[-1]
    baseline = series[:-1]
    mean = statistics.fmean(baseline)
    stdev = statistics.pstdev(baseline)
    z = (latest - mean) / stdev if stdev else 0.0
    if z > 0.5:
        direction = "rising"
    elif z < -0.5:
        direction = "falling"
    else:
        direction = "stable"
    return {"latest": round(latest, 2), "mean": round(mean, 2), "z_score": round(z, 2), "direction": direction}


def compute_velocity_snapshot(ticker: str) -> dict | None:
    """{"ticker", "owner_repo", "weekly_commits_4wk_avg", "trend_52wk",
    "contributor_count"}, or None if the ticker isn't tracked or GitHub's
    stats endpoint has no data yet."""
    repo = TRACKED_REPOS.get(ticker.upper())
    if not repo:
        return None
    owner, name = repo
    weeks = fetch_commit_activity(owner, name)
    if not weeks or len(weeks) < 8:
        return None

    trend_52wk = _trend([float(w) for w in weeks])
    if trend_52wk is None:
        return None
    recent_4wk_avg = statistics.fmean(weeks[-4:])
    contributor_count = fetch_contributor_count(owner, name)

    return {
        "ticker": ticker.upper(),
        "owner_repo": f"{owner}/{name}",
        "weekly_commits_4wk_avg": round(recent_4wk_avg, 1),
        "trend_52wk": trend_52wk,
        "contributor_count": contributor_count,
    }


def get_velocity_snapshot(ticker: str, force: bool = False) -> dict | None:
    """Cached accessor -- recomputes at most once per _CACHE_TTL_S per ticker.
    Tracks the previous cached contributor_count so a fresh snapshot can
    report a delta once one is available (resets on process restart, same
    as every other in-memory macro/velocity cache in this codebase)."""
    ticker = ticker.upper()
    if ticker not in TRACKED_REPOS:
        return None
    now = time.time()
    entry = _cache.get(ticker)
    if not force and entry and now - entry["computed_at"] <= _CACHE_TTL_S:
        return entry["data"]

    prev_contributor_count = entry["data"]["contributor_count"] if entry and entry["data"] else None
    data = compute_velocity_snapshot(ticker)
    if data is None:
        return entry["data"] if entry else None

    if prev_contributor_count is not None and data["contributor_count"] is not None:
        data["contributor_count_delta"] = data["contributor_count"] - prev_contributor_count
    else:
        data["contributor_count_delta"] = None

    _cache[ticker] = {"computed_at": now, "data": data}
    return data
