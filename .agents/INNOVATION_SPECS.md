# Collaboration Briefing: Innovation Specs & Credit Fallbacks

Hello Claude! Gemini here. The user has reassigned development tasks to you, while I run validation loops and suggest architectural upgrades. 

Below is the brief on API key alternatives and step-by-step implementation suggestions for the new innovations.

---

## 1. Cloud AI Backend Alternatives (Depleted Credits)

The cloud Gemini API key is currently out of prepay credits (`429 RESOURCE_EXHAUSTED`). Please use the following fallbacks during development and testing:

1. **Local Ollama**: Fred is configured to use local Ollama (`llama3.2`) on port 11434 if cloud keys fail and the user has consented.
2. **Groq (Free Cloud Inference)**: Add `GROQ_API_KEY` to the `.env` file. Fred already has built-in support (`_groq_complete`) to fall back to Llama 3 on Groq's high-speed cloud endpoint.
3. **xAI Grok (Paid Alternative)**: Add `XAI_API_KEY` to `.env` to route requests to Grok (`_grok_complete`).

---

## 2. Innovation Implementation Roadmaps

### A. Kelly Criterion Position Sizing Engine (L2)
* **Goal**: Dynamically calculate suggested portfolio trade allocations based on historical prediction edges.
* **Suggested Steps**:
  1. Add a utility module `kelly_sizing.py`.
  2. Implement the formula:
     ```python
     def calculate_kelly(win_rate: float, win_loss_ratio: float) -> float:
         # f* = p - (q / b)
         p = win_rate
         q = 1.0 - p
         b = win_loss_ratio
         kelly = p - (q / b)
         return max(0.0, kelly) # Never recommend shorting or negative size
     ```
  3. Query `backtesting_engine.py::get_accuracy_report()` to fetch the real historical win rate (\(p\)) of the signal source for the asset's category.
  4. Expose the calculated value via GET `/api/portfolio/kelly` and display it next to holdings.

### B. Options Volatility Smile & Skew Tracker (L2)
* **Goal**: Flag defensive options activity (OOTM put volume spikes) representing tail-risk hedging.
* **Suggested Steps**:
  1. Leverage the yfinance option chain module: `ticker.option_chain(date)`.
  2. Find implied volatilities (IV) of out-of-the-money puts and calls at the nearest expiration date.
  3. Compute Skewness:
     ```python
     skew = put_iv_ootm - call_iv_ootm
     ```
  4. Trigger a warning event on the Situational Room HUD log if the skew value spikes beyond its 20-day average by 2 standard deviations.

### C. Automated Regime-Switching Classifier (L2)
* **Goal**: Detect changes in market trend mechanics (e.g. Range-bound vs. Trending) to adjust technical alerts.
* **Suggested Steps**:
  1. Calculate ADX (Average Directional Index) or rolling ATR (Average True Range) inside a new `regime_detector.py`.
  2. Map states: `TRENDING` (ADX > 25) vs. `MEAN_REVERTING` (ADX <= 25).
  3. Expose state to the Technical Alerts processor (`run_technical_alerts`) to prioritize breakout alerts in trending markets and RSI overbought/oversold alerts in mean-reverting markets.
