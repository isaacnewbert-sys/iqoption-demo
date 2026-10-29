# Persistent demo trade memory — memory-v1-shadow

Prepared for PostgreSQL, not enabled until LEARNING_DATABASE_URL is securely configured.
No paid resource is required. The user created a free external Neon project and configured LEARNING_DATABASE_URL in Render. Activation uses that existing project, never provisions a paid Render database.

## Stored evidence

Each bot order captures its wallet-scoped ID, exact pair (normal/OTC remain distinct), direction, stake, expiry, recorded timestamp, strategy version, setup, regime, trigger, ATR, support/resistance, moving averages, checks and six-pair selection score/feed age when available.
Terminal outcomes come only from broker-confirmed closed positions with finite realized P/L. Entry/outcome writes are idempotent, independently joinable and never overwritten by duplicate events. Acknowledgements, missing positions, stale valuation and unknown sends are not settlement evidence. Credentials are not stored.

Read-only startup history imports the latest 30 broker positions. It is not a complete account export. Multiple order IDs sharing one position's aggregate P/L are excluded from import to avoid duplicating returns. Historical outcomes lacking recorded bot context are retained as unattributed and excluded from training. They must never be claimed as past strategy examples. Manual test orders do not train a strategy without its pre-entry context.

## Continuous evaluation

Completed contextual examples group by exact pair, strategy version, setup, regime and direction. The engine measures win rate, mean stake-normalized return and profit factor. Win rate alone is insufficient for the asymmetric +8% target / expiry loss distribution.

At least 60 contextual closes are needed per group: oldest N-20 for development and newest 20 for temporal validation. All training outcomes must have been known before the first validation entry. Future outcomes are filtered. Approximate two-standard-error bounds must agree in sign across both partitions. A suggested score delta is capped at +/-5. Each evaluation includes a model digest of its ordered evidence and sample counts.

This is a heuristic screening method, not proof of statistical significance, calibrated probability, profitability or improvement. Repeated evaluation, nonstationarity, selection bias and multiple comparisons remain limitations. No score adjustment is applied to actual entries in this version. Promotion requires a separate reviewed change and comparison against the unchanged strategy on forward data.

The memory does not change stake 100, max three positions, +8% trade exit, fixed 1% session goal, demo-only account checks or signal/contract/feed gates. Existing open-position monitoring continues if memory writes fail; memory failures are reported, not mistaken for a trade failure.

## Deployment plan

1. Use the existing Neon Free project (AWS Ohio), with a pooled TLS URL. Observe its free compute/storage/network quotas; continuous trading can exhaust compute allowance. Do not promise unlimited free uptime.
2. Set its external pooled TLS connection URL as protected LEARNING_DATABASE_URL. Never commit it. New dependency: psycopg[binary] 3.2.10.
3. Run integration checks on an isolated database: schema creation, idempotent entries/outcomes, process restart retention, wallet isolation, unavailable DB and restore/export.
4. Deploy only after current demo positions finish. Sessions currently use ephemeral SQLite; this change persists learning records only and does not make session control or free web hosting continuous.
5. Check authenticated /status.learning and the memory card. Confirm real writes and import counts; don't report the DB as active based solely on code tests.
6. Back up PostgreSQL independently. Paid hosting is not a substitute for exports, retention policy and recovery tests. Nothing is promised to be retained forever.

## Validation

101 local tests passed (11 new memory tests), plus dashboard JavaScript syntax check. SQLite is an isolated test double, never advertised as durable Render storage. Startup checks commit an isolated non-trade marker and read it through a second PostgreSQL connection, then remove it. Health returns sanitized results only. Summary reads are cached for 15 minutes, including failures; per-trade writes do not invalidate the cache. This reduces reads but does not eliminate compute used by continuous trade writes. Live PostgreSQL integration and forward statistical validation remain pending.
