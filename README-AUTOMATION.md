# IQ Lab · demo automation v28

Only PRACTICE trading is enabled. Fixed stake: **100 units of the demo wallet's currency per order** (not 100 BRL unless the account itself is BRL). At most three simultaneous positions, for up to 300 units committed. The amount is fixed in settings.py and is never taken from request JSON. Real-wallet selection, a changed wallet identity and non-PRACTICE profiles block trading.

## Six-market scanner

Choose **6 pares · Mercado normal** (MAJORS) or **6 pares · Mercado OTC** (MAJORS-OTC). Both baskets contain EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD and USDCHF; the latter explicitly requests each -OTC variant. Individual markets remain available for diagnostics and manual tests. No normal/OTC substitution occurs.

One IQ websocket connection maintains six market-specific candle/instrument/quote streams. Historical candle requests for all six markets are sent without waiting for each individual response, and unique request IDs correlate out-of-order replies. Price events are checked against the requested asset ID. The pinned SDK's shared candle buffer is not used by the basket. Requests to the socket are serialized; read-side callbacks fan out safely. Only available, unsuspended catalogue assets are subscribed. All requested markets appear in the radar, including unavailable ones.

Every two seconds, the scanner evaluates the six current market snapshots with the same server-time reference. A candidate requires continuous history, a live candle no older than 3 seconds, historical data received within 35 seconds, a valid current 5-minute CALL/PUT contract and quote, an unused signal and available portfolio capacity. Historical context and indicators never use future candles. No signal means no order.

For every new order, the entire basket is compared again immediately before the write. If the selected signal is no longer the highest-ranked eligible signal, the write is blocked. The executed pair, score, comparison timestamp and selection rule are recorded. Global spacing remains at least 60 seconds between attempts. The same candle/signal is not reused on a pair. Opposite positions on the same pair are blocked; directions on different pairs can differ.

### Priority is not win probability

The deterministic, uncalibrated priority score uses: base 30; context quality up to 20; proximity to the trigger up to 20; space before the nearby barrier up to 15; and relative bid/ask quote spread up to 15. Trend context uses directional efficiency; range/transition context uses its inverse. Trigger proximity is normalized by ATR. Available space is normalized by 2 ATR, with a neutral .25 factor when a forward barrier is unknown/already crossed. Quote-cost factor is 1 - (ask - bid)/ask. Ties are resolved by the requested pair name. These weights are an experimental ordering rule, not a demonstrated edge or forecast of returns.

## Strategy and exits

The regime-v2 strategy uses 1-minute EMA9/EMA21, their slope, directional efficiency, complete 5-minute EMA3/EMA8 context and Wilder ATR14. Trend setups: pullback/resumption or breakout with a held retest. Range/transition setups: rejection at an extreme or failed break followed by reclaim and a higher low/lower high. Actual entry requires an intrabar trigger and a bounded extension. At least 65 continuous complete 1-minute bars and the current live bar are required. Context and regions use past data only. This does not implement institutional tape reading, all ten requested strategies, WCCI from screenshots, or generative-AI trading decisions.

Each accepted order gets its own amount-verified order-to-position mapping and resale monitor. For a stake of 100, +8% means **8 net currency units**, e.g. gross resale proceeds of 108. Net profit is validated against the broker's own valuation; movement in the underlying price is not treated as realized option profit. Stale or inconsistent valuations do not trigger a close. An ACK is not a confirmed position closure. Unknown submissions/closes are not blindly retried.

There is no loss stop. If the target is not reached, the position remains until expiry. Actual execution prices and realized profit can vary. A triggered +8% live demo resale and profitability of the expanded strategy still need practical validation.

## Fixed session target

Before the first entry, after confirming no pre-existing digital positions, the session records a fresh PRACTICE wallet balance. The fixed target is 1% of this balance, aggregated across all pairs. Only broker-confirmed realized P/L of this session's orders is counted, including losses; no compounding or automatic baseline reset. Settlements are deduplicated by order ID and recorded atomically.

Once the target has been reached, new entries remain blocked even if other open positions later lose. Existing positions continue to their own +8% target or expiry, so final session profit can fall below 1%. Pause only stops new entries and leaves all accepted orders monitored. An uncertain result locks the entire session until reconciled; another position closing cannot clear that uncertainty.

## Dashboard and deployment limits

The authenticated responsive dashboard shows initial balance, realized P/L, target progress, a six-row radar with candidate priorities/blockages, per-position pair/amount/P&L, analysis checks, and the last 20 settled journal records. Technical JSON is collapsed. Example data is used only in local browser QA, never in production. Basic-auth username is isaac; password comes from PANEL_PASSWORD. IQ credentials remain in protected Render environment variables and are never solicited in the dashboard. All modifying panel requests require X-Demo-Panel:1.

Run duration is at most six hours before new entries pause; accepted positions are still monitored. No restart auto-resumes trading. SQLite state and journal files are ephemeral and may be lost on redeploy/restart. Free hosting can suspend while idle and cannot guarantee uninterrupted unattended trading. Check positions in IQ before starting a new session. Do not concurrently run another bot or manually trade the same demo wallet during a session.

The unofficial protocol can return no usable contracts even for a listed asset; unavailable markets stay excluded and visible in the radar. A public-Git-URL Render service needs a manual deploy after source updates.

Validation:

    python -m unittest test_basket.py test_regime_strategy.py test_strategy_session.py test_multi_position.py test_profit_exit.py test_demo_order.py test_fast_diagnostics.py test_panel_state.py test_streaming.py

Tests cover six request streams, out-of-order history isolation, normal/OTC separation, causal indicator/setups, stale-data and contract rejection, ranking/revalidation, unknown submission locks, fixed amount 100, +8% monetary math, independent three-position monitoring, fourth-entry blocking, fixed session target, authentication and browser output integrity. Browser QA covers widths 320, 360, 412, 768 and 1440, basket/manual controls and escaping with mock API responses only. No broker orders are sent by these tests.
