import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useCreateBot, useStrategies, useVenues } from '../api/hooks'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { LiveBadge } from '../components/LiveBadge'
import { useAuth } from '../hooks/useAuth'
import { marketLabel, venueLabel } from '../labels'

interface CredField {
  name: string
  label: string
  optional?: boolean
  /** What this value is and where the operator gets it. Every field has one. */
  help: string
  /** Shown greyed in the input as a shape hint, never as a usable value. */
  placeholder?: string
}

// Which credential fields to collect per venue (stored via PUT secrets).
//
// Every field carries help text. These are opaque vendor-specific names — an
// operator staring at "CID" and "Secret" with no guidance cannot tell whether
// they want an account password or an API key, and guessing wrong fails at
// start time with an authentication error that names neither.
const CREDENTIAL_FIELDS: Record<string, CredField[]> = {
  // Paper needs none, and that is the point of it (#116): the demo path exists
  // so an operator can watch a bot trade before handing over any exchange key.
  // Listed explicitly rather than left to the fallback below, which would have
  // demanded Coinbase keys for a venue that authenticates nothing.
  paper: [],
  coinbase: [
    {
      name: 'api_key',
      label: 'API key',
      help: 'Coinbase → Settings → API → New API key, with "trade" permission.',
    },
    {
      name: 'api_secret',
      label: 'API secret',
      help: 'Shown once when the key is created. If you did not save it, make a new key.',
    },
  ],
  // Four, not six. Tradovate's accesstokenrequest schema marks appId and
  // appVersion optional and only echoes them back, so the venue supplies its
  // own defaults rather than asking the operator to invent values. cid/sec are
  // the API key pair; name/password are the two the schema actually requires.
  tradovate: [
    {
      name: 'name',
      label: 'Username',
      help: 'The username you sign in to Tradovate with — not your email.',
    },
    {
      name: 'password',
      label: 'Password',
      help: 'Your Tradovate account password.',
    },
    {
      name: 'cid',
      label: 'API key id',
      help: 'Tradovate → Application Settings → API Access. Shown as "cid".',
    },
    {
      name: 'sec',
      label: 'API key secret',
      help: 'Issued with that key id, and shown as "sec". Not your account password.',
    },
  ],
}

function credFieldsFor(venue: string): CredField[] {
  return CREDENTIAL_FIELDS[venue] ?? CREDENTIAL_FIELDS.coinbase
}

/** One credential input with its explanation, wired for screen readers. */
function CredentialField({
  field,
  value,
  onChange,
}: {
  field: CredField
  value: string
  onChange: (value: string) => void
}) {
  const id = `cred-${field.name}`
  return (
    <div className="field">
      <label htmlFor={id}>
        {field.label}
        {field.optional ? ' (optional)' : ''}
      </label>
      <input
        id={id}
        type="password"
        autoComplete="off"
        placeholder={field.placeholder}
        aria-describedby={`${id}-help`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="field-help" id={`${id}-help`}>
        {field.help}
      </p>
    </div>
  )
}

/** Timeframe syntax the API accepts (#113): a positive integer and a unit. */
const TIMEFRAME_PATTERN = /^[1-9][0-9]*[mhdw]$/

/** Guided bot creation: venue → strategy → params + keys → review. Dry-run default. */
export function NewBot() {
  const navigate = useNavigate()
  const { client } = useAuth()
  const venuesQuery = useVenues()
  const strategiesQuery = useStrategies()
  const createBot = useCreateBot()

  const [step, setStep] = useState(1)
  const [venue, setVenue] = useState('')
  const [marketType, setMarketType] = useState('')
  const [strategy, setStrategy] = useState('')
  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState('1m')
  const [quantity, setQuantity] = useState('0.1')
  const [perBotCap, setPerBotCap] = useState('1000')
  const [globalCap, setGlobalCap] = useState('10000')
  const [live, setLive] = useState(false)
  const [creds, setCreds] = useState<Record<string, string>>({})
  const [confirmLive, setConfirmLive] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const venues = useMemo(() => venuesQuery.data ?? [], [venuesQuery.data])
  const venueNames = useMemo(() => [...new Set(venues.map((v) => v.venue))], [venues])
  const marketsForVenue = useMemo(
    () => venues.filter((v) => v.venue === venue).map((v) => v.market_type),
    [venues, venue],
  )

  // What the chosen pairing can do (#125). Shown rather than silently
  // enforced: the API refuses an unsupported strategy/venue pair, and an
  // operator who cannot see why would just retry the same combination.
  const selectedVenue = useMemo(
    () => venues.find((v) => v.venue === venue && v.market_type === marketType),
    [venues, venue, marketType],
  )

  // Default the venue/market and strategy once their lists load.
  useEffect(() => {
    if (venue === '' && venues.length > 0) {
      setVenue(venues[0].venue)
      setMarketType(venues[0].market_type)
    }
  }, [venue, venues])
  useEffect(() => {
    const list = strategiesQuery.data
    if (strategy === '' && list && list.length > 0) setStrategy(list[0])
  }, [strategy, strategiesQuery.data])

  function onVenueChange(next: string) {
    setVenue(next)
    const markets = venues.filter((v) => v.venue === next).map((v) => v.market_type)
    setMarketType(markets[0] ?? '')
    setCreds({}) // credential fields differ per venue
  }

  const credFields = credFieldsFor(venue)
  // Default to allowing LIVE while the venue list is still loading: absent
  // capabilities must not silently present a real venue as simulated.
  const liveCapable = selectedVenue?.supports_live ?? true

  // Symbol format differs by market, so the hint has to as well. Typing
  // "BTC/USD" into a futures bot earns a venue rejection at start time that
  // explains nothing.
  const symbolHelp =
    marketType === 'futures'
      ? 'Contract symbol including its month and year code — e.g. CLU6 for September 2026 crude oil.'
      : 'Market pair as the exchange lists it, base first — e.g. BTC/USD.'

  const timeframeError =
    timeframe.trim() !== '' && !TIMEFRAME_PATTERN.test(timeframe.trim())
      ? `"${timeframe}" is not a valid timeframe. Use a number and a unit, like 30m or 4h.`
      : null

  const step3Valid =
    symbol.trim() !== '' &&
    Number(quantity) > 0 &&
    timeframeError === null &&
    timeframe.trim() !== '' &&
    credFields.every((f) => f.optional || (creds[f.name] ?? '').trim() !== '')

  function onLiveToggle(checked: boolean) {
    if (checked) setConfirmLive(true)
    else setLive(false)
  }

  async function onCreate() {
    setError(null)
    try {
      const nonEmptyCreds = Object.fromEntries(
        Object.entries(creds).filter(([, v]) => v.trim() !== ''),
      )
      if (Object.keys(nonEmptyCreds).length > 0) {
        await client.putSecrets(venue, marketType, nonEmptyCreds)
      }
      const bot = await createBot.mutateAsync({
        venue,
        market_type: marketType,
        strategy,
        symbol: symbol.trim(),
        timeframe,
        quantity: Number(quantity),
        live,
        per_bot_cap: Number(perBotCap),
        global_cap: Number(globalCap),
        params: {},
      })
      navigate(`/bots/${bot.id}`)
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <main className="page">
      <header className="topbar">
        <h1>New bot</h1>
        <Link to="/dashboard" className="button-link">
          Cancel
        </Link>
      </header>

      {/* Progress as a bar rather than "step 3 of 4" in the title: the heading
          should say what the page is, not where you are in it. */}
      <ol className="wizard-steps" aria-label={`Step ${step} of 4`}>
        {[1, 2, 3, 4].map((n) => (
          <li key={n} className={`wizard-step ${n <= step ? 'done' : ''}`} />
        ))}
      </ol>

      <div className="card wizard">
        {step === 1 && (
          <>
            <h2>Venue</h2>
            <label htmlFor="venue">Venue</label>
            <select id="venue" value={venue} onChange={(e) => onVenueChange(e.target.value)}>
              {venueNames.map((v) => (
                <option key={v} value={v}>
                  {venueLabel(v)}
                </option>
              ))}
            </select>
            <label htmlFor="market">Market type</label>
            <select id="market" value={marketType} onChange={(e) => setMarketType(e.target.value)}>
              {marketsForVenue.map((m) => (
                <option key={m} value={m}>
                  {marketLabel(m)}
                </option>
              ))}
            </select>
            {selectedVenue && (
              <p className="muted" data-testid="venue-capabilities">
                {selectedVenue.supports_short
                  ? 'Supports long and short positions.'
                  : 'Long only \u2014 this market cannot hold short positions.'}
              </p>
            )}
          </>
        )}

        {step === 2 && (
          <>
            <h2>Strategy</h2>
            <label htmlFor="strategy">Strategy</label>
            <select id="strategy" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {(strategiesQuery.data ?? []).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </>
        )}

        {step === 3 && (
          <>
            <h2>Parameters</h2>
            <label htmlFor="symbol">Symbol</label>
            <input
              id="symbol"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              aria-describedby="symbol-help"
              required
            />
            <p className="field-help" id="symbol-help">
              {symbolHelp}
            </p>

            <label htmlFor="timeframe">Timeframe</label>
            <input
              id="timeframe"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              aria-describedby="timeframe-help"
            />
            <p className="field-help" id="timeframe-help">
              Candle length the strategy evaluates on: a number and a unit. <code>1m</code>,{' '}
              <code>30m</code>, <code>4h</code>, <code>1d</code>.
            </p>
            {timeframeError && (
              <p className="field-error" role="alert">
                {timeframeError}
              </p>
            )}

            <label htmlFor="quantity">Quantity</label>
            <input
              id="quantity"
              inputMode="decimal"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              aria-describedby="quantity-help"
            />
            <p className="field-help" id="quantity-help">
              Size of each order, in the instrument&apos;s own units — coins for crypto, contracts
              for futures. Not dollars.
            </p>

            <label htmlFor="perBotCap">Per-bot cap ($ notional)</label>
            <input
              id="perBotCap"
              inputMode="decimal"
              value={perBotCap}
              onChange={(e) => setPerBotCap(e.target.value)}
              aria-describedby="perBotCap-help"
            />
            <p className="field-help" id="perBotCap-help">
              Most this one bot may have at risk at once, in dollars. An order that would exceed it
              is refused before it reaches the venue.
            </p>

            <label htmlFor="globalCap">Global cap ($ notional)</label>
            <input
              id="globalCap"
              inputMode="decimal"
              value={globalCap}
              onChange={(e) => setGlobalCap(e.target.value)}
              aria-describedby="globalCap-help"
            />
            <p className="field-help" id="globalCap-help">
              Same limit, across every bot you run. The lower of the two applies.
            </p>

            <h2>{credFields.length === 0 ? 'Credentials' : `${venueLabel(venue)} credentials`}</h2>
            {credFields.length === 0 ? (
              <p className="muted" data-testid="no-credentials-needed">
                None needed. {venueLabel(venue)} simulates its fills and never contacts an exchange
                account, so it watches live prices without any API key.
              </p>
            ) : (
              <p className="muted">
                Stored server-side, encrypted at rest — sent once, never shown again.
              </p>
            )}
            {credFields.map((f) => (
              <CredentialField
                key={f.name}
                field={f}
                value={creds[f.name] ?? ''}
                onChange={(v) => setCreds((c) => ({ ...c, [f.name]: v }))}
              />
            ))}
          </>
        )}

        {step === 4 && (
          <>
            <h2>Review</h2>
            <dl className="config-list">
              <dt>Venue</dt>
              <dd>
                {venueLabel(venue)} ({marketLabel(marketType)})
              </dd>
              <dt>Strategy</dt>
              <dd>{strategy}</dd>
              <dt>Symbol</dt>
              <dd>{symbol}</dd>
              <dt>Timeframe</dt>
              <dd>{timeframe}</dd>
              <dt>Quantity</dt>
              <dd>{quantity}</dd>
              <dt>Per-bot cap</dt>
              <dd>{perBotCap}</dd>
              <dt>Mode</dt>
              <dd>
                <LiveBadge live={live} />
              </dd>
            </dl>
            <div className="control-row">
              <input
                id="live"
                type="checkbox"
                checked={live}
                disabled={!liveCapable}
                onChange={(e) => onLiveToggle(e.target.checked)}
              />
              <label htmlFor="live">Enable LIVE trading (default is dry-run)</label>
            </div>
            {!liveCapable && (
              <p className="muted" data-testid="live-unavailable">
                {venueLabel(venue)} cannot trade live: its fills are simulated, so any profit or
                position it reports exists only in this console. Create a bot on a funded venue to
                trade for real.
              </p>
            )}
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
          </>
        )}

        <div className="button-row">
          {step > 1 && <button onClick={() => setStep((s) => s - 1)}>Back</button>}
          {step < 4 && (
            <button onClick={() => setStep((s) => s + 1)} disabled={step === 3 && !step3Valid}>
              Next
            </button>
          )}
          {/* Red is reserved for real money (#164). Creating a dry-run bot is
              not a destructive act, and colouring it as one teaches the
              operator to ignore the colour that matters. */}
          {step === 4 && (
            <button
              className={live ? 'danger' : 'primary'}
              onClick={onCreate}
              disabled={createBot.isPending}
            >
              {createBot.isPending ? 'Creating…' : 'Create bot'}
            </button>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmLive}
        message={`Create this bot in LIVE mode? It will send real orders to ${venueLabel(venue)} once started.`}
        onConfirm={() => {
          setLive(true)
          setConfirmLive(false)
        }}
        onCancel={() => setConfirmLive(false)}
      />
    </main>
  )
}
