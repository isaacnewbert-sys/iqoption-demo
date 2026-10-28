# Demo automation v23

Explicit start only, PRACTICE account only, one 1-unit digital position at a time. CALL/PUT decisions use a deterministic experimental reversal hypothesis: 20-bar support/resistance, rejection wick on the last completed 1-minute bar, live breakout of that bar, and a completed 5-minute trend filter. It is not an implementation of all ten strategies or institutional tape reading and has no demonstrated trading edge.

The session records a freshly queried PRACTICE balance before any first entry, after confirming there are no existing digital positions. The fixed realized-profit target is 1% of that balance. Only this session's broker-confirmed realized trade P/L is counted, including losses; unrealized valuations are not counted. No compounding or automatic baseline reset. Once reached, new entries (including manual tests) are blocked. Explicitly preparing a new session clears the prior local session record; it does not send an order.

Each position attempts broker resale at net profit >=8% of its 1-unit stake, using the existing position-valuation monitor. There is no loss stop. Otherwise it remains until expiry. A pause stops new entries; it does not interrupt the position monitor. This is a target, not guaranteed execution at that price. Actual +8% resale has not yet been demonstrated in a live demo test.

Start/stop/new session endpoints require existing panel Basic authentication and X-Demo-Panel:1. Credentials stay in Render environment variables. Real accounts are rejected. Data gaps, missing or stale live candle formats, stale contract quotes, wrong balances, previous positions, ambiguous submissions or missing realized close confirmation prevent new orders. Unknown order/position outcomes lock the session for manual reconciliation. The strategy is reassessed immediately before sending; the same signal is not reused within a session. SDK silence is bounded by the parent watchdog.

A run lasts at most six hours before new entries pause; an already open position is still monitored. There is no auto-resume after restart. SQLite session/journal data live on Render's ephemeral filesystem and may be lost after redeploy or restart; this free service cannot guarantee continuous unattended operation. Check IQ PRACTICE positions and previous results before starting again. Do not run a concurrent external bot or manually trade the same demo wallet while testing a session.

Panel controls:
- Iniciar / retomar sessão demo automática
- Pausar novas entradas
- Preparar nova sessão (explicitly clears the previous session record only when inactive and not uncertain)

Validation: python -m unittest test_strategy_session.py test_profit_exit.py test_demo_order.py test_fast_diagnostics.py test_panel_state.py
