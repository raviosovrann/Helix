import { Link } from 'react-router-dom'
import type { BotView } from '../types'
import { LiveBadge } from './LiveBadge'
import { BotStatusPill } from './StatusPill'
import { marketLabel, venueLabel } from '../labels'

function positionText(bot: BotView): string {
  const pos = bot.position
  if (!pos || pos.side === 'flat') return '—'
  return `${pos.side} ${pos.size} @ ${pos.entry_price}`
}

/** Statuses where the bot is mid-transition and must not be acted on again. */
const TRANSITIONAL = new Set(['starting', 'stopping'])

/** Live table of all bots; row actions delegate confirmation to the parent. */
export function BotTable({
  bots,
  onStart,
  onStop,
  busyIds = [],
}: {
  bots: BotView[]
  onStart: (bot: BotView) => void
  onStop: (bot: BotView) => void
  /** Bots with a lifecycle request already in flight from this client. */
  busyIds?: string[]
}) {
  if (bots.length === 0) {
    // An empty state should say what this screen is for and offer the one
    // action that resolves it, rather than only reporting the absence (#164).
    return (
      <div className="empty-state" data-testid="bots-empty">
        <p className="empty-title">No bots yet</p>
        <p className="muted">
          A bot watches one symbol on one timeframe and routes its strategy&apos;s signals to a
          venue. New bots start in dry-run, so nothing is sent to a real market until you arm it.
        </p>
        <Link to="/bots/new" className="button-link primary">
          Create your first bot
        </Link>
      </div>
    )
  }
  return (
    <div className="table-wrap">
      <table className="bot-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Venue</th>
            <th>Market</th>
            <th>Strategy</th>
            <th>Mode</th>
            <th>Status</th>
            <th>Position</th>
            <th>PnL</th>
            <th>Last signal</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {bots.map((bot) => (
            <tr key={bot.id}>
              <td>
                <Link to={`/bots/${bot.id}`}>{bot.symbol}</Link>
              </td>
              <td>{venueLabel(bot.venue)}</td>
              <td>{marketLabel(bot.market_type)}</td>
              <td>{bot.strategy}</td>
              <td>
                <LiveBadge live={bot.live} />
              </td>
              <td>
                <BotStatusPill bot={bot} />
              </td>
              <td>{positionText(bot)}</td>
              <td className={`pnl ${bot.pnl < 0 ? 'pnl-neg' : bot.pnl > 0 ? 'pnl-pos' : ''}`}>
                {/* Signed and tabular so a column of PnL scans as a column of
                  numbers, and a loss is legible without relying on colour. */}
                {bot.pnl > 0 ? '+' : ''}
                {bot.pnl.toFixed(2)}
              </td>
              <td className="muted">{bot.last_decision ?? '—'}</td>
              <td>
                {(() => {
                  // Busy either because this client has a request in flight, or
                  // because the server reports the bot mid-transition (another
                  // operator, or a reload mid-start).
                  const busy = busyIds.includes(bot.id) || TRANSITIONAL.has(bot.status)
                  return bot.status === 'running' ? (
                    <button disabled={busy} onClick={() => onStop(bot)}>
                      Stop
                    </button>
                  ) : (
                    <button disabled={busy} onClick={() => onStart(bot)}>
                      {bot.status === 'starting' ? 'Starting…' : 'Start'}
                    </button>
                  )
                })()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
