# Contributing to FredAI

Thank you for your interest in making Fred better. Contributions of all kinds are welcome — bug fixes, new data sources, UI improvements, documentation, and ideas.

## Before you start

- Check [existing issues](https://github.com/essentialbit/fredai/issues) to avoid duplicating work
- For large features, open a [Discussion](https://github.com/essentialbit/fredai/discussions) first to align on direction
- Fred has a specific design philosophy: **simple to self-host, zero cloud lock-in, your data stays yours**. Keep that in mind when proposing features

## Development setup

```bash
git clone https://github.com/essentialbit/fredai.git
cd fredai
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add at minimum ANTHROPIC_API_KEY
python3 main.py
```

## Project structure (quick map)

| File | Change it when... |
|------|--------------------|
| `main.py` | Adding/modifying routes or scheduler jobs |
| `news_client.py` | Adding a new news source or geo-coordinate |
| `market_data.py` | Fixing or extending market data fetching |
| `technical_alerts.py` | Adding a new technical indicator alert |
| `installer.py` | Improving native shortcut creation |
| `templates/dashboard.html` | Changing the main dashboard UI |
| `templates/news.html` | Changing the news/globe/video page |
| `agent.py` | Changing Fred's AI behaviour |

**Do not modify `soul.md`** — it defines Fred's personality and operating values.

## Code style

- No comments unless the WHY is non-obvious (skip comments explaining *what* the code does)
- No trailing summaries in functions
- Match the existing dark finance theme: `#03080f` background, `#00ff88` positive, `#ff3b5c` negative, `#00b4ff` accent
- All API keys come from `config.py` / environment — never hardcode them
- SQLite only — no external databases
- Keep PRs focused: one feature or fix per PR

## Adding a news source

1. Add an entry to `MACRO_FEEDS` in `news_client.py`:
   ```python
   {"url": "https://example.com/rss", "source": "Source Name", "category": "market"},
   ```
   Valid categories: `market`, `central_bank`, `macro`, `geopolitical`, `ai`

2. Add geo-coordinates to `SOURCE_COORDINATES`:
   ```python
   "Source Name": (lat, lng, "City, Country"),
   ```

3. Test it: `python3 -c "from news_client import MACRO_FEEDS; print(len(MACRO_FEEDS), 'feeds')`

## Pull request checklist

- [ ] `python3 -c "from main import app; print('Import OK')"` passes
- [ ] No hardcoded API keys or secrets
- [ ] No new external database dependencies
- [ ] `.env.example` updated if you added a new env var
- [ ] PR description explains *what* and *why* (not a line-by-line summary)

## Reporting bugs

Use the [bug report template](https://github.com/essentialbit/fredai/issues/new?template=bug_report.md). Include:
- Your OS and Python version
- Steps to reproduce
- What you expected vs what happened
- Relevant log output (check your terminal or `logs/`)

## Code of Conduct

Be direct, be constructive, be kind. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
