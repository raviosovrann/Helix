import type { BotView } from '../types'

function money(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}$${Math.abs(value).toFixed(2)}`
}

/**
 * Fleet-level answer to "how is everything doing", above the table (#164).
 *
 * The dashboard used to open with a flat list, so the only way to learn that
 * one bot had failed, or that the fleet was net down, was to read every row.
 * These four numbers are what an operator actually scans for.
 */
export function FleetSummary({ bots }: { bots: BotView[] }) {
  const running = bots.filter((b) => b.status === 'running').length
  const failed = bots.filter((b) => b.status === 'failed').length
  const live = bots.filter((b) => b.live).length
  const pnl = bots.reduce((total, b) => total + b.pnl, 0)

  return (
    <section className="stat-row" aria-label="Fleet summary">
      <div className="stat">
        <p className="stat-label">Bots</p>
        <p className="stat-value">
          {running}
          <span className="stat-suffix"> / {bots.length} running</span>
        </p>
      </div>
      <div className="stat">
        <p className="stat-label">Unrealised PnL</p>
        <p className={`stat-value ${pnl > 0 ? 'pnl-pos' : pnl < 0 ? 'pnl-neg' : ''}`}>
          {money(pnl)}
        </p>
      </div>
      <div className="stat">
        <p className="stat-label">Live bots</p>
        {/* Zero is the reassuring answer here, so it is not dressed as an
            alert — but any non-zero count takes the warning colour, because
            "something is trading real money" is the one thing an operator
            must never have to hunt for. */}
        <p className={`stat-value ${live > 0 ? 'stat-alert' : ''}`}>{live}</p>
      </div>
      <div className="stat">
        <p className="stat-label">Failed</p>
        <p className={`stat-value ${failed > 0 ? 'pnl-neg' : ''}`}>{failed}</p>
      </div>
    </section>
  )
}
