import time
from datetime import datetime, timezone
import requests
import pandas as pd
import streamlit as st

BASE = "https://api.india.delta.exchange"
HEADERS = {"Accept": "application/json", "User-Agent": "SMC-Coin-Hunter/0.1"}
st.set_page_config(page_title="SMC Coin Hunter | Delta", page_icon="🛰️", layout="wide")

st.title("🛰️ SMC Coin Hunter Pro — Delta Exchange")
st.caption("Market scanner • SMC-inspired rules • 1H setup + 4H trend • paper signals only")

st.warning(
    "Research tool only: signals are unvalidated candidates, not financial advice or guaranteed-profit calls. "
    "This build does not place orders and does not need your API key."
)

@st.cache_data(ttl=60, show_spinner=False)
def api_get(path, params=None):
    r = requests.get(BASE + path, params=params or {}, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(str(data.get("error", "Delta API returned success=false")))
    return data

def result_list(payload):
    result = payload.get("result", []) if isinstance(payload, dict) else payload
    return result if isinstance(result, list) else []

@st.cache_data(ttl=60, show_spinner=False)
def get_products():
    payload = api_get("/v2/products", {"page_size": 200})
    rows = result_list(payload)
    # Try additional pages where a cursor is available, but cap calls for safety.
    cursor = (payload.get("meta") or {}).get("after") if isinstance(payload, dict) else None
    pages = 0
    while cursor and pages < 4:
        payload2 = api_get("/v2/products", {"page_size": 200, "after": cursor})
        rows.extend(result_list(payload2))
        cursor = (payload2.get("meta") or {}).get("after") if isinstance(payload2, dict) else None
        pages += 1
    out = []
    for p in rows:
        if not isinstance(p, dict):
            continue
        ptype = str(p.get("contract_type", p.get("product_type", ""))).lower()
        state = str(p.get("state", "")).lower()
        symbol = str(p.get("symbol", ""))
        status = str(p.get("trading_status", "operational")).lower()
        if symbol and ("perpetual" in ptype) and (state in ("live", "")) and status == "operational":
            out.append({
                "symbol": symbol,
                "description": p.get("description", p.get("underlying_asset", symbol)),
                "product_id": p.get("id"),
            })
    return out

@st.cache_data(ttl=45, show_spinner=False)
def get_tickers():
    payload = api_get("/v2/tickers")
    rows = result_list(payload)
    data = {}
    for t in rows:
        if not isinstance(t, dict):
            continue
        symbol = t.get("symbol")
        if symbol:
            data[str(symbol)] = t
    return data

@st.cache_data(ttl=45, show_spinner=False)
def get_candles(symbol, resolution, bars=100):
    now = int(time.time())
    secs = 3600 if resolution == "1h" else 14400
    start = now - secs * (bars + 3)
    payload = api_get("/v2/history/candles", {
        "resolution": resolution, "symbol": symbol, "start": start, "end": now
    })
    rows = result_list(payload)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    required = ["time", "open", "high", "low", "close"]
    if not all(c in df.columns for c in required):
        return pd.DataFrame()
    for c in ["open", "high", "low", "close", "volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("time").drop_duplicates("time")
    # Exclude the newest candle because it may still be forming.
    if len(df) > 2:
        df = df.iloc[:-1].copy()
    return df.tail(bars).reset_index(drop=True)

def analyse(symbol):
    try:
        h1 = get_candles(symbol, "1h", 100)
        h4 = get_candles(symbol, "4h", 80)
        if len(h1) < 30 or len(h4) < 25:
            return None
        # Higher-timeframe trend filter
        h4c = h4["close"]
        ema20 = h4c.ewm(span=20, adjust=False).mean()
        ema50 = h4c.ewm(span=50, adjust=False).mean()
        if len(ema50) < 25:
            return None
        if h4c.iloc[-1] > ema20.iloc[-1] and ema20.iloc[-1] > ema50.iloc[-1]:
            bias = "Bullish"
        elif h4c.iloc[-1] < ema20.iloc[-1] and ema20.iloc[-1] < ema50.iloc[-1]:
            bias = "Bearish"
        else:
            bias = "Mixed"

        last = h1.iloc[-1]
        prev = h1.iloc[-2]
        prior = h1.iloc[-13:-1]
        prior_high = float(prior["high"].max())
        prior_low = float(prior["low"].min())
        close = float(last["close"])
        high = float(last["high"])
        low = float(last["low"])
        # Approximate structure breaks using previous 12 completed bars.
        bull_bos = close > prior_high
        bear_bos = close < prior_low
        # Liquidity sweep: wick takes prior range and candle closes back inside.
        sweep_low = low < prior_low and close > prior_low
        sweep_high = high > prior_high and close < prior_high
        # 3-candle FVG: gap between candle 1 and candle 3.
        a = h1.iloc[-3]
        bull_fvg = float(last["low"]) > float(a["high"])
        bear_fvg = float(last["high"]) < float(a["low"])
        bull_gap_low, bull_gap_high = (float(a["high"]), low) if bull_fvg else (None, None)
        bear_gap_low, bear_gap_high = (high, float(a["low"])) if bear_fvg else (None, None)
        # Recent FVG retest / overlap.
        bull_retest = False
        bear_retest = False
        if bull_fvg:
            bull_retest = low <= bull_gap_high and high >= bull_gap_low
        if bear_fvg:
            bear_retest = low <= bear_gap_high and high >= bear_gap_low
        # Also inspect recent gaps for retests to avoid requiring a gap only on the latest bar.
        for i in range(max(2, len(h1)-12), len(h1)):
            c = h1.iloc[i]
            older = h1.iloc[i-2]
            if float(c["low"]) > float(older["high"]):
                gl, gh = float(older["high"]), float(c["low"])
                if low <= gh and high >= gl:
                    bull_retest = True
            if float(c["high"]) < float(older["low"]):
                gl, gh = float(c["high"]), float(older["low"])
                if low <= gh and high >= gl:
                    bear_retest = True

        vol = float(last["volume"]) if "volume" in h1.columns and pd.notna(last.get("volume")) else 0.0
        vol_mean = float(h1["volume"].tail(20).mean()) if "volume" in h1.columns else 0.0
        vol_confirm = bool(vol_mean > 0 and vol >= vol_mean)
        score_long = (20 if bias == "Bullish" else 0) + (25 if bull_bos else 0) + (20 if sweep_low else 0) + (15 if bull_fvg else 0) + (10 if bull_retest else 0) + (10 if vol_confirm else 0)
        score_short = (20 if bias == "Bearish" else 0) + (25 if bear_bos else 0) + (20 if sweep_high else 0) + (15 if bear_fvg else 0) + (10 if bear_retest else 0) + (10 if vol_confirm else 0)

        side, score = "WAIT", max(score_long, score_short)
        if score_long >= 60 and score_long > score_short:
            side = "BUY candidate"
        elif score_short >= 60 and score_short > score_long:
            side = "SELL candidate"

        # ATR-like recent range for an indicative stop; not an order instruction.
        tr = (h1["high"] - h1["low"]).tail(14)
        atr = float(tr.mean()) if len(tr) else close * 0.01
        if side == "BUY candidate":
            stop = min(float(h1["low"].tail(8).min()), close - atr)
            risk = max(close - stop, close * 0.002)
            t1, t2 = close + 1.5*risk, close + 2*risk
            zone = f"{min(close, bull_gap_low) if bull_gap_low else close:.6g} – {max(close, bull_gap_high) if bull_gap_high else close:.6g}"
        elif side == "SELL candidate":
            stop = max(float(h1["high"].tail(8).max()), close + atr)
            risk = max(stop - close, close * 0.002)
            t1, t2 = close - 1.5*risk, close - 2*risk
            zone = f"{min(close, bear_gap_low) if bear_gap_low else close:.6g} – {max(close, bear_gap_high) if bear_gap_high else close:.6g}"
        else:
            stop = t1 = t2 = None
            zone = "Wait for confirmation"

        setup = []
        if bull_bos or bear_bos: setup.append("BOS")
        if sweep_low: setup.append("Sell-side sweep")
        if sweep_high: setup.append("Buy-side sweep")
        if bull_fvg: setup.append("Bullish FVG")
        if bear_fvg: setup.append("Bearish FVG")
        if bull_retest or bear_retest: setup.append("FVG retest")
        if vol_confirm: setup.append("Volume")
        return {
            "Coin": symbol, "Direction": side, "Score": int(score), "4H bias": bias,
            "Price": close, "Entry zone (indicative)": zone,
            "Stop (indicative)": stop, "Target 1": t1, "Target 2": t2,
            "Setup checks": ", ".join(setup) if setup else "No complete setup",
            "1H candle time": datetime.fromtimestamp(int(last["time"]), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        }
    except Exception:
        return None

with st.sidebar:
    st.header("Scanner settings")
    market_count = st.slider("Markets to scan (top by 24h turnover)", 5, 40, 15, 5)
    min_score = st.slider("Minimum score to highlight", 40, 90, 60, 5)
    st.caption("The scan uses completed candles and public market data.")
    refresh = st.button("🔄 Refresh / scan now", type="primary", use_container_width=True)
    st.divider()
    st.caption("Build 0.1 • No trading API key • No order execution")

st.write("### Market scan")
if refresh:
    st.cache_data.clear()

try:
    with st.spinner("Loading Delta Exchange markets and tickers…"):
        products = get_products()
        tickers = get_tickers()
    if not products:
        st.error("No perpetual futures were returned by the product endpoint. Check API status or endpoint response.")
        st.stop()

    ranked = []
    for p in products:
        t = tickers.get(p["symbol"], {})
        turnover = t.get("turnover_24h", t.get("turnover", t.get("volume", 0)))
        try: turnover = float(turnover or 0)
        except (TypeError, ValueError): turnover = 0.0
        ranked.append({**p, "turnover": turnover, "ticker": t})
    ranked.sort(key=lambda x: x["turnover"], reverse=True)
    chosen = ranked[:market_count]

    c1, c2, c3 = st.columns(3)
    c1.metric("Eligible perpetual markets", len(products))
    c2.metric("Markets selected", len(chosen))
    c3.metric("Scan time (UTC)", datetime.now(timezone.utc).strftime("%H:%M:%S"))

    rows = []
    progress = st.progress(0, text="Scanning SMC conditions…")
    for i, p in enumerate(chosen):
        item = analyse(p["symbol"])
        if item:
            item["24h turnover"] = p["turnover"]
            rows.append(item)
        progress.progress((i+1)/len(chosen), text=f"Analysing {p['symbol']} ({i+1}/{len(chosen)})")
    progress.empty()

    if not rows:
        st.warning("No usable candle sets were returned. Try refreshing later; this may be an API/data issue.")
    else:
        df = pd.DataFrame(rows)
        df["Priority"] = df.apply(lambda r: "HIGH" if r["Score"] >= min_score and r["Direction"] != "WAIT" else ("WATCH" if r["Score"] >= 40 else "LOW"), axis=1)
        df = df.sort_values(["Score", "24h turnover"], ascending=[False, False])
        top = df[(df["Score"] >= min_score) & (df["Direction"] != "WAIT")]
        a, b, c = st.columns(3)
        a.metric("BUY candidates", int((top["Direction"] == "BUY candidate").sum()))
        b.metric("SELL candidates", int((top["Direction"] == "SELL candidate").sum()))
        c.metric("High-priority setups", len(top))
        st.dataframe(
            df[["Priority","Coin","Direction","Score","4H bias","Price","Entry zone (indicative)","Stop (indicative)","Target 1","Target 2","Setup checks","24h turnover","1H candle time"]],
            use_container_width=True, hide_index=True
        )
        st.download_button("⬇️ Download scan as CSV", df.to_csv(index=False).encode("utf-8"), "smc_coin_hunter_scan.csv", "text/csv")
        st.subheader("Highest-ranked candidates")
        if top.empty:
            st.info("No setup passed your current score threshold. WAIT is a valid result.")
        else:
            st.dataframe(top[["Coin","Direction","Score","4H bias","Price","Entry zone (indicative)","Stop (indicative)","Target 1","Target 2","Setup checks"]], use_container_width=True, hide_index=True)
        st.caption("Scores are rule-based confluence points, not win probabilities. Stops/targets are rough research estimates, before fees, slippage, funding, contract sizing and exchange-specific risk checks.")
except requests.RequestException as e:
    st.error(f"Could not connect to Delta Exchange public API: {e}")
    st.info("Confirm your deployment can access api.india.delta.exchange and retry.")
except Exception as e:
    st.error(f"Scanner error: {e}")

st.divider()
st.caption("Next build steps: validate the SMC rules against historical data, record signal outcomes, add configurable notifications, and only then consider paper trading. Do not add exchange trading credentials to this scanner.")
