"""Sector classification + AI-generated per-ticker assessment (bull/bear
case, conviction, signal).

The static company-relationship graph and HQ-location data that used to
live here were cannibalized into dashboard.html's Globe (2026-07-04) --
they never earned their keep as a hand-maintained, non-comprehensive
edge list disconnected from the rest of Fred's signal stack. SECTORS/
SECTOR_COLORS and generate_assessment below are still genuinely reused
elsewhere (portfolio hover, /api/assessment, AI Universe context).
"""
import json
import re
from datetime import datetime


# ── SECTOR DEFINITIONS ───────────────────────────────────────────────────────
SECTORS = {
    "NVDA":"Semiconductors","AMD":"Semiconductors","INTC":"Semiconductors",
    "AVGO":"Semiconductors","QCOM":"Semiconductors","ARM":"Semiconductors",
    "AMAT":"Semiconductors","ASML":"Semiconductors","TSM":"Semiconductors","MRVL":"Semiconductors",
    "MSFT":"Cloud","AMZN":"Cloud","GOOGL":"Cloud","META":"Cloud","ORCL":"Cloud","IBM":"Cloud",
    "PLTR":"AI Software","AI":"AI Software","SNOW":"AI Software","CRM":"AI Software",
    "NOW":"AI Software","ADBE":"AI Software","DDOG":"AI Software","MDB":"AI Software",
    "SMCI":"AI Infra","VRT":"AI Infra","EQIX":"AI Infra","DLR":"AI Infra",
    "AMT":"AI Infra","CSCO":"AI Infra","ANET":"AI Infra",
    "CEG":"AI Energy","VST":"AI Energy","NRG":"AI Energy","NEE":"AI Energy",
    "ETR":"AI Energy","DUK":"AI Energy","SO":"AI Energy","CCJ":"AI Energy",
    "TSLA":"Robotics","ISRG":"Robotics","ABB":"Robotics","FANUY":"Robotics",
    "KEYS":"Robotics","ZBRA":"Robotics","ROK":"Robotics",
    "SOUN":"AI Pure-Play","BBAI":"AI Pure-Play","UPST":"FinTech",
    "PATH":"AI Pure-Play","RXRX":"Biotech",
    "AAPL":"Consumer Tech","NFLX":"Consumer Tech","SPOT":"Consumer Tech",
    "SNAP":"Consumer Tech","PINS":"Consumer Tech","RBLX":"Consumer Tech",
    "SPY":"ETF","QQQ":"ETF",
    "JPM":"Finance","GS":"Finance","BAC":"Finance",
    "BTC-USD":"Crypto","ETH-USD":"Crypto",
    "LMT":"Defence","RTX":"Defence","NOC":"Defence","GD":"Defence","BA":"Defence",
    "KTOS":"Defence","HII":"Defence","LDOS":"Defence","CACI":"Defence","SAIC":"Defence",
    "XOM":"Oil & Gas","CVX":"Oil & Gas","COP":"Oil & Gas","OXY":"Oil & Gas",
    "SLB":"Oil & Gas","EOG":"Oil & Gas","PSX":"Oil & Gas","VLO":"Oil & Gas",
    "MPC":"Oil & Gas","BP":"Oil & Gas",
    "MRNA":"Biotech","ILMN":"Biotech","NVAX":"Biotech","CRSP":"Biotech",
    "EDIT":"Biotech","BEAM":"Biotech","PACB":"Biotech","TMO":"Biotech",
    "V":"FinTech","MA":"FinTech","PYPL":"FinTech","SQ":"FinTech",
    "NU":"FinTech","SOFI":"FinTech","AFRM":"FinTech","COIN":"Crypto","HOOD":"FinTech",
    "UBER":"Autonomous","LYFT":"Autonomous","RIVN":"Autonomous","LCID":"Autonomous",
    "GM":"Automotive","F":"Automotive","MBLY":"Autonomous",
    # ASX
    "BHP.AX":"ASX Mining","RIO.AX":"ASX Mining","FMG.AX":"ASX Mining",
    "MIN.AX":"ASX Mining","LYC.AX":"ASX Mining","PLS.AX":"ASX Mining",
    "CBA.AX":"ASX Banks","WBC.AX":"ASX Banks","ANZ.AX":"ASX Banks","NAB.AX":"ASX Banks",
    "MQG.AX":"ASX Finance","QBE.AX":"ASX Finance",
    "CSL.AX":"ASX Healthcare","COH.AX":"ASX Healthcare","PME.AX":"ASX Healthcare",
    "WTC.AX":"ASX Tech","XRO.AX":"ASX Tech","REA.AX":"ASX Tech","SEK.AX":"ASX Tech",
    "WES.AX":"ASX Retail","WOW.AX":"ASX Retail","COL.AX":"ASX Retail","JBH.AX":"ASX Retail",
    "WDS.AX":"ASX Energy","STO.AX":"ASX Energy",
    "TCL.AX":"ASX Infrastructure",
    "VAS.AX":"ASX ETF","IOZ.AX":"ASX ETF","NDQ.AX":"ASX ETF",
}

SECTOR_COLORS = {
    "Semiconductors": "#9b59ff",
    "Cloud": "#00b4ff",
    "AI Software": "#00ff88",
    "AI Infra": "#f5a623",
    "AI Energy": "#ff3b5c",
    "Robotics": "#00e5cc",
    "AI Pure-Play": "#ff9500",
    "Finance": "#4a6380",
    "Consumer Tech": "#aaa",
    "ETF": "#666",
    "Crypto": "#f7931a",
    "Defence": "#8ba3b8",
    "Oil & Gas": "#f5a623",
    "Biotech": "#ff6b9d",
    "FinTech": "#00e5cc",
    "Automotive": "#aaaaff",
    "Autonomous": "#9b59ff",
    "ASX Mining":          "#f5a623",
    "ASX Banks":           "#00b4ff",
    "ASX Finance":         "#00e5cc",
    "ASX Healthcare":      "#ff6b9d",
    "ASX Tech":            "#00ff88",
    "ASX Retail":          "#9b59ff",
    "ASX Energy":          "#ff3b5c",
    "ASX Infrastructure":  "#8ba3b8",
    "ASX ETF":             "#4a6380",
}

# EDGES/EDGE_COLORS: kept here (unlike HQ/build_graph, which were removed
# 2026-07-04 along with the Graph page) because cascade_engine.py's
# forward-propagation alerting genuinely depends on this relationship data --
# a separate, real feature from the retired visualization.
# ── STATIC RELATIONSHIP EDGES ─────────────────────────────────────────────────
# (source, target, type, strength 1-10, description)
# Types: competitor | partner | customer | supplier | subsidiary | investor |
#        government | regulatory | ecosystem | musk-linked
EDGES = [
    # Semiconductor ecosystem
    ("NVDA", "AMD",   "competitor", 9,  "Direct GPU competitors — data center and consumer segments"),
    ("NVDA", "INTC",  "competitor", 7,  "Competing in AI accelerator and data center markets"),
    ("NVDA", "GOOGL", "competitor", 6,  "NVDA chips vs Google TPUs for AI training"),
    ("NVDA", "TSM",   "supplier",   9,  "TSMC manufactures all NVDA chips"),
    ("AMD",  "TSM",   "supplier",   9,  "TSMC manufactures AMD chips"),
    ("INTC", "AMAT",  "customer",   7,  "Intel uses AMAT equipment in fabs"),
    ("TSM",  "ASML",  "customer",   10, "TSMC requires ASML EUV lithography exclusively"),
    ("ASML", "TSM",   "supplier",   10, "ASML sole supplier of EUV machines to TSMC"),
    ("ASML", "INTC",  "customer",   8,  "Intel building Ohio fabs with ASML EUV"),
    ("ARM",  "NVDA",  "partner",    7,  "NVDA attempted ARM acquisition; uses ARM IP"),
    ("ARM",  "QCOM",  "customer",   8,  "Qualcomm licenses ARM architecture for Snapdragon"),
    ("ARM",  "AAPL",  "customer",   9,  "Apple Silicon (M-series) built on ARM architecture"),
    ("NVDA", "MSFT",  "partner",    9,  "Azure H100 clusters; Microsoft embedding NVDA AI"),
    ("NVDA", "AMZN",  "partner",    9,  "AWS Trainium vs H100; dual relationship"),
    ("NVDA", "META",  "partner",    8,  "Meta Llama trained on 100k+ H100 GPUs"),
    ("NVDA", "GOOGL", "partner",    7,  "Google Cloud NVDA GPU instances"),
    ("NVDA", "CEG",   "customer",   6,  "NVDA data centers need nuclear-powered clean power"),
    ("SMCI", "NVDA",  "partner",    9,  "Supermicro primary NVDA H100/H200 system integrator"),
    ("MRVL", "TSM",   "customer",   8,  "Marvell custom AI chips manufactured at TSMC"),
    # Cloud competition & partnerships
    ("MSFT", "AMZN",  "competitor", 9,  "Azure vs AWS — cloud market share war"),
    ("MSFT", "GOOGL", "competitor", 8,  "Azure vs GCP; Office vs Workspace"),
    ("AMZN", "GOOGL", "competitor", 7,  "AWS vs GCP in enterprise cloud"),
    ("MSFT", "META",  "competitor", 5,  "Competing AI assistants; Teams vs Workplace"),
    # Microsoft ecosystem
    ("MSFT", "SNOW",  "partner",    7,  "Azure partnership; Snowflake runs on Azure"),
    ("MSFT", "CRM",   "competitor", 6,  "Dynamics 365 vs Salesforce CRM"),
    ("MSFT", "DDOG",  "partner",    7,  "Datadog on Azure marketplace"),
    ("MSFT", "NOW",   "partner",    6,  "ServiceNow Azure integration"),
    ("MSFT", "PLTR",  "partner",    7,  "Palantir Azure Government Cloud"),
    # AI Software ecosystem
    ("PLTR", "AMZN",  "customer",   6,  "Palantir AWS government deployments"),
    ("SNOW",  "MSFT", "partner",    7,  "Snowflake Azure partnership"),
    ("SNOW",  "AMZN", "partner",    7,  "Snowflake AWS partnership"),
    ("SNOW",  "GOOGL","partner",    7,  "Snowflake GCP partnership"),
    ("ADBE",  "MSFT", "partner",    6,  "Adobe Creative Cloud Microsoft integration"),
    ("CRM",   "AMZN", "partner",    6,  "Salesforce AWS strategic partnership"),
    # Data centers & power
    ("EQIX", "MSFT",  "customer",   8,  "Microsoft colocates in Equinix data centers"),
    ("EQIX", "AMZN",  "customer",   8,  "Amazon AWS uses Equinix interconnect"),
    ("DLR",  "MSFT",  "customer",   7,  "Digital Realty partners with Azure"),
    ("VRT",  "MSFT",  "customer",   7,  "Vertiv power infrastructure for Azure"),
    ("VRT",  "AMZN",  "customer",   7,  "Vertiv power infrastructure for AWS"),
    ("CEG",  "MSFT",  "partner",    9,  "Microsoft 20yr nuclear power purchase agreement"),
    ("CEG",  "AMZN",  "partner",    7,  "Amazon data center nuclear power deal"),
    ("CEG",  "GOOGL", "partner",    6,  "Google clean energy nuclear deal with Constellation"),
    ("VST",  "AMZN",  "customer",   6,  "Amazon AWS power purchase from Vistra"),
    ("NEE",  "AMZN",  "partner",    6,  "Amazon renewable energy contracts"),
    ("CCJ",  "CEG",   "partner",    7,  "Uranium supplier to Constellation nuclear plants"),
    # ANET / networking
    ("ANET", "MSFT",  "customer",   8,  "Arista network switches in Azure data centers"),
    ("ANET", "META",  "customer",   8,  "Meta uses Arista in AI training clusters"),
    ("CSCO", "ANET",  "competitor", 7,  "Cisco vs Arista in data center switching"),
    # Tesla / EV ecosystem
    ("TSLA", "NVDA",  "competitor", 5,  "Tesla Dojo chip vs NVDA for autonomous AI"),
    ("TSLA", "PANASONIC", "partner", 8, "Panasonic Gigafactory battery joint venture"),
    # Finance sector
    ("JPM",  "MSFT",  "partner",    6,  "JPMorgan Azure cloud transformation"),
    ("GS",   "MSFT",  "partner",    5,  "Goldman Sachs Microsoft AI partnership"),
    # Government / regulatory
    ("NVDA", "NVDA",  "regulatory", 5,  "US export controls on H100/H200 to China"),
    ("ASML", "ASML",  "regulatory", 8,  "Netherlands export restrictions on EUV to China"),
    ("PLTR", "PLTR",  "government", 9,  "Palantir primary US Government AI contractor"),
    ("BBAI", "BBAI",  "government", 7,  "BigBear.ai US DoD and intelligence community"),
    # Musk ecosystem
    ("TSLA", "TSLA",  "musk-linked", 8, "Elon Musk CEO; xAI, X, SpaceX ecosystem"),
    # Australian context — US tech investing in Australia
    ("MSFT", "MSFT",  "australia",  6,  "Microsoft $5B Australian AI data center investment"),
    ("AMZN", "AMZN",  "australia",  6,  "Amazon AWS Australia regions"),
    ("GOOGL","GOOGL", "australia",  5,  "Google Cloud Australian infrastructure"),
    # ASX relationships
    ("BHP.AX",  "RIO.AX",  "competitor", 9,  "Direct competitors in global iron ore and copper markets"),
    ("BHP.AX",  "FMG.AX",  "competitor", 8,  "Iron ore competitors in Pilbara region"),
    ("RIO.AX",  "FMG.AX",  "competitor", 8,  "Iron ore competitors in Pilbara region"),
    ("BHP.AX",  "MIN.AX",  "competitor", 6,  "Competing lithium and nickel miners in WA"),
    ("BHP.AX",  "TSM",     "customer",   6,  "TSMC uses BHP copper in chip manufacturing"),
    ("BHP.AX",  "NVDA",    "ecosystem",  5,  "BHP data center uses NVDA for mining AI and simulation"),
    ("FMG.AX",  "NVDA",    "customer",   6,  "Fortescue Green Tech uses NVDA for AI optimisation"),
    ("FMG.AX",  "CEG",     "ecosystem",  5,  "Fortescue green hydrogen and nuclear power interest"),
    ("LYC.AX",  "NVDA",    "supplier",   7,  "Lynas supplies rare earths for NVDA chip magnets and motors"),
    ("LYC.AX",  "TSM",     "supplier",   6,  "Rare earth supplier to semiconductor manufacturers"),
    ("PLS.AX",  "TSLA",    "customer",   7,  "Pilbara Minerals lithium spodumene used in Tesla batteries"),
    ("PLS.AX",  "MIN.AX",  "competitor", 7,  "Competing Pilbara lithium producers"),
    ("MIN.AX",  "TSLA",    "customer",   6,  "Mineral Resources lithium to EV battery supply chain"),
    ("CSL.AX",  "MRNA",    "competitor", 6,  "Competing in plasma-derived therapies and vaccines"),
    ("CSL.AX",  "NVAX",    "competitor", 5,  "Competing in flu and COVID vaccines (CSL Seqirus)"),
    ("XRO.AX",  "MSFT",    "partner",    7,  "Xero Microsoft Azure partnership; Azure-hosted SaaS"),
    ("XRO.AX",  "CRM",     "competitor", 5,  "Xero vs Salesforce small business financial tools"),
    ("WTC.AX",  "MSFT",    "partner",    6,  "WiseTech Global Microsoft Azure infrastructure"),
    ("WTC.AX",  "AMZN",    "partner",    6,  "WiseTech Global AWS deployment"),
    ("MQG.AX",  "GS",      "competitor", 7,  "Macquarie Group competes with Goldman Sachs in infrastructure and M&A"),
    ("MQG.AX",  "JPM",     "competitor", 6,  "Macquarie vs JPMorgan in Asia-Pacific investment banking"),
    ("CBA.AX",  "MQG.AX",  "competitor", 6,  "Commonwealth Bank vs Macquarie in retail and business banking"),
    ("WBC.AX",  "CBA.AX",  "competitor", 8,  "Big 4 bank direct competitors in Australian retail banking"),
    ("ANZ.AX",  "CBA.AX",  "competitor", 8,  "Big 4 bank direct competitors in Australian retail banking"),
    ("NAB.AX",  "CBA.AX",  "competitor", 8,  "Big 4 bank direct competitors in Australian retail banking"),
    ("WDS.AX",  "STO.AX",  "competitor", 8,  "Woodside and Santos compete in Australian LNG and gas"),
    ("WDS.AX",  "XOM",     "competitor", 5,  "Competing in global LNG markets"),
    ("WDS.AX",  "BP",      "ecosystem",  6,  "BP had stake in Woodside assets (North West Shelf history)"),
    ("STO.AX",  "COP",     "partner",    6,  "Santos and ConocoPhillips joint ventures (APLNG, Darwin LNG)"),
    ("WES.AX",  "WOW.AX",  "competitor", 9,  "Wesfarmers (Coles divested) vs Woolworths in Australian retail duopoly"),
    ("COL.AX",  "WOW.AX",  "competitor", 9,  "Coles (Wesfarmers spin-off) vs Woolworths in supermarkets"),
    ("REA.AX",  "MSFT",    "partner",    5,  "REA Group Microsoft Azure digital real estate platform"),
    ("SEK.AX",  "MSFT",    "partner",    5,  "SEEK Microsoft Azure partnership for AI job matching"),
    ("COH.AX",  "ISRG",    "competitor", 5,  "Cochlear medical devices competes with Intuitive Surgical in specialised markets"),
    ("PME.AX",  "NVDA",    "customer",   7,  "Pro Medicus uses NVDA GPUs for AI radiology (Visage 7)"),
    ("TCL.AX",  "AMT",     "ecosystem",  5,  "Transurban and American Tower both in infrastructure/real assets"),
    ("NDQ.AX",  "QQQ",     "ecosystem",  9,  "BetaShares NDQ tracks Nasdaq 100 — same underlying as QQQ"),
    ("VAS.AX",  "SPY",     "ecosystem",  7,  "Vanguard ASX 300 ETF — Australian equivalent of SPY"),
]

EDGE_COLORS = {
    "competitor": "#ff3b5c",
    "partner": "#00ff88",
    "customer": "#00b4ff",
    "supplier": "#9b59ff",
    "subsidiary": "#f5a623",
    "investor": "#ff9500",
    "government": "#00e5cc",
    "regulatory": "#ff3b5c",
    "ecosystem": "#4a6380",
    "musk-linked": "#aaa",
    "australia": "#ff9500",
    "correlated": "#8ba3b8",  # cascade_engine.py's statistical (not hand-typed) relationship tier
}

_ai_assessment_cache: dict = {}
_ASSESS_TTL = 1800  # 30 min cache


def generate_assessment(symbol: str, news_items: list[dict], quote: dict,
                        technicals: dict, position: dict = None) -> dict:
    """Generate Fred's buy/sell/hold assessment for a symbol."""
    import time as _t
    now = _t.time()
    cached = _ai_assessment_cache.get(symbol)
    if cached and (now - cached["ts"]) < _ASSESS_TTL:
        return cached["data"]

    from agent import _provider, FRED_SYSTEM, DISCLAIMER_FOOTER

    news_text = "\n".join([
        f"  [{n.get('source','')}] {n.get('title','')} (sent={n.get('sentiment_score',0):.2f})"
        for n in (news_items or [])[:8]
    ])

    tech_text = ""
    if technicals:
        rsi = technicals.get("rsi14")
        sma20 = technicals.get("sma20")
        sma50 = technicals.get("sma50")
        vr = technicals.get("volume_ratio", 1)
        price = quote.get("price", 0)
        tech_text = (
            f"Price: ${price} | RSI(14): {rsi or 'N/A'} | "
            f"SMA20: {sma20 or 'N/A'} | SMA50: {sma50 or 'N/A'} | "
            f"Vol ratio: {vr}× avg"
        )

    port_text = ""
    if position:
        port_text = (
            f"User holds {position.get('shares',0)} shares @ ${position.get('avg_cost',0)} "
            f"avg cost — P&L: {position.get('pnl_pct',0):+.1f}%"
        )

    prompt = f"""Assess {symbol} and provide a signal. Respond ONLY as valid JSON, no markdown:

SYMBOL: {symbol}
PRICE: ${quote.get('price', 'N/A')} ({quote.get('change_pct', 0):+.2f}% today)
TECHNICALS: {tech_text or 'Not available'}
USER POSITION: {port_text or 'Not held'}

RECENT NEWS ({len(news_items or [])} items):
{news_text or 'No recent news found.'}

Return this exact JSON:
{{
  "signal": "BUY" | "SELL" | "HOLD" | "WATCH",
  "conviction": "HIGH" | "MEDIUM" | "LOW",
  "rationale": "2-3 sentences with specific data points. Frame as signal observation, not advice.",
  "bull_case": "One sentence on positive scenario.",
  "bear_case": "One sentence on risk scenario.",
  "key_catalysts": ["catalyst 1", "catalyst 2"],
  "time_horizon": "SHORT (< 3mo)" | "MEDIUM (3-12mo)" | "LONG (1yr+)",
  "disclaimer": "Not financial advice — informational signal only."
}}

Base signal on: news sentiment, technical position vs MAs/RSI, momentum, and known catalysts.
BUY = strong bullish signal | SELL = bearish signal | HOLD = no clear edge | WATCH = monitoring"""

    raw = _provider.complete(
        [{"role": "user", "content": prompt}],
        FRED_SYSTEM,
        tier="summary",
        max_tokens=600,
    )

    try:
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        result = json.loads(clean)
    except Exception:
        result = {
            "signal": "WATCH",
            "conviction": "LOW",
            "rationale": "Insufficient data for signal generation — monitoring.",
            "bull_case": "Price and signal data still loading.",
            "bear_case": "No assessment available yet.",
            "key_catalysts": [],
            "time_horizon": "MEDIUM (3-12mo)",
            "disclaimer": "Not financial advice — informational signal only.",
        }

    result["symbol"] = symbol
    result["generated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    _ai_assessment_cache[symbol] = {"ts": now, "data": result}
    return result
