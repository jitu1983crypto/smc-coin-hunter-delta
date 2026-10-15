import time
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

# ==========================================
# SMC COIN HUNTER PRO
# Delta Exchange market scanner
# ==========================================

st.set_page_config(
    page_title="SMC Coin Hunter Pro",
    page_icon="📊",
    layout="wide"
)

API = "https://api.india.delta.exchange"

st.title("🎯 SMC Coin Hunter Pro")
st.caption(
    "Delta Exchange | Multi-timeframe market scanner"
)

st.warning(
    "Analysis only. Signals are not guaranteed to be "
    "profitable. Verify prices and market conditions "
    "before making any trading decision."
)

# ==========================================
# REFRESH CONTROLS
# ==========================================

if st.button("🔄 Refresh Market Data"):
    st.cache_data.clear()
    st.rerun()

st.caption(
    "Time shown in UTC. Refresh the scanner to request "
    "new market data."
)

# ==========================================
# API REQUEST
# ==========================================

@st.cache_data(ttl=20, show_spinner=False)
def api_get(path, params=None):
    response = requests.get(
        API + path,
        params=params,
        headers={"Accept": "application/json"},
        timeout=15
    )
    response.raise_for_status()

    data = response.json()

    if data.get("success") is False:
        raise ValueError("Delta Exchange API returned an error.")

    return data


# ==========================================
# LOAD LIVE PRODUCTS
# ==========================================

@st.cache_data(ttl=60, show_spinner=False)
def get_products():
    products = []
    cursor = None

    for _ in range(10):
        params = {
            "states": "live",
            "page_size": 100
        }

        if cursor:
            params["after"] = cursor

        data = api_get("/v2/products", params)
        products.extend(data.get("result", []))

        meta = data.get("meta", {})
        next_cursor = meta.get("after")

        if not next_cursor or next_cursor == cursor:
            break

        cursor = next_cursor

    return products


@st.cache_data(ttl=20, show_spinner=False)
def get_tickers():
    data = api_get("/v2/tickers")
    return data.get("result", [])


# ==========================================
# FIND MAIN MARKETS
# ==========================================

ASSETS = {
    "Bitcoin": ["BTC"],
    "Ethereum": ["ETH"],
    "Solana": ["SOL"],
    "Gold": ["XAU", "GOLD"],
    "Silver": ["XAG", "SILVER"]
}


def matches_asset(product, asset):
    symbol = str(product.get("symbol", "")).upper()
    underlying = str(
        product.get("underlying_asset", "")
    ).upper()

    names = ASSETS[asset]

    for name in names:
        if (
            symbol.startswith(name)
            or underlying == name
        ):
            return True

    return False


def choose_product(products, asset):
    candidates = [
        p for p in products
        if matches_asset(p, asset)
    ]

    # Prefer live perpetual futures, then spot.
    def rank(p):
        contract = str(
            p.get("contract_type", "")
        ).lower()

        symbol = str(p.get("symbol", "")).upper()

        if contract == "perpetual_futures":
            return 0
        if contract == "spot":
            return 1
        if "PERPETUAL" in symbol:
            return 2

        return 3

    candidates.sort(key=rank)

    if not candidates:
        return None

    # Prefer an exact base-asset match.
    preferred = {
        "Bitcoin": ["BTCUSD", "BTC_INR"],
        "Ethereum": ["ETHUSD", "ETH_INR"],
        "Solana": ["SOLUSD", "SOL_INR"],
        "Gold": ["XAUUSD", "GOLDUSD"],
        "Silver": ["XAGUSD", "SILVERUSD"]
    }

    for symbol in preferred[asset]:
        for p in candidates:
            if str(p.get("symbol", "")).upper() == symbol:
                return p

    return candidates[0]


# ==========================================
# GET CANDLE DATA
# ==========================================

@st.cache_data(ttl=20, show_spinner=False)
def get_candles(symbol, resolution, count=120):
    now = int(time.time())

    seconds = {
        "15m": 900,
        "1h": 3600,
        "4h": 14400
    }[resolution]

    start = now - (count + 5) * seconds

    data = api_get(
        "/v2/history/candles",
        {
            "resolution": resolution,
            "symbol": symbol,
            "start": start,
            "end": now
        }
    )

    rows = data.get("result", [])

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    required = [
        "time", "open", "high",
        "low", "close", "volume"
    ]

    if not all(c in df.columns for c in required):
        return pd.DataFrame()

    for col in [
        "open", "high", "low", "close", "volume"
    ]:
        df[col] = pd.to_numeric(
            df[col], errors="coerce"
        )

    df["time"] = pd.to_numeric(
        df["time"], errors="coerce"
    )

    df = df.dropna(
        subset=["time", "open", "high", "low", "close"]
    )

    df = df.sort_values("time").drop_duplicates(
        subset=["time"]
    )

    return df.tail(count).reset_index(drop=True)


# ==========================================
# TECHNICAL ANALYSIS
# ==========================================

def analyse(df):
    if len(df) < 55:
        return {
            "trend": "INSUFFICIENT DATA",
            "signal": "WAIT",
            "fvg": "Not available",
            "liquidity_high": None,
            "liquidity_low": None,
            "close": None,
            "candle_time": None
        }

    close = df["close"]

    ema20 = close.ewm(
        span=20, adjust=False
    ).mean()

    ema50 = close.ewm(
        span=50, adjust=False
    ).mean()

    last = len(df) - 1

    if ema20.iloc[last] > ema50.iloc[last]:
        trend = "BULLISH"
    elif ema20.iloc[last] < ema50.iloc[last]:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    # Three-candle Fair Value Gap detection.
    recent = df.tail(30).reset_index(drop=True)

    bullish_gaps = []
    bearish_gaps = []

    for i in range(2, len(recent)):
        first = recent.iloc[i - 2]
        third = recent.iloc[i]

        if third["low"] > first["high"]:
            bullish_gaps.append(
                (first["high"], third["low"])
            )

        if third["high"] < first["low"]:
            bearish_gaps.append(
                (third["high"], first["low"])
            )

    if bullish_gaps and bearish_gaps:
        fvg_text = (
            f"Bullish: {len(bullish_gaps)} | "
            f"Bearish: {len(bearish_gaps)}"
        )
    elif bullish_gaps:
        fvg_text = f"Bullish: {len(bullish_gaps)}"
    elif bearish_gaps:
        fvg_text = f"Bearish: {len(bearish_gaps)}"
    else:
        fvg_text = "No recent FVG detected"

    # Recent swing levels: potential liquidity areas.
    liquidity_high = float(
        df["high"].iloc[-21:-1].max()
    )

    liquidity_low = float(
        df["low"].iloc[-21:-1].min()
    )

    # Use completed candles for break detection.
    previous_high = float(
        df["high"].iloc[-11:-1].max()
    )

    previous_low = float(
        df["low"].iloc[-11:-1].min()
    )

    previous_close = float(df["close"].iloc[-2])
    current_close = float(df["close"].iloc[-1])

    bullish_break = (
        current_close > previous_high
        and previous_close <= previous_high
    )

    bearish_break = (
        current_close < previous_low
        and previous_close >= previous_low
    )

    signal = "WAIT"

    if bullish_break and trend == "BULLISH":
        signal = "BUY WATCH"

    elif bearish_break and trend == "BEARISH":
        signal = "SELL WATCH"

    return {
        "trend": trend,
        "signal": signal,
        "fvg": fvg_text,
        "liquidity_high": liquidity_high,
        "liquidity_low": liquidity_low,
        "close": current_close,
        "candle_time": int(df["time"].iloc[-1])
    }


# ==========================================
# DISPLAY MAIN MARKETS
# ==========================================

try:
    with st.spinner("Loading Delta Exchange markets..."):
        products = get_products()
        tickers = get_tickers()

    ticker_map = {
        str(t.get("symbol", "")).upper(): t
        for t in tickers
    }

    market_results = []

    for asset in ASSETS:
        product = choose_product(products, asset)

        if product is None:
            market_results.append({
                "Asset": asset,
                "Symbol": "Not found",
                "Price": "Unavailable",
                "15m": "WAIT",
                "1H": "WAIT",
                "4H": "WAIT",
                "Status": "No matching live contract"
            })
            continue

        symbol = str(product.get("symbol", ""))
        ticker = ticker_map.get(symbol.upper(), {})

        price = (
            ticker.get("mark_price")
            or ticker.get("close")
            or ticker.get("spot_price")
        )

        result = {
            "Asset": asset,
            "Symbol": symbol,
            "Price": (
                float(price)
                if price is not None
                else None
            ),
            "Status": "Checking candles"
        }

        analyses = {}

        for tf in ["15m", "1h", "4h"]:
            try:
                df = get_candles(symbol, tf)

                # Exclude the currently forming candle.
                if len(df) > 1:
                    df = df.iloc[:-1].reset_index(drop=True)

                analyses[tf] = analyse(df)

            except Exception:
                analyses[tf] = {
                    "trend": "DATA ERROR",
                    "signal": "WAIT",
                    "fvg": "Unavailable",
                    "liquidity_high": None,
                    "liquidity_low": None,
                    "close": None,
                    "candle_time": None
                }

        a15 = analyses["15m"]
        a1h = analyses["1h"]
        a4h = analyses["4h"]

        # Conservative multi-timeframe confirmation.
        signal = "WAIT"

        if (
            a15["signal"] == "BUY WATCH"
            and a1h["trend"] == "BULLISH"
            and a4h["trend"] == "BULLISH"
        ):
            signal = "BUY WATCH"

        elif (
            a15["signal"] == "SELL WATCH"
            and a1h["trend"] == "BEARISH"
            and a4h["trend"] == "BEARISH"
        ):
            signal = "SELL WATCH"

        candle_time = a15.get("candle_time")

        if candle_time is None:
            status = "Candle data unavailable"
        else:
            age = time.time() - candle_time

            if age > 1800:
                status = "STALE DATA - DO NOT USE"
            else:
                status = "Candle data received"

        market_results.append({
            "Asset": asset,
            "Symbol": symbol,
            "Price": result["Price"],
            "15m": a15["trend"],
            "1H": a1h["trend"],
            "4H": a4h["trend"],
            "Signal": signal,
            "FVG (15m)": a15["fvg"],
            "Liquidity High": a15["liquidity_high"],
            "Liquidity Low": a15["liquidity_low"],
            "Last Candle UTC": (
                datetime.fromtimestamp(
                    candle_time, timezone.utc
                ).strftime("%Y-%m-%d %H:%M")
                if candle_time is not None
                else "Unavailable"
            ),
            "Status": status
        })

    st.subheader("📊 Main Market Scanner")

    st.dataframe(
        pd.DataFrame(market_results),
        use_container_width=True,
        hide_index=True
    )

    st.subheader("🔎 Individual Market Analysis")

    for item in market_results:
        with st.expander(
            f"{item['Asset']} — {item['Symbol']}"
        ):
            st.write("Price:", item["Price"])
            st.write("15-minute trend:", item["15m"])
            st.write("1-hour trend:", item["1H"])
            st.write("4-hour trend:", item["4H"])
            st.write("Signal:", item.get("Signal", "WAIT"))
            st.write("FVG:", item.get("FVG (15m)", "Unavailable"))
            st.write(
                "Potential liquidity high:",
                item.get("Liquidity High")
            )
            st.write(
                "Potential liquidity low:",
                item.get("Liquidity Low")
            )
            st.write("Data status:", item["Status"])

    st.caption(
        "Signal logic uses EMA trend and recent price breaks. "
        "FVG and liquidity levels are simplified estimates, "
        "not a complete SMC model. This scanner does not "
        "place trades."
    )

    st.caption(
        "Last page refresh (UTC): "
        + datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

except Exception as e:
    st.error(
        "Unable to load Delta Exchange market data. "
        "Please refresh and try again."
    )

    st.caption(
        "Technical details: "
        + str(e)[:250]
    ) 
