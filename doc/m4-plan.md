# M4 — End-to-End Demo and Venue Readiness

Eight issues: #130, #116, #119, #117, #123, #120, #133, #164.

## The structural finding that sets the build order

**The product cannot currently be demonstrated at all.** Three issues are one
story, not three:

- `registry.py` refuses to build a ccxt venue without `api_key`/`api_secret`
  **even when `live=False`**, so a new operator cannot start a dry-run bot.
- The only registered strategy, `example`, returns `None` unconditionally. A bot
  that does start shows "no signal" forever.
- The Playwright smoke stops after *creating* a bot and is not wired into CI.

So nothing downstream of "a bot that runs and emits an order" can be observed,
which is also why #164 (UI polish) has no real states to polish and why #117 has
no path to assert on.

One fact makes the demo cheap: **Coinbase spot market data is already
credential-free.** `hub_factory.py` builds `CoinbaseCandleFeed` /
`CoinbaseStreamFeed` with no keys at all. The gap in #116 is purely on the
*execution* side.

⇒ **Build order is not issue order:** `#130 → #116 → #119 → #164 → #117 → #123 → #120 → #133`.

`#130` leads because both new strategies (#119's demo strategy and the crude-oil
strategy) read candles through `StrategyContext`. Writing them against a
contract typed `Any`, with a warmup cache that returns the wrong depth, means
writing them twice — the same reasoning that put the ledger first in M3.

## Scope split imposed by credentials

Tradovate API access and extended market-data history arrive **Mon 2026-08-03/04**
(funds deposited 2026-08-01, two business days to clear).

- **Buildable and verifiable now:** #130, #116, #119, #164, #117.
- **Buildable now, verifiable Monday:** #123 (the environment × execution-mode
  matrix is pure modelling; its matrix test uses fakes) and #120's backend login
  flow (fake-auth integration tests, per its own acceptance criteria).
- **Blocked until Monday:** #133. Contract tests written blind would encode the
  same assumed request/response shapes the issue exists to disprove. Write the
  harness, leave the job skipping when secrets are absent, run it Monday.

## Decisions taken before starting

1. **The demo runs on real market data, not a simulation.** `PaperVenue`
   simulates *fills*; candles are genuine public Coinbase. A fully synthetic
   demo would prove nothing about the real data path, which is the seam #117
   exists to cover.
2. **CI is the one exception.** #117's smoke injects a deterministic feed. That
   is a test double inside CI, not a demo mode — a CI job reaching out to
   Coinbase would be flaky and would fail on a quiet market. Same `PaperVenue`,
   two different data sources.
3. **Paper is a separate venue, not a mode of the live one.** `("paper", "spot")`
   gets its own registry entry. #116 asks for a *clearly isolated* path;
   relaxing the credential check on the real coinbase venue when `live=False`
   would make the isolated case a branch inside the live one, which is the shape
   most likely to let a misconfiguration reach a private endpoint.
4. **Tradovate is gated, not deleted.** #120's acceptance criteria say to mark it
   unavailable until #96 (market-data feed, still open and unmilestoned) is
   demo-verified. Implemented as a readiness flag the UI reads and reports a
   reason for, so it flips on once #96 is verified against demo rather than
   requiring the code to come back.
5. **Crude oil cannot run on real bars before Monday.** CL is a Tradovate
   futures product and Coinbase — the only credential-free source — does not
   list it. The strategy is implemented and unit-tested against its own candle
   fixtures; pointing it at live CL 30m is a credentials switch.

## #130 — the typed strategy data contract

Three defects, one contract:

- `StrategyContext.data_feed` is typed `Any` and documented as a feed exposing
  synchronous `warmup_candles()`, but the supervisor passes `MarketDataHub`,
  which exposes **async** `warmup()`. The no-op `example` strategy masks the
  mismatch; the first strategy that reads data hits it.
- `MarketDataHub.warmup()` caches on `(symbol, timeframe)` **without depth**, so
  a 20-candle request poisons a later 200-candle one, and a 200-candle request
  returns 200 rows to a later caller that asked for 20. Results depend on call
  order.
- Strategy evaluation is synchronous and runs on a per-bot worker lane, so it
  cannot await.

**Resolution — prefetch, not an async strategy API.** Making `on_bar` async
would push the event loop into every strategy author's problem space for no
gain, since the runtime already knows which timeframes a strategy needs before
it starts. Instead:

- A narrow `MarketData` protocol replaces `Any`: synchronous `candles(symbol,
  timeframe, limit)` and `latest_price(symbol, timeframe)`, both non-blocking.
- Strategies declare required history the same way #125 made them declare venue
  requirements — opt-in, empty default, so existing strategies stay valid.
- The supervisor prefetches those timeframes on the event loop and refreshes
  them on the existing poll tick. The strategy reads a populated snapshot.
- Cache depth semantics: store the deepest fetch for a key and return the
  **newest `limit`** from it. A deeper request refetches; a shallower one slices.

## #164 — design direction (agreed before restyling)

Reference: `agentictraders.io`. The direction, so the pass is one system rather
than ad-hoc restyling:

- **Surface** — near-black, faintly green-tinted background; cards a step
  lighter with a low-contrast border and generous internal padding.
- **Accent** — a single mint/spring green, used for primary action and positive
  state only. A soft outer glow on the primary button, nowhere else.
- **Type** — large, tight-tracked headings against muted grey body copy. The
  contrast between the two carries the hierarchy.
- **Status vocabulary** — pill chips with a leading dot, one colour per state
  (`created`/`starting`/`running`/`stopping`/`stopped`/`failed`), used
  identically on the dashboard and the detail page.
- **LIVE** — must be unmissable and must not read as "positive". It takes a
  warning treatment that deliberately breaks the green system, so it can never
  be confused with a healthy state.
- **Colour is never the sole carrier of meaning** — every state pairs its colour
  with a dot shape and a text label (pairs with the a11y work in #132).

Dashboard first — status, LIVE and PnL scannability is where the visual
impression is actually made — then the detail page, then the wizard.
