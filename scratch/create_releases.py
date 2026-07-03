import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "essentialbit/fredai"

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {TOKEN}" if TOKEN else ""
}

releases_data = {
    "v1.3.12": {
        "name": "FredAI v1.3.12",
        "body": """## FredAI v1.3.12

### Changes
- feat: implement Phase 1 of FinBERT Sentiment Upgrade (#47)
  - Integrated Hugging Face's `ProsusAI/finbert` sequence classification model with lazy loading and capability-gated fallback to VADER on low-end hardware (RAM < 1GB like Raspberry Pi Zero) (closes #46).
  - Added `sentiment_model` columns to `signals` and `news_items` schemas/lightweight migrations in `memory_store.py`.
  - Integrated the gated scoring logic into `twitter_client.py` and `news_client.py`.
  - Added dependencies to `requirements.txt`.
"""
    },
    "v1.3.13": {
        "name": "FredAI v1.3.13",
        "body": """## FredAI v1.3.13

### Changes
- feat: per-story HQ-to-exchange geocoding for globe arcs (Phase 1 of #48) (#52)
  - Added robust corporate geocoding mapping news stories from corporate headquarters to stock exchanges.
  - Resolves coordinate references for primary world stock exchanges to draw dynamic arcs.
"""
    },
    "v1.3.14": {
        "name": "FredAI v1.3.14",
        "body": """## FredAI v1.3.14

### Changes
- docs: update README.md changelog for v1.3.11 (#53)
  - Sync README changelog block.
"""
    },
    "v1.3.15": {
        "name": "FredAI v1.3.15",
        "body": """## FredAI v1.3.15

### Changes
- feat: real per-story sentiment-colored globe arcs (Phase 2 of #48) (#54)
  - Draw interactive paths on the 3D globe connecting the corporate HQ to the exchange where the asset is traded.
  - Colored globe arcs by real-time FinBERT/VADER sentiment score (green for bullish, red for bearish, gray for neutral).
"""
    },
    "v1.3.16": {
        "name": "FredAI v1.3.16",
        "body": """## FredAI v1.3.16

### Changes
- feat: complete Phase 2 Globe Uplift with monitored node overlays, hotspot rings, and interactive details (Issue #48) (#55)
  - Elevates the 3D WebGL globe with monitored node overlays representing active server nodes.
  - Adds glowing hotspot rings around high-signal-density areas.
  - Enhances interactive details with popup info cards for geocoded stories.
"""
    },
    "v1.3.17": {
        "name": "FredAI v1.3.17",
        "body": """## FredAI v1.3.17

### Changes
- feat: implement Gmail export option for Google Workspace Integration (Issue #49)
  - Allows exporting financial briefing digests directly to Gmail for easy updates on standard consumer hardware.
"""
    },
    "v1.3.18": {
        "name": "FredAI v1.3.18",
        "body": """## FredAI v1.3.18

### Changes
- feat: landing page visual uplift and notification center (Issue #51)
  - Modernized dashboard design with upgraded Outfit/JetBrains Mono typography.
  - Integrated real-time central Notification Center for critical market alerts and agent messages.
  - Re-styled layout elements for responsive high-signal-density views.
"""
    }
}

def check_and_create_release(tag, data):
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{tag}"
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        print(f"Release for {tag} already exists on GitHub.")
        return
    elif r.status_code == 404:
        print(f"Creating release for {tag}...")
        create_url = f"https://api.github.com/repos/{REPO}/releases"
        payload = {
            "tag_name": tag,
            "name": data["name"],
            "body": data["body"],
            "draft": False,
            "prerelease": False
        }
        res = requests.post(create_url, json=payload, headers=headers)
        if res.status_code in (200, 201):
            print(f"Successfully created release for {tag}!")
        else:
            print(f"Failed to create release for {tag}: {res.status_code} - {res.text}")
    else:
        print(f"Error checking release for {tag}: {r.status_code} - {r.text}")

if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: GITHUB_TOKEN not found in .env file.")
        exit(1)
    for tag, data in sorted(releases_data.items()):
        check_and_create_release(tag, data)
