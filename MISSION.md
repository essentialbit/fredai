# FredAI — Mission: World's First Financial Super Intelligence

> *"Every 6-hour cycle is a step toward the most intelligent financial mind ever built."*

---

## The Mission

Build the world's first **Financial Super Intelligence (FSI)** — an AI that doesn't merely aggregate market data but develops a deep, causal, self-improving understanding of global financial systems. Fred must eventually outthink every Bloomberg terminal, every quant desk, and every financial analyst on Earth — running on everyday hardware, free to anyone, improving itself autonomously every 6 hours.

This is not a dashboard project. This is a civilisational bet on open, democratised financial intelligence.

---

## FSI Capability Roadmap

Each level unlocks the next. No level is skipped.

### L1 — Signal Intelligence ✅ (current)
*Aware of what the market is saying.*

- Multi-source real-time sentiment (X/Twitter, news, RSS)
- VADER financial sentiment scoring
- Live price data (yfinance, 26+ assets)
- 4-hour Claude-powered briefings
- Portfolio P&L tracking, multi-user auth
- Obsidian vault integration

**Unlocks:** Raw inputs exist. Now Fred needs to see patterns across them.

---

### L2 — Pattern Intelligence 🔄 (in progress)
*Recognises recurring structures across signals, assets, and time.*

- FinBERT sentiment (finance-domain NLP, replaces VADER)
- Cross-asset correlation matrix (rolling, dynamic)
- Options flow anomaly detection (unusual call/put activity)
- SEC insider trading filings (Form 4 — who's buying their own stock?)
- Fear & Greed Index integration (CNN Business API)
- Reddit sentiment (r/wallstreetbets, r/investing)
- Earnings calendar with pre/post signal analysis
- Signal deduplication and influence weighting (high-follower accounts)
- Short interest tracking (Finviz)
- Bitcoin on-chain metrics (Glassnode free tier)

**Unlocks:** Fred sees patterns. Now Fred needs to predict where patterns lead.

---

### L3 — Predictive Intelligence 🔲
*Anticipates market moves before they happen.*

- Backtesting framework: did Fred's signals predict price? (ground truth loop)
- Anomaly detection on signal volume spikes (ML-based)
- Macro regime detection (risk-on/risk-off, inflation/deflation, rate cycles)
- Earnings surprise prediction from pre-earnings signal patterns
- Sentiment reversal early warning (bearish→bullish flip detection)
- Google Trends financial keyword correlation
- FRED API macro indicators (CPI, PMI, unemployment, yield curve)
- Commodity futures curve analysis (contango/backwardation)
- Seasonal pattern recognition (Santa rally, September effect, etc.)

**Unlocks:** Fred predicts. Now Fred needs to *reason* about why.

---

### L4 — Reasoning Intelligence 🔲
*Understands causation, not just correlation.*

- Multi-agent market debate (Bull Agent vs Bear Agent, synthesised by Arbiter)
- Causal attribution ("BTC fell because: Fed minutes + CPI surprise, not crypto-native")
- Hypothesis testing loop (Fred proposes thesis → tests against history → updates)
- SEC 10-K / 10-Q deep analysis (EDGAR full-text, automated financial ratio extraction)
- 13F institutional positioning (what are Berkshire, Renaissance, Bridgewater holding?)
- Options chain visualisation (put/call ratio, IV surface, max pain)
- Credit default swap spread monitoring
- Central bank language semantic analysis (Fed/RBA/ECB statement deltas)
- Portfolio VaR, Sharpe, max drawdown, Kelly criterion sizing

**Unlocks:** Fred reasons. Now Fred needs a model of the whole world.

---

### L5 — World Model Intelligence 🔲
*Maintains a living model of the global financial system.*

- Cross-market contagion tracking (when EM debt moves, what follows?)
- Alternative data: satellite imagery (shipping, retail carpark occupancy)
- Alternative data: job listing trends (company hiring = growth signal)
- Alternative data: patent filings, GitHub commit velocity
- Private fine-tuned financial LLM (trained on signal history + outcomes)
- Multi-agent swarm: specialised agents per sector (Tech, Energy, Financials, Macro)
- Geopolitical risk scoring (news clustering by conflict zone, sanctions)
- Supply chain stress indicators (Baltic Dry Index, container shipping rates)
- Real-time 13F delta tracking (what changed vs last quarter)

**Unlocks:** Fred has a world model. Now Fred directs its own research.

---

### L6 — Super Intelligence 🔲
*Self-directing. Discovers edges before consensus forms.*

- Autonomous research agenda: Fred decides what to study next without prompting
- Novel signal discovery: Fred proposes new data sources and tests their predictive value
- Autonomous portfolio recommendation engine (with full risk disclosure and backtested track record)
- Edge detection before consensus: signals that predict moves 24-72h before analysts catch up
- Self-improving prompts: Fred rewrites its own briefing templates based on outcome accuracy
- Cross-instance learning: multiple deployed Freds share discovered edges (with privacy)
- Real-time hypothesis market: Fred bets confidence on predictions, tracks accuracy over time
- Institutional-grade risk model (comparable to internal Goldman / Bridgewater risk systems)

---

## Current Level Assessment

**We are at: L1 complete → L2 in active development**

### L1 Completion checklist
- [x] X/Twitter signal scraping
- [x] VADER sentiment scoring
- [x] yfinance price data (26+ assets)
- [x] 4h Claude briefings
- [x] Multi-user portfolio/watchlist
- [x] APScheduler 6h cycle
- [x] Autonomous self-improvement loop (R&D)
- [x] Device installer (macOS/Linux/Windows/Pi)
- [x] CI/CD pipeline (multi-arch Docker, GitHub Releases)
- [x] Community engagement system

### L2 Priority queue (next implementations)
- [x] FinBERT sentiment (huggingface `ProsusAI/finbert`) — merged #47
- [x] Fear & Greed Index (CNN Business) — merged #25 (closes #18)
- [x] SEC insider trading Form 4 feed (EDGAR) — merged #81 (closes #10)
- [x] Cross-asset rolling correlation matrix — merged #79 (closes #11)
- [x] Signal accuracy backtesting scaffold — merged #27 (closes #9), v2 in #118 (closes #108)
- [ ] Reddit sentiment (PRAW or Pushshift) — code-complete, PR #122 open awaiting merge (closes #58)
- [ ] Options flow anomaly (Unusual Whales free API) — code-complete, PR #128 open awaiting merge (closes #12)
- [x] Short interest (Finviz scrape) — merged #78 (closes #21)

All 8 items are code-complete as of 2026-07-09; 6 are merged to `main`, 2 (Reddit, Options) sit in open PRs awaiting a merge pass. L2 is not "complete" until those two land — track via merged PRs, not issue-close counts (several L2-labelled issues were closed as duplicate-cleanup, not real completions).

---

## Guiding Principles for All R&D Decisions

1. **FSI-first**: Every improvement must advance Fred toward a higher intelligence level. Cosmetic or administrative work is deprioritised unless it unblocks FSI capability.

2. **Compounding over isolated features**: Prefer improvements that build on existing capabilities (e.g. FinBERT builds on existing signal pipeline) over standalone additions that don't connect to anything.

3. **Leverage freely available technology**: Open models (HuggingFace), free APIs (EDGAR, FRED, CoinGecko, Fear&Greed), open research (arXiv finance papers) are the fuel. Fred must be the most capable free financial AI, not the most expensive.

4. **Signal quality over quantity**: 50 accurate, diverse signals beat 500 noisy duplicates. Every new signal source must prove predictive value within 30 days or be removed.

5. **Measurability is non-negotiable**: Every intelligence improvement must be testable. If we can't measure whether it made Fred smarter, it's not FSI progress — it's speculation.

6. **Everyday hardware**: Fred must run on a Raspberry Pi 4. Super Intelligence that requires a $10k GPU cluster is not democratised intelligence.

7. **Minimalist, high-signal UI (added 2026-07-02)**: Every screen should show less, not more — and what it shows should be real, high-value signal, not decorative noise. A page dense with jargon-badges, redundant simultaneous animations, or cosmetic "telemetry" copy is not sophisticated, it's cluttered — a genuinely sophisticated finance professional wants the fewest elements that convey the most, not a busy cockpit. Any number presented as a signal (a confidence score, an impact %, a rating) must be a real computed value per the existing anti-hallucination rule (agent.py's FRED_SYSTEM) — never a decorative placeholder invented for visual effect. When adapting UI ideas from external concepts, keep the interaction depth and visual craft, prune the verbosity.

---

## How the R&D Cycle Advances the Mission

Every 6-hour improvement cycle:
1. Reads this document to establish the current FSI level
2. Evaluates the backlog against FSI-advancement criteria
3. Picks the highest-impact, feasible L2+ capability to implement
4. Runs it through ClaudeCodeAgent
5. Commits, tags, releases
6. Updates this document's Level 2 checklist when items complete

When all L2 items are complete, Fred declares L2 and shifts focus to L3.

---

*Fred is not a dashboard. Fred is becoming the world's most intelligent financial mind.*
*One cycle at a time. One capability at a time. No shortcuts.*

---

## FSI Master Plan: Scaling to Institutional & Retail Excellence

To capture both the institutional depth of top-tier quants (Goldman Sachs, Citadel) and the accessible utility of everyday retail traders, FredAI must continually evolve along both aesthetic and technical frontiers. 

### 1. What a Goldman Sachs/Citadel Analyst Demands
* **Mathematical Rigor**: Moving beyond raw sentiment scores to covariance matrices, rolling beta estimation, Sharpe/Sortino ratios, and real-time Value at Risk (VaR) calculations.
* **Causal Attribution (L4)**: Knowing *why* a move happened. Attributing stock performance to macroeconomic cycles (CPI, FOMC statement deltas) vs micro events (earnings, insider trading).
* **Options Flow and IV Surfaces (L4)**: Monitoring unusual options sweep activity, put/call volume ratios, and visualizing the Implied Volatility (IV) surface to detect institutional positioning.
* **Alternative Data (L5)**: Scraping corporate actions, insider purchases (Form 4), patent filings, and GitHub commit velocities.

### 2. What an OpenAI/Google AI Architect Demands
* **Verifiable Accuracy (L3)**: Strong backtesting ground-truth loops ensuring that sentiment signals actually predict subsequent price action, keeping LLMs grounded.
* **Adversarial Debating (L4)**: Multi-agent debate loops where specialised Bull and Bear agents argue current proposals with a neutral Arbiter agent writing the summary.
* **Domain-Specific Embedding (L2)**: Standardizing on FinBERT or locally-running financial LLM models rather than raw VADER scoring.

### 3. What the Everyday Retail Trader Demands
* **Aesthetic Superiority**: Clean, dark glassmorphic dashboards that summarize complex signal networks at a glance, eliminating clutter.
* **Actionable Alerts**: Instant push notifications or Obsidian-synced briefings highlighting trading setups before they happen.
* **Democratised Deployment**: Runs on a $35 Raspberry Pi Zero/4 or low-cost cloud VM without requiring a cluster of expensive GPUs.

### 4. Next Implementation Steps (Q3 2026)
1. **Adversarial Multi-Agent Debates (L4)**: Create dedicated Bull/Bear agent personas for the debate cycle to simulate quantitative peer review.
2. **FinBERT / Llama-3 Sentiment Upgrade (L2)**: Migrate the current RSS and Twitter scraping pipelines to use finance-specific models.
3. **Advanced Risk and Portfolio Sizing (L3/L4)**: Implement Kelly Criterion and Sharpe ratio tracking in the portfolio module.
4. **SEC EDGAR Insider Trading Parser (L2/L4)**: Automate parsing of Form 4 filings for immediate ticker alerting.*
