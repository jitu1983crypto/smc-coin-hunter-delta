import time
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

# SMC Coin Hunter Pro — Delta Exchange India
BASE_URL = "https://api.india.delta.exchange"
HEADERS = {"Accept": "application/json", "User-Agent": "SMC-Coin-Hunter-Pro/1.0"}

st.set_page_config(
    page_title="SMC Coin Hunter Pro",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 SMC Coin Hunter Pro")
st.caption("Delta Exchange • Live market scanner • 15m / 1h / 4h")

st.warning(
    "Educational market analysis only. Signals can be wrong. "
    "No automatic trading or guaranteed profits."
)


def api_get(path, params=None):
    response = requests.get(
        BASE_URL + path,
        params=params,
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(str(data.get("error", "Exchange API returned an error")))

    return data.get("result", [])


@st.cache_data(ttl=60, show_spinner=False)
def get_products_and_tickers():
    products = api_get("/v2/products", {"page_size": 100})
    tickers = api_get("/v2/tickers", {"contract_types": "perpetual_futures"})
    return products, tickers


def get_candles(symbol, resolution, count=100):
    seconds = {
        "15m": 15 * 60,
        "1h": 60 * 60,
        "4h": 4 * 60 * 60,
    }[resolution]

    end = int(time.time())
    start = end - seconds * count

    rows = api_get(
        "/v2/history/candles",
        {
            "symbol": symbol,
            "resolution": resolution,
            "start": start,
            "end": end,
        },
    )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    return df.sort_values("time").reset_index(drop=True) if "time" in df else df


def analyze(df):
    if df.empty or len(df) < 30:
        return {
            "bias": "WAIT",
            "score": 0,
            "price": None,
            "fvg": "Not enough candles",
            "liquidity": "Not enough candles",
            "structure": "Not enough candles",
            "reason": "Insufficient candle history",
        }

    close = df["close"]
    high = df["high"]
    low = df["low"]
    last = df.iloc[-1]

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    recent_high = high.iloc[-21:-1].max()
    recent_low = low.iloc[-21:-1].min()

    # Simplified BOS: latest close breaks recent swing range.
    bullish_bos = last["close"] > recent_high
    bearish_bos = last["close"] < recent_low

    # Simplified FVG: three-candle imbalance, checked recently.
    bullish_fvg = False
    bearish_fvg = False
    fvg_text = "No recent FVG"

    for i in range(max(2, len(df) - 12), len(df)):
        if i >= 2:
            if low.iloc[i] > high.iloc[i - 2]:
                bullish_fvg = True
                fvg_text = f"Bullish FVG: {high.iloc[i-2]:.6g}–{low.iloc[i]:.6g}"
            if high.iloc[i] < low.iloc[i - 2]:
                bearish_fvg = True
                fvg_text = f"Bearish FVG: {high.iloc[i]:.6g}–{low.iloc[i-2]:.6g}"

    # Possible liquidity sweep: wick crosses a recent level, then closes back.
    sweep_low = low.iloc[-1] < recent_low and close.iloc[-1] > recent_low
    sweep_high = high.iloc[-1] > recent_high and close.iloc[-1] < recent_high

    liquidity_text = "No clear sweep"
    if sweep_low:
        liquidity_text = "Possible sell-side liquidity sweep"
    elif sweep_high:
        liquidity_text = "Possible buy-side liquidity sweep"

    bull_score = 0
    bear_score = 0
    reasons = []

    if ema20.iloc[-1] > ema50.iloc[-1]:
        bull_score += 1
        reasons.append("EMA trend bullish")
    elif ema20.iloc[-1] < ema50.iloc[-1]:
        bear_score += 1
        reasons.append("EMA trend bearish")

    if bullish_bos:
        bull_score += 2
        reasons.append("Bullish BOS")
    elif bearish_bos:
        bear_score += 2
        reasons.append("Bearish BOS")

    if bullish_fvg:
        bull_score += 1
    if bearish_fvg:
        bear_score += 1

    if sweep_low:
        bull_score += 1
    if sweep_high:
        bear_score += 1

    if bull_score >= 3 and bull_score >= bear_score + 1:
        bias = "LONG"
        score = bull_score
    elif bear_score >= 3 and bear_score >= bull_score + 1:
        bias = "SHORT"
        score = bear_score
    else:
        bias = "WAIT"
        score = max(bull_score, bear_score)

    structure = (
        "Bullish BOS" if bullish_bos else
        "Bearish BOS" if bearish_bos else
        "No confirmed BOS"
    )

    return {
        "bias": bias,
        "score": score,
        "price": float(last["close"]),
        "fvg": fvg_text,
        "liquidity": liquidity_text,
        "structure": structure,
        "reason": ", ".join(reasons) if reasons else "No strong setup",
    }


def get_live_markets():
    products, tickers = get_products_and_tickers()

    live_symbols = set()
    for product in products:
        symbol = product.get("symbol")
        state = str(product.get("state", "")).lower()
        contract_type = str(product.get("contract_type", "")).lower()

        if (
            symbol
            and state == "live"
            and contract_type == "perpetual_futures"
        ):
            live_symbols.add(symbol)

    ticker_map = {}
    for ticker in tickers:
        symbol = ticker.get("symbol")
        if symbol in live_symbols:
            ticker_map[symbol] = ticker

    markets = []
    for symbol, ticker in ticker_map.items():
        try:
            price = float(
                ticker.get("mark_price")
                or ticker.get("close")
                or ticker.get("spot_price")
                or 0
            )
            volume = float(
                ticker.get("volume")
                or ticker.get("turnover")
                or 0
            )
        except (TypeError, ValueError):
            continue

        if price > 0:
            markets.append({
                "Symbol": symbol,
                "Live price": price,
                "Reported volume": volume,
            })

    return pd.DataFrame(markets)


with st.sidebar:
    st.header("Scanner settings")
    max_markets = st.slider("Markets to scan", 5, 30, 12)
    scan_all = st.checkbox("Scan all listed markets", value=False)
    st.caption("More markets can take longer and may hit API rate limits.")

if st.button("🔄 Refresh live data", type="primary"):
    get_products_and_tickers.clear()

try:
    with st.spinner("Connecting to Delta Exchange public market data..."):
        markets = get_live_markets()

    if markets.empty:
        st.error("No live markets were returned. Please refresh later.")
        st.stop()

    # Prefer major markets if available; then use reported volume.
    preferred = ["BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD", "XAGUSD"]
    markets["Priority"] = markets["Symbol"].apply(
        lambda s: 0 if s in preferred else 1
    )
    markets = markets.sort_values(
        ["Priority", "Reported volume"],
        ascending=[True, False],
    )

    if not scan_all:
        markets = markets.head(max_markets)

    st.caption(
        f"Markets selected: {len(markets)} • "
        f"Data fetched: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    st.dataframe(
        markets[["Symbol", "Live price", "Reported volume"]],
        use_container_width=True,
        hide_index=True,
    )

    if st.button("🎯 Run SMC scan"):
        results = []
        progress = st.progress(0)
        status = st.empty()
        total = len(markets)

        for index, row in enumerate(markets.itertuples(index=False), start=1):
            symbol = row[0]
            status.write(f"Scanning {symbol} ({index}/{total})")

            try:
                a15 = analyze(get_candles(symbol, "15m"))
                a1h = analyze(get_candles(symbol, "1h"))
                a4h = analyze(get_candles(symbol, "4h"))

                # Conservative agreement: 4h trend and 1h trend should align.
                if a4h["bias"] == a1h["bias"] and a1h["bias"] in ["LONG", "SHORT"]:
                    if a15["bias"] == a1h["bias"]:
                        final_signal = a1h["bias"]
                        explanation = "15m, 1h and 4h signals agree"
                    else:
                        final_signal = "WAIT"
                        explanation = "Higher-timeframe agreement; 15m confirmation missing"
                else:
                    final_signal = "WAIT"
                    explanation = "1h and 4h are not aligned"

                results.append({
                    "Symbol": symbol,
                    "Signal": final_signal,
                    "15m": a15["bias"],
                    "1h": a1h["bias"],
                    "4h": a4h["bias"],
                    "Price": a15["price"],
                    "15m structure": a15["structure"],
                    "15m FVG": a15["fvg"],
                    "15m liquidity": a15["liquidity"],
                    "Reason": explanation,
                })

            except Exception as exc:
                results.append({
                    "Symbol": symbol,
                    "Signal": "DATA ERROR",
                    "15m": "-",
                    "1h": "-",
                    "4h": "-",
                    "Price": None,
                    "15m structure": "-",
                    "15m FVG": "-",
                    "15m liquidity": "-",
                    "Reason": str(exc)[:160],
                })

            progress.progress(index / total)
            time.sleep(0.1)

        status.empty()
        progress.empty()

        result_df = pd.DataFrame(results)
        st.subheader("SMC scan results")
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        st.download_button(
            "Download scan as CSV",
            data=result_df.to_csv(index=False).encode("utf-8"),
            file_name="smc_coin_hunter_scan.csv",
            mime="text/csv",
        )

        st.info(
            "This initial version identifies simplified structure and imbalance "
            "patterns. It does not calculate a validated entry, stop-loss, or "
            "profit target. Verify every setup on the chart before making decisions."
        )

except requests.RequestException as exc:
    st.error(
        "Cannot connect to Delta Exchange market data right now. "
        "Check your connection and try again."
    )
    st.caption(f"Technical detail: {str(exc)[:250]}")
except Exception as exc:
    st.error("The scanner could not load the market list.")
    st.caption(f"Technical detail: {str(exc)[:250]}")
