
import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
import io

# -------------------------
# Page setup
# -------------------------
st.set_page_config(layout="wide", page_title="Daily Market Bias — Nasdaq 100 & Gold")

TZ_LABEL = "UTC"  # adjust display if you like

# -------------------------
# API keys (Trading Economics)
# -------------------------
# Fill these with your credentials (Settings > Secrets in Streamlit Cloud also works)
TE_USERNAME = st.secrets.get("TE_USERNAME", "YOUR_TE_USERNAME")
TE_API_KEY = st.secrets.get("TE_API_KEY", "YOUR_TE_API_KEY")

# -------------------------
# Constants
# -------------------------
CFTC_COT_CSV_URL = "https://www.cftc.gov/files/dea/history/deacotdisagg.csv"

# yfinance tickers
NASDAQ_PRICE_TICKERS = ["QQQ", "NVDA", "AAPL", "SOXX", "^VIX"]
GOLD_CROSS_MARKET_TICKERS = {
    "DXY": "DX-Y.NYB",     # Dollar index proxy
    "US10Y": "^TNX",       # 10Y yield *10 (yfinance convention)
    "VIX": "^VIX",
    "COPPER": "HG=F",
    "OIL": "CL=F"
}

# Breadth sample (can be replaced with SP500 full list CSV later)
SP500_SAMPLE = [
    "AAPL","MSFT","AMZN","GOOGL","META","TSLA","NVDA","JPM","JNJ","V",
    "XOM","PG","HD","AVGO","LLY","BAC","PFE","KO","DIS","NFLX"
]

MACRO_COUNTRIES = ["United States", "Euro Area", "China"]

# -------------------------
# Helpers
# -------------------------
def fmt_num(x):
    try:
        x = float(x)
    except:
        return str(x)
    if abs(x) >= 1e9: return f"{x/1e9:.2f}B"
    if abs(x) >= 1e6: return f"{x/1e6:.2f}M"
    if abs(x) >= 1e3: return f"{x/1e3:.0f}K"
    return f"{x:.0f}"

def sentiment_label(score):
    if score >= 1.5:  return "Bullish", "🟢"
    if score >= 0.5:  return "Mild Bullish", "🟩"
    if score > -0.5:  return "Neutral", "🟨"
    if score > -1.5:  return "Mild Bearish", "🟧"
    return "Bearish", "🔴"

# -------------------------
# Data fetchers (cached)
# -------------------------
@st.cache_data(ttl=1800)
def fetch_cot_csv():
    r = requests.get(CFTC_COT_CSV_URL, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    return df

def _find_latest_week(df, mask):
    sub = df[mask].copy()
    if sub.empty: 
        return None, None
    sub["Report_Date_as_MM_DD_YYYY"] = pd.to_datetime(sub["Report_Date_as_MM_DD_YYYY"])
    latest = sub["Report_Date_as_MM_DD_YYYY"].max()
    prev = latest - pd.Timedelta(days=7)
    return sub[sub["Report_Date_as_MM_DD_YYYY"]==latest], sub[sub["Report_Date_as_MM_DD_YYYY"]==prev]

def parse_cot_for_nasdaq(df):
    # Try to match common names for Nasdaq futures in the CSV
    mask = df["Market_and_Exchange_Names"].str.contains(
        "NASDAQ-100|E-MINI NASDAQ-100|NASDAQ 100", case=False, na=False
    )
    latest, prev = _find_latest_week(df, mask)
    if latest is None or latest.empty:
        return None
    def _vals(row):
        return dict(
            non_com_long = int(row["Noncommercial_Positions_Long_All"]),
            non_com_short= int(row["Noncommercial_Positions_Short_All"]),
            comm_long    = int(row["Commercial_Positions_Long_All"]),
            comm_short   = int(row["Commercial_Positions_Short_All"]),
            open_interest= int(row["Open_Interest_All"]),
            date         = row["Report_Date_as_MM_DD_YYYY"].strftime("%Y-%m-%d")
        )
    L = _vals(latest.iloc[0])
    if prev is not None and not prev.empty:
        P = _vals(prev.iloc[0])
        L["chg_non_com_long"]  = L["non_com_long"]  - P["non_com_long"]
        L["chg_non_com_short"] = L["non_com_short"] - P["non_com_short"]
        L["chg_oi"]            = L["open_interest"] - P["open_interest"]
    else:
        L["chg_non_com_long"] = L["chg_non_com_short"] = L["chg_oi"] = 0
    L["net_spec"] = L["non_com_long"] - L["non_com_short"]
    L["net_comm"] = L["comm_long"] - L["comm_short"]
    return L

def parse_cot_for_gold(df):
    mask = df["Market_and_Exchange_Names"].str.contains("GOLD", case=False, na=False)
    latest, prev = _find_latest_week(df, mask)
    if latest is None or latest.empty:
        return None
    def _vals(row):
        return dict(
            non_com_long = int(row["Noncommercial_Positions_Long_All"]),
            non_com_short= int(row["Noncommercial_Positions_Short_All"]),
            comm_long    = int(row["Commercial_Positions_Long_All"]),
            comm_short   = int(row["Commercial_Positions_Short_All"]),
            open_interest= int(row["Open_Interest_All"]),
            date         = row["Report_Date_as_MM_DD_YYYY"].strftime("%Y-%m-%d")
        )
    L = _vals(latest.iloc[0])
    if prev is not None and not prev.empty:
        P = _vals(prev.iloc[0])
        L["chg_non_com_long"]  = L["non_com_long"]  - P["non_com_long"]
        L["chg_non_com_short"] = L["non_com_short"] - P["non_com_short"]
        L["chg_oi"]            = L["open_interest"] - P["open_interest"]
    else:
        L["chg_non_com_long"] = L["chg_non_com_short"] = L["chg_oi"] = 0
    L["net_spec"] = L["non_com_long"] - L["non_com_short"]
    L["net_comm"] = L["comm_long"] - L["comm_short"]
    return L

@st.cache_data(ttl=240)
def fetch_prices(tickers):
    """Return last and previous close + pct change for each ticker."""
    if isinstance(tickers, str):
        tickers = [tickers]
    data = yf.download(tickers, period="2d", interval="1d", progress=False, auto_adjust=False)
    # Handle single vs multi-index
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"].iloc[-2:]
        vol   = data["Volume"].iloc[-1]
        out = []
        for t in close.columns:
            prev = close[t].iloc[0]
            last = close[t].iloc[1]
            chg  = (last - prev) / prev * 100 if prev not in (0, None) else 0
            out.append((t, float(last), float(chg), float(vol[t]) if t in vol.index else None))
        return pd.DataFrame(out, columns=["Ticker","Close","PctChange","Volume"]).set_index("Ticker")
    else:
        # Single ticker
        prev = data["Close"].iloc[-2]
        last = data["Close"].iloc[-1]
        chg  = (last - prev) / prev * 100 if prev not in (0, None) else 0
        vol  = data["Volume"].iloc[-1]
        return pd.DataFrame([[tickers[0], float(last), float(chg), float(vol)]],
                            columns=["Ticker","Close","PctChange","Volume"]).set_index("Ticker")

@st.cache_data(ttl=240)
def fetch_option_flow_yf(ticker):
    """Crude option flow proxy using near expiry chain totals (volume & open interest)."""
    try:
        tk = yf.Ticker(ticker)
        opts = tk.options
        if not opts:
            return None
        opt_date = opts[0]
        chain = tk.option_chain(opt_date)
        calls = chain.calls
        puts  = chain.puts
        total_call_vol = int(calls["volume"].fillna(0).sum())
        total_put_vol  = int(puts["volume"].fillna(0).sum())
        total_call_oi  = int(calls["openInterest"].fillna(0).sum())
        total_put_oi   = int(puts["openInterest"].fillna(0).sum())
        pcr = total_put_vol / total_call_vol if total_call_vol > 0 else None
        return {
            "call_volume": total_call_vol,
            "put_volume": total_put_vol,
            "call_oi": total_call_oi,
            "put_oi": total_put_oi,
            "put_call_ratio": pcr
        }
    except Exception:
        return None

@st.cache_data(ttl=600)
def fetch_trading_economics_calendar(countries=MACRO_COUNTRIES):
    url = f"https://api.tradingeconomics.com/calendar?c={TE_USERNAME}:{TE_API_KEY}&f=json"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return []
        data = r.json()
        return [e for e in data if e.get("Country") in countries]
    except Exception:
        return []

# -------------------------
# Breadth & scoring
# -------------------------
def compute_breadth():
    px = fetch_prices(SP500_SAMPLE)
    adv = int((px["PctChange"] > 0).sum())
    dec = int((px["PctChange"] < 0).sum())
    tot = len(SP500_SAMPLE)
    ratio = adv / max(dec,1)
    score = 0
    if ratio > 1.2: score += 1
    elif ratio < 0.8: score -= 1
    # simple MA breadth placeholder: use % positive day as proxy
    pct_pos = adv / tot
    if pct_pos > 0.55: score += 1
    elif pct_pos < 0.45: score -= 1
    score = max(min(score, 3), -3)
    return score, adv, dec, tot

def score_options(flow):
    if not flow or flow.get("put_call_ratio") is None:
        return 0, "No option flow (PCR)"
    pcr = flow["put_call_ratio"]
    if pcr < 0.8:  return 1, f"Put/Call {pcr:.2f} bullish"
    if pcr > 1.2:  return -1, f"Put/Call {pcr:.2f} bearish"
    return 0, f"Put/Call {pcr:.2f} neutral"

def score_price(px_df, base_ticker):
    if px_df is None or base_ticker not in px_df.index:
        return 0, "No price data"
    chg = px_df.loc[base_ticker, "PctChange"]
    if chg > 0.2:  s = 1
    elif chg < -0.2: s = -1
    else: s = 0
    return s, f"{base_ticker} change {chg:.2f}%"

def score_cot_generic(cot):
    if not cot: 
        return 0, "No COT"
    s = 1 if cot["net_spec"] > 0 else -1
    if cot["chg_non_com_short"] > cot["chg_non_com_long"]:
        s -= 0.5
    else:
        s += 0.5
    s = max(min(s, 2), -2)
    txt = f"NetSpec {fmt_num(cot['net_spec'])}, ΔLong {fmt_num(cot['chg_non_com_long'])}, ΔShort {fmt_num(cot['chg_non_com_short'])}"
    return s, txt

def score_gold_cot(cot):
    if not cot:
        return 0, "No COT"
    s = 1.5 if cot["net_spec"] > 50000 else (1 if cot["net_spec"] > 0 else -1)
    s += 0.5 if cot["chg_non_com_long"] > 0 else -0.5
    s = max(min(s, 2), -2)
    txt = f"Gold NetSpec {fmt_num(cot['net_spec'])}, ΔLong {fmt_num(cot['chg_non_com_long'])}"
    return s, txt

def score_macro(calendar_events):
    now = datetime.utcnow()
    start = now - timedelta(days=3)
    end   = now + timedelta(days=3)
    impact_map = {"High": 2, "Medium": 1, "Low": 0}
    score = 0.0
    for e in calendar_events:
        dt_str = e.get("Date")
        if not dt_str: 
            continue
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        except:
            continue
        if dt < start or dt > end:
            continue
        impact = impact_map.get(e.get("Impact"), 0)
        surprise = e.get("Surprise")
        if surprise not in (None, ""):
            try:
                sv = float(surprise)
                score += impact if sv > 0 else -impact
            except:
                pass
        else:
            # upcoming risk weight
            score -= impact * 0.5
    score = max(min(score, 3), -3)
    return score, f"Macro impact score {score:.2f}"

def score_gold_cross(pxmap):
    s = 0.0
    notes = []
    dxy = pxmap.get("DXY"); tnx = pxmap.get("US10Y"); vix = pxmap.get("VIX")
    if dxy is not None:
        if dxy["PctChange"] < 0: s += 1; notes.append("DXY↓ supports gold")
        else: s -= 1; notes.append("DXY↑ hurts gold")
    if tnx is not None:
        if tnx["PctChange"] > 0: s -= 1; notes.append("US10Y↑ hurts gold")
        else: s += 1; notes.append("US10Y↓ supports gold")
    if vix is not None:
        if vix["PctChange"] < 0: s -= 0.5; notes.append("VIX↓ risk-on (bearish gold)")
        else: s += 0.5; notes.append("VIX↑ risk-off (bullish gold)")
    s = max(min(s, 2), -2)
    return s, "; ".join(notes)

# -------------------------
# Top bar
# -------------------------
st.markdown("## 📈 Daily Market Bias — Nasdaq 100 & Gold (XAUUSD)")
refresher = st.empty()
btn = st.button("🔄 Refresh Now")
if btn:
    st.cache_data.clear()

# auto-refresh every 60s without infinite loops
st_autorefresh = st.experimental_data_editor if False else None  # placeholder to avoid linter

# -------------------------
# Fetch shared data
# -------------------------
with st.spinner("Loading data..."):
    cot_df = fetch_cot_csv()
    cot_ndx = parse_cot_for_nasdaq(cot_df)
    cot_gold = parse_cot_for_gold(cot_df)

    px_nas = fetch_prices(NASDAQ_PRICE_TICKERS)
    opt_qqq = fetch_option_flow_yf("QQQ")
    breadth_score_raw, adv, dec, tot = compute_breadth()
    macro_events = fetch_trading_economics_calendar()

    # Cross-market for gold
    cross_ticks = list(GOLD_CROSS_MARKET_TICKERS.values())
    px_cross = fetch_prices(cross_ticks) if cross_ticks else pd.DataFrame()
    # map back
    cross_map = {}
    for k, t in GOLD_CROSS_MARKET_TICKERS.items():
        if t in px_cross.index:
            cross_map[k] = px_cross.loc[t].to_dict()

# -------------------------
# NASDAQ Column
# -------------------------
col1, col2 = st.columns(2)

with col1:
    st.subheader("🖥 Nasdaq 100 Sentiment")
    s_cot, txt_cot = score_cot_generic(cot_ndx)
    s_prc, txt_prc = score_price(px_nas, "QQQ")
    s_opt, txt_opt = score_options(opt_qqq)
    s_brd = max(min(breadth_score_raw, 2), -2)
    txt_brd = f"Breadth score {breadth_score_raw} — {adv} adv / {dec} dec / {tot} total"

    s_mac, txt_mac = score_macro(macro_events)

    nasdaq_score = s_cot*0.15 + s_prc*0.25 + s_opt*0.20 + s_brd*0.20 + s_mac*0.20
    lbl, emo = sentiment_label(nasdaq_score)

    st.markdown(f"### {emo} Overall Nasdaq 100 Bias: **{lbl}** ({nasdaq_score:.2f})")
    with st.expander("Details"):
        st.write(f"**COT:** {txt_cot}")
        st.write(f"**Price:** {txt_prc}")
        st.write(f"**Options:** {txt_opt}")
        st.write(f"**Breadth:** {txt_brd}")
        st.write(f"**Macro (USD/Euro/China):** {txt_mac}")

# -------------------------
# GOLD Column
# -------------------------
with col2:
    st.subheader("🥇 Gold (XAUUSD) Sentiment")
    s_cot_g, txt_cot_g = score_gold_cot(cot_gold)
    # Inflation panel can be added via TE inflation endpoint later; using macro as proxy now
    # Options via GLD
    opt_gld = fetch_option_flow_yf("GLD")
    s_opt_g, txt_opt_g = score_options(opt_gld)
    s_cross, txt_cross = score_gold_cross(cross_map)

    gold_score = s_cot_g*0.35 + 0.25*0 + s_opt_g*0.20 + s_cross*0.20  # inflation weight reserved (0 for now if not wired)
    lbl_g, emo_g = sentiment_label(gold_score)

    st.markdown(f"### {emo_g} Overall Gold Bias: **{lbl_g}** ({gold_score:.2f})")
    with st.expander("Details"):
        st.write(f"**COT:** {txt_cot_g}")
        st.write(f"**Options (GLD proxy):** {txt_opt_g}")
        st.write(f"**Cross-Market:** {txt_cross}")

st.markdown("---")
stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
refresher.markdown(f"**Last updated:** {stamp} {TZ_LABEL}")
st.caption("Sources: CFTC, Trading Economics, Yahoo Finance. Auto-cached; click Refresh to force update.")
