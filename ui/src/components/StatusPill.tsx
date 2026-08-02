import type { BotView } from '../types'

/** Human wording per status. The pill shows the word, not just a colour (#164). */
const LABELS: Record<string, string> = {
  created: 'Created',
  starting: 'Starting',
  running: 'Running',
  stopping: 'Stopping',
  stopped: 'Stopped',
  failed: 'Failed',
}

/**
 * One status treatment, used identically on the dashboard and the detail page.
 *
 * Statuses used to render as bare text, so an operator scanning a list had to
 * read every row to find the one that had failed. Colour, a dot and the word
 * all carry the state here, so it stays legible without colour vision — which
 * is why this pairs with the a11y work in #132 rather than replacing it.
 */
export function StatusPill({
  status,
  degraded,
  degradedReason,
}: {
  status: string
  /** Running but not receiving market data (#114) — a warning, not a failure. */
  degraded?: boolean
  degradedReason?: string | null
}) {
  const label = LABELS[status] ?? status
  return (
    <span className="status-group">
      <span className={`status status-${status}`}>{label}</span>
      {degraded && (
        <span className="badge-degraded" title={degradedReason ?? undefined}>
          no data
        </span>
      )}
    </span>
  )
}

/** Convenience wrapper for a whole bot, so callers cannot mismatch the fields. */
export function BotStatusPill({ bot }: { bot: BotView }) {
  return (
    <StatusPill status={bot.status} degraded={bot.degraded} degradedReason={bot.degraded_reason} />
  )
}
