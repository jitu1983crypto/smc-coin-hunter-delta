# SMC Coin Hunter Pro — Delta Exchange (starter build)

This is a starter research dashboard that reads public Delta Exchange India market data and ranks perpetual futures using a simplified SMC-inspired rule set.

## Included
- Delta Exchange India public products, tickers and OHLC candle endpoints
- 1H setup checks and 4H EMA trend context
- Approximate BOS, liquidity sweep, FVG and FVG-retest checks
- Rule-based confluence score and indicative stop/targets
- CSV export
- No API key and no order placement

## Important limitations
- This is an early prototype, not a validated profitable strategy.
- The rules are approximations and are not an exact reproduction of the user's TradingView Pine Script.
- Scores are confluence points, not win probabilities.
- Entry zones, stops and targets are illustrative estimates and do not account for all contract specifications, fees, funding, slippage or liquidation risk.
- No background scanner, Telegram/WhatsApp push notification, persistent signal history, backtesting engine, or auto-trading is included yet.
- Public cloud deployments may sleep or have limited resources. Always-on scanning and push notifications require an appropriate continuously running host/worker.

## Run locally
1. Install Python 3.10+.
2. In the project folder:
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```
3. Open the displayed local address.

## Deploy to a cloud dashboard
1. Create/sign in to a GitHub account.
2. Create a repository and upload `app.py`, `requirements.txt`, and `README.md`.
3. Open Streamlit Community Cloud and deploy `app.py` from that repository.
4. Note: Community Cloud apps can hibernate after inactivity; this is not a reliable always-on signal engine. For persistent monitoring, use a paid always-on host/worker after validating the prototype.

## Official API documentation
https://docs.delta.exchange/
