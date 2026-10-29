# DEMO candle sequence and concurrent-position changes

## Experimental reversal variants

Strategy version regime-v3-sequences adds REVERSAO_SEQUENCIA_2 and REVERSAO_SEQUENCIA_3. Only completed, consecutive, non-doji 1-minute candles count. Two/three rising closes with bullish bodies seek PUT; falling closes with bearish bodies seek CALL. Four or more consecutive bodies are not truncated into a two/three pattern.

The setup additionally requires lateral/transition context, support/resistance built from 20 bars before the sequence, extension of at least 0.3 ATR per sequence bar, and a final body at most 75% of the previous body or a rejection wick at least 35% of range and at least as large as its body. Entry requires a live opposite break of the last closed candle's extreme, at most 0.5 ATR beyond the trigger. Classified trends continue using existing trend setups; no forced countertrend trades.

These thresholds are experimental implementation choices, not published performance claims. Count, source candle times, extension and confirmation are stored with the analysis in persistent memory. Setup names and strategy version keep both variants separate from prior samples. No martingale or size escalation.

## Time window

No manual or automated placement may be attempted with 60 seconds or less remaining to the actual broker-reported expiry. Both the initial check and the check immediately before the socket write enforce this, using IQ server time. The radar excludes these contracts rather than displaying them as executable candidates. The broker's own earlier purchase/deadtime restriction remains enforced. This concerns each selected contract's expiry; not a phone-clock minute or candle color.

## Multiple positions

The basket previously imposed a global 60-second interval. It now tries up to three candidates per scan, subject to the existing global three-position cap. Before every placement it re-compares all six streams, checks the session goal/stop/uncertainty, rechecks the wallet and available virtual balance, and respects same-pair direction restrictions and used signals. Already accepted positions have independent +8%/expiry monitors.

Network writes and broker validations remain serialized through one SDK connection; this permits concurrent open positions without unsafe simultaneous SDK account mutation. No 60-second wait remains between eligible different markets. An unsuccessful candidate is not retried within that cycle and receives a 15-second retry backoff; another eligible candidate can still proceed. An unknown submission stops the batch, and a missing/stale contract or account check never forces a trade. Single-market mode retains signal deduplication, using a 2-second evaluation cooldown.

Stake remains 100 virtual units, max exposure from three positions 300, fixed session goal 1% of starting balance. The unchanged strategy and the new variants still require forward DEMO validation; more trades do not establish higher expected return.

## Validation

114 unit/integration tests passed locally; network/broker responses are mocked. New tests cover both reversal directions/counts, trend/four-bar/non-confirmed exclusions, no future candle leakage, the exact 60-second boundary and a guard crossing into it, radar exclusion and three different pairs accepted at the same simulated timestamp with independent monitors. Dashboard JavaScript syntax checked. No live orders were sent by these tests.
