import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# ===== API Keys =====
FINNHUB_API_KEY = "d1uv2rhr01qujmdeohv0d1uv2rhr01qujmdeohvg"
TE_USERNAME = "c88d1d122399451"
TE_API_KEY = "rdog9czpshn7zb9"

# ===== Config =====
REFRESH_INTERVAL = 30  # seconds
SYMBOLS = {
    "XAUUSD": "Gold",
    "NASDAQ100": "Nasdaq 100"
}

# ===== Functions =====
def get_macro_events():
    """Fetch upcoming macro events affecting USD"""
    url = f"https://api.tradingeconomics.com/calendar?country=united%20states&importance=2,3&c={TE_USERNAME}:{TE_API_KEY}"
    try:
        resp = requests.get(url)
        data = resp.json()
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        today = datetime.utcnow()
        df = df[df["date"] >= today]
        return df
    except Exception as e:
        st.error(f"Error fetching macro events: {e}")
        return pd.DataFrame()

def get_geopolitical_sentiment():
    """Fetch geopolitical news from Finnhub"""
    from_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    to_date = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://finnhub.io/api/v1/news?category=general&from={from_date}&to={to_date}&token={FINNHUB_API_KEY}"
    try:
        resp = requests.get(url)
        news_items = resp.json()
        filtered = []
        keywords = ["gold", "xau", "nasdaq", "us tech", "technology stocks"]
        for item in news_items:
            headline = item.get("headline", "").lower()
            if any(k in headline for k in keywords):
                filtered.append(item)
        return filtered
    except Exception as e:
        st.error(f"Error fetching geopolitical news: {e}")
        return []

def calculate_bias(symbol, macro_df, news_items):
    """Score bias based on macro events and news sentiment"""
    score = 0
    # Macro events impact
    if not macro_df.empty:
        for _, row in macro_df.iterrows():
            if "USD" in row.get("currency", ""):
                if row.get("importance") == 3:
                    score -= 1  # High impact USD event = risk
                elif row.get("importance") == 2:
                    score -= 0.5

    # News sentiment impact
    for news in news_items:
        headline = news.get("headline", "").lower()
        if symbol == "XAUUSD" and "gold" in headline:
            score += 1
        if symbol == "NASDAQ100" and ("nasdaq" in headline or "tech" in headline):
            score += 1

    # Determine bias label
    if score > 0:
        bias = "Bullish"
        color = "green"
    elif score < 0:
        bias = "Bearish"
        color = "red"
    else:
        bias = "Neutral"
        color = "gray"

    return bias, color, score

# ===== UI =====
st.set_page_config(page_title="Daily Market Bias Dashboard", layout="wide")
st.title("📊 Daily Market Bias Dashboard")
st.caption(f"Auto-refreshes every {REFRESH_INTERVAL} seconds — GOLD & NASDAQ only")

macro_df = get_macro_events()
news_items = get_geopolitical_sentiment()

data = []
for sym, name in SYMBOLS.items():
    bias, color, score = calculate_bias(sym, macro_df, news_items)
    data.append({
        "Symbol": sym,
        "Name": name,
        "Bias": f":{color}[{bias}]",
        "Score": score
    })

df_display = pd.DataFrame(data)
st.dataframe(df_display, use_container_width=True)

with st.expander("Macro Events Impacting USD"):
    if not macro_df.empty:
        st.dataframe(macro_df[["date", "event", "currency", "importance"]])
    else:
        st.write("No upcoming events found.")

with st.expander("Relevant Geopolitical News"):
    if news_items:
        for n in news_items:
            st.write(f"**{n['headline']}** — {n['datetime']}")
    else:
        st.write("No recent geopolitical news found.")

# Auto-refresh
st_autorefresh = st.experimental_rerun
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = datetime.utcnow()

if (datetime.utcnow() - st.session_state["last_refresh"]).seconds >= REFRESH_INTERVAL:
    st.session_state["last_refresh"] = datetime.utcnow()
    st.experimental_rerun()
