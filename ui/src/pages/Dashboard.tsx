import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useBots, useStartBot, useStopBot } from '../api/hooks'
import { BotTable } from '../components/BotTable'
import { FleetSummary } from '../components/FleetSummary'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { useAuth } from '../hooks/useAuth'
import { useBotEvents } from '../hooks/useBotEvents'
import type { BotView } from '../types'
import { venueLabel } from '../labels'

interface PendingAction {
  /** Short action name; becomes the dialog's accessible name. */
  title: string
  message: string
  /** Returns the request so the dialog can hold Confirm until it settles. */
  run: () => Promise<unknown>
}

/** Live table of all bots, updated over the WebSocket. */
export function Dashboard() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const { data: bots, isLoading, error } = useBots()
  const queryClient = useQueryClient()
  const startBot = useStartBot()
  const stopBot = useStopBot()
  const [pending, setPending] = useState<PendingAction | null>(null)

  useBotEvents((event) => {
    if (event.type === 'overflow') {
      // Events were dropped for this client, so the table may be stale.
      void queryClient.invalidateQueries({ queryKey: ['bots'] })
    } else if (event.type === 'state') {
      // The snapshot is authoritative and complete — apply it, don't refetch.
      queryClient.setQueryData<BotView[]>(['bots'], (old) =>
        old?.map((b) =>
          b.id === event.bot_id
            ? {
                ...b,
                status: event.status,
                position: event.position,
                pnl: event.pnl,
                last_decision: event.last_decision,
                degraded: event.degraded,
                degraded_reason: event.degraded_reason,
                degraded_permanent: event.degraded_permanent,
              }
            : b,
        ),
      )
    } else if (event.type === 'decision') {
      // Patch the row in place — decisions arrive every bar.
      queryClient.setQueryData<BotView[]>(['bots'], (old) =>
        old?.map((b) => (b.id === event.bot_id ? { ...b, last_decision: event.text } : b)),
      )
    } else if (event.type === 'order') {
      // Fills change position/PnL/status — refetch the authoritative view.
      void queryClient.invalidateQueries({ queryKey: ['bots'] })
    }
  })

  return (
    <main className="page">
      <header className="topbar">
        <h1>
          <span className="brand" aria-hidden="true">
            TC
          </span>
          Trading Console
        </h1>
        <nav className="button-row">
          <Link to="/bots/new" className="button-link primary">
            New bot
          </Link>
          {/* Signing out deliberately returns to the landing page. An expired
              session still goes to /login via ProtectedRoute, because there the
              operator wants to get back in, not read about the product. */}
          <button
            onClick={() => {
              void logout().then(() => navigate('/'))
            }}
          >
            Sign out
          </button>
        </nav>
      </header>

      {bots && bots.length > 0 && <FleetSummary bots={bots} />}

      {isLoading && (
        <div className="skeleton-stack" data-testid="bots-loading">
          <div className="skeleton" style={{ height: '2.5rem' }} />
          <div className="skeleton" style={{ height: '2.5rem' }} />
          <div className="skeleton" style={{ height: '2.5rem' }} />
        </div>
      )}
      {error && (
        <p role="alert" className="state-error">
          Failed to load bots: {String(error)}
        </p>
      )}
      {bots && (
        <BotTable
          bots={bots}
          busyIds={[
            startBot.isPending ? startBot.variables : null,
            stopBot.isPending ? stopBot.variables : null,
          ].filter((id): id is string => typeof id === 'string')}
          onStart={(bot) =>
            setPending({
              title: `Start ${bot.symbol} in ${bot.live ? 'LIVE' : 'dry-run'} mode`,
              message: bot.live
                ? `Real orders will be sent to ${venueLabel(bot.venue)} and can move real money.`
                : 'Orders are logged only; nothing is sent to the venue.',
              run: () => startBot.mutateAsync(bot.id),
            })
          }
          onStop={(bot) =>
            setPending({
              title: `Stop ${bot.symbol}`,
              message: 'The bot stops trading. Any open position is left as it is.',
              run: () => stopBot.mutateAsync(bot.id),
            })
          }
        />
      )}

      <ConfirmDialog
        open={pending !== null}
        title={pending?.title ?? 'Confirm action'}
        message={pending?.message ?? ''}
        onConfirm={async () => {
          // Awaited so the dialog can disable Confirm for the whole request —
          // the single in-flight guard #126 relies on.
          await pending?.run()
          setPending(null)
        }}
        onCancel={() => setPending(null)}
      />
    </main>
  )
}
