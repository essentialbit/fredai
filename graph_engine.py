"""Stock Relationship Intelligence Engine.

Builds a force-directed knowledge graph of:
  - Company relationships (competitor/partner/subsidiary/customer/supplier)
  - Corporate locations (HQ lat/lng for world map)
  - Sector clustering
  - AI ecosystem connections
  - Government / regulatory relationships

Claude augments with dynamic discovery. Static edges handle known facts.
"""
import json
import re
import time
from datetime import datetime

# ── HQ LOCATIONS (lat, lng, city, country) ───────────────────────────────────
HQ = {
    # Semiconductors
    "NVDA":  (37.3688, -122.0363, "Santa Clara, CA", "USA"),
    "AMD":   (37.3826, -122.0130, "Santa Clara, CA", "USA"),
    "INTC":  (37.3875, -121.9630, "Santa Clara, CA", "USA"),
    "AVGO":  (37.4220, -122.0841, "Palo Alto, CA", "USA"),
    "QCOM":  (32.9031, -117.2013, "San Diego, CA", "USA"),
    "ARM":   (51.5167, -0.7667,   "Cambridge", "UK"),
    "AMAT":  (37.3887, -121.9779, "Santa Clara, CA", "USA"),
    "ASML":  (51.4143, 5.3750,    "Veldhoven", "Netherlands"),
    "TSM":   (24.7678, 120.9964,  "Hsinchu", "Taiwan"),
    "MRVL":  (37.3688, -122.0363, "Santa Clara, CA", "USA"),
    # Cloud & Hyperscalers
    "MSFT":  (47.6423, -122.1302, "Redmond, WA", "USA"),
    "AMZN":  (47.6062, -122.3321, "Seattle, WA", "USA"),
    "GOOGL": (37.4220, -122.0841, "Mountain View, CA", "USA"),
    "META":  (37.4848, -122.1481, "Menlo Park, CA", "USA"),
    "ORCL":  (37.5309, -122.2913, "Austin, TX", "USA"),
    "IBM":   (41.1182, -73.7262,  "Armonk, NY", "USA"),
    # AI Software
    "PLTR":  (34.0221, -118.4958, "Denver, CO", "USA"),
    "AI":    (37.3875, -122.0282, "Redwood City, CA", "USA"),
    "SNOW":  (37.8715, -122.2747, "San Mateo, CA", "USA"),
    "CRM":   (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "NOW":   (37.4030, -121.9700, "Santa Clara, CA", "USA"),
    "ADBE":  (37.3319, -121.8939, "San Jose, CA", "USA"),
    "DDOG":  (40.7589, -73.9851,  "New York, NY", "USA"),
    "MDB":   (40.7589, -73.9851,  "New York, NY", "USA"),
    # AI Infrastructure
    "SMCI":  (37.3688, -121.9641, "San Jose, CA", "USA"),
    "VRT":   (43.0481, -76.1474,  "Columbus, OH", "USA"),
    "EQIX":  (37.5485, -122.0597, "Redwood City, CA", "USA"),
    "DLR":   (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "AMT":   (42.3601, -71.0589,  "Boston, MA", "USA"),
    "CSCO":  (37.4080, -121.9709, "San Jose, CA", "USA"),
    "ANET":  (37.3875, -122.0170, "Santa Clara, CA", "USA"),
    # AI Energy
    "CEG":   (41.8827, -87.6233,  "Chicago, IL", "USA"),
    "VST":   (32.7767, -96.7970,  "Dallas, TX", "USA"),
    "NRG":   (29.7604, -95.3698,  "Houston, TX", "USA"),
    "NEE":   (25.7617, -80.1918,  "Juno Beach, FL", "USA"),
    "ETR":   (29.9511, -90.0715,  "New Orleans, LA", "USA"),
    "DUK":   (35.2271, -80.8431,  "Charlotte, NC", "USA"),
    "SO":    (33.7490, -84.3880,  "Atlanta, GA", "USA"),
    "CCJ":   (52.1579, -106.6700, "Saskatoon", "Canada"),
    # Robotics
    "TSLA":  (30.2185, -97.6319,  "Austin, TX", "USA"),
    "ISRG":  (37.3875, -122.0580, "Sunnyvale, CA", "USA"),
    "ABB":   (47.3769, 8.5417,    "Zurich", "Switzerland"),
    "FANUY": (35.0116, 138.5858,  "Yamanashi", "Japan"),
    "KEYS":  (37.3875, -122.0170, "Santa Rosa, CA", "USA"),
    "ZBRA":  (42.0334, -87.9273,  "Lincolnshire, IL", "USA"),
    "ROK":   (43.0481, -87.9062,  "Milwaukee, WI", "USA"),
    # AI Pure-Plays
    "SOUN":  (37.5485, -122.0597, "Santa Clara, CA", "USA"),
    "BBAI":  (38.9072, -77.0369,  "Columbia, MD", "USA"),
    "UPST":  (37.4030, -122.0500, "San Mateo, CA", "USA"),
    "PATH":  (40.7589, -73.9851,  "New York, NY", "USA"),
    "RXRX":  (37.7749, -122.4194, "San Francisco, CA", "USA"),
    # Market ETFs & Finance
    "SPY":   (40.7128, -74.0060,  "New York, NY", "USA"),
    "QQQ":   (40.7128, -74.0060,  "New York, NY", "USA"),
    "JPM":   (40.7128, -74.0060,  "New York, NY", "USA"),
    "GS":    (40.7128, -74.0060,  "New York, NY", "USA"),
    "BAC":   (35.2271, -80.8431,  "Charlotte, NC", "USA"),
    # Crypto
    "BTC-USD": (37.7749, -122.4194, "Decentralized", "Global"),
    "ETH-USD": (37.7749, -122.4194, "Decentralized", "Global"),
    # Consumer Tech
    "AAPL":  (37.3318, -122.0312, "Cupertino, CA", "USA"),
    "NFLX":  (37.3382, -121.8863, "Los Gatos, CA", "USA"),
    "SPOT":  (59.3293, 18.0686,   "Stockholm", "Sweden"),
    "SNAP":  (34.0195, -118.4912, "Santa Monica, CA", "USA"),
    "PINS":  (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "RBLX":  (37.3875, -122.0170, "San Mateo, CA", "USA"),
    # Defence
    "LMT":  (38.9072, -77.0369,  "Bethesda, MD", "USA"),
    "RTX":  (41.7658, -72.6851,  "Arlington, VA", "USA"),
    "NOC":  (34.0522, -118.2437, "Falls Church, VA", "USA"),
    "GD":   (38.9072, -77.0369,  "Reston, VA", "USA"),
    "BA":   (47.6062, -122.3321, "Arlington, VA", "USA"),
    "KTOS": (32.7767, -96.7970,  "San Diego, CA", "USA"),
    "HII":  (36.8468, -76.2951,  "Newport News, VA", "USA"),
    "LDOS": (38.9072, -77.0369,  "Reston, VA", "USA"),
    "CACI": (38.9072, -77.0369,  "Reston, VA", "USA"),
    "SAIC": (38.9072, -77.0369,  "Reston, VA", "USA"),
    # Oil & Gas
    "XOM":  (32.7767, -96.7970,  "Spring, TX", "USA"),
    "CVX":  (37.8271, -122.2905, "San Ramon, CA", "USA"),
    "COP":  (29.7604, -95.3698,  "Houston, TX", "USA"),
    "OXY":  (29.7604, -95.3698,  "Houston, TX", "USA"),
    "SLB":  (29.7604, -95.3698,  "Houston, TX", "USA"),
    "EOG":  (29.7604, -95.3698,  "Houston, TX", "USA"),
    "PSX":  (29.7604, -95.3698,  "Houston, TX", "USA"),
    "VLO":  (29.4241, -98.4936,  "San Antonio, TX", "USA"),
    "MPC":  (40.7500, -83.1271,  "Findlay, OH", "USA"),
    "BP":   (51.5074, -0.1278,   "London", "UK"),
    # Biotech
    "MRNA": (42.3601, -71.0589,  "Cambridge, MA", "USA"),
    "ILMN": (32.9031, -117.2013, "San Diego, CA", "USA"),
    "NVAX": (38.9072, -77.0369,  "Gaithersburg, MD", "USA"),
    "CRSP": (47.3769, 8.5417,    "Zug", "Switzerland"),
    "EDIT": (42.3601, -71.0589,  "Cambridge, MA", "USA"),
    "BEAM": (42.3601, -71.0589,  "Cambridge, MA", "USA"),
    "PACB": (37.3875, -122.0170, "Menlo Park, CA", "USA"),
    "TMO":  (42.3601, -71.0589,  "Waltham, MA", "USA"),
    # FinTech
    "V":    (37.3875, -122.1085, "San Jose, CA", "USA"),
    "MA":   (40.7589, -73.9851,  "Purchase, NY", "USA"),
    "PYPL": (37.3875, -122.1085, "San Jose, CA", "USA"),
    "SQ":   (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "NU":   (-23.5505, -46.6333, "São Paulo", "Brazil"),
    "SOFI": (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "AFRM": (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "COIN": (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "HOOD": (37.3875, -122.0170, "Menlo Park, CA", "USA"),
    # Autonomous
    "UBER": (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "LYFT": (37.7749, -122.4194, "San Francisco, CA", "USA"),
    "RIVN": (34.0195, -118.4912, "Irvine, CA", "USA"),
    "LCID": (33.4484, -112.0740, "Newark, CA", "USA"),
    "GM":   (42.3314, -83.0458,  "Detroit, MI", "USA"),
    "F":    (42.3314, -83.0458,  "Dearborn, MI", "USA"),
    "MBLY": (38.9072, -77.0369,  "Jerusalem", "Israel"),
}

# ── STATIC RELATIONSHIP EDGES ─────────────────────────────────────────────────
# (source, target, type, strength 1-10, description)
# Types: competitor | partner | customer | supplier | subsidiary | investor |
#        government | regulatory | ecosystem | musk-linked
EDGES = [
    # Semiconductor ecosystem
    ("NVDA", "AMD",   "competitor", 9,  "Direct GPU competitors — data center and consumer segments"),
    ("NVDA", "INTC",  "competitor", 7,  "Competing in AI accelerator and data center markets"),
    ("NVDA", "GOOGL", "competitor", 6,  "NVDA chips vs Google TPUs for AI training"),
    ("NVDA", "AMD",   "competitor", 9,  "Head-to-head in AI GPU market"),
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
    # Australian context
    ("MSFT", "MSFT",  "australia",  6,  "Microsoft $5B Australian AI data center investment"),
    ("AMZN", "AMZN",  "australia",  6,  "Amazon AWS Australia regions"),
    ("GOOGL","GOOGL", "australia",  5,  "Google Cloud Australian infrastructure"),
]

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
}

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
}


def build_graph(symbols: list[str] = None, quotes: dict = None) -> dict:
    """Build graph nodes and edges for given symbols (or all known)."""
    quotes = quotes or {}
    all_syms = set(HQ.keys())
    if symbols:
        # Include requested symbols + their 1-hop neighbors
        req = set(s.upper() for s in symbols)
        neighbors = set()
        for src, tgt, *_ in EDGES:
            if src in req: neighbors.add(tgt)
            if tgt in req: neighbors.add(src)
        focus = req | (neighbors & all_syms)
    else:
        focus = all_syms

    nodes = []
    for sym in focus:
        if sym not in HQ:
            continue
        lat, lng, city, country = HQ[sym]
        q = quotes.get(sym, {})
        sector = SECTORS.get(sym, "Other")
        nodes.append({
            "id": sym,
            "symbol": sym,
            "name": q.get("name", sym),
            "sector": sector,
            "color": SECTOR_COLORS.get(sector, "#4a6380"),
            "price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
            "lat": lat,
            "lng": lng,
            "city": city,
            "country": country,
            "size": max(10, min(40, 10 + (q.get("price", 1) ** 0.3))),
        })

    node_ids = {n["id"] for n in nodes}
    edges = []
    seen = set()
    for src, tgt, etype, strength, desc in EDGES:
        if src == tgt:
            continue
        if src not in node_ids or tgt not in node_ids:
            continue
        key = tuple(sorted([src, tgt])) + (etype,)
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            "source": src,
            "target": tgt,
            "type": etype,
            "strength": strength,
            "color": EDGE_COLORS.get(etype, "#4a6380"),
            "description": desc,
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "sector_colors": SECTOR_COLORS,
        "edge_colors": EDGE_COLORS,
        "generated_at": datetime.utcnow().isoformat(),
        "node_count": len(nodes),
        "edge_count": len(edges),
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
