import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusPill } from './StatusPill'

describe('StatusPill (#164)', () => {
  it('names the status in words, not only colour', () => {
    render(<StatusPill status="running" />)

    // The word itself is the assertion: colour alone must never carry meaning.
    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('carries the status in a class so each state reads differently', () => {
    const { container } = render(<StatusPill status="failed" />)

    expect(container.querySelector('.status-failed')).toBeInTheDocument()
  })

  it('falls back to the raw status rather than rendering nothing', () => {
    // A status the UI has not been taught about must still be visible; a bot
    // whose state vanished from the table would look like it had no state.
    render(<StatusPill status="quarantined" />)

    expect(screen.getByText('quarantined')).toBeInTheDocument()
  })

  it('shows a degraded bot as still running, with a separate warning', () => {
    // Degraded is not a status (#114): the bot runs, it just has no data. It
    // must not replace the status or the operator will read it as stopped.
    render(<StatusPill status="running" degraded degradedReason="stream closed" />)

    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByText('no data')).toBeInTheDocument()
    expect(screen.getByTitle('stream closed')).toBeInTheDocument()
  })

  it('shows no degraded marker when the bot has data', () => {
    render(<StatusPill status="running" />)

    expect(screen.queryByText('no data')).not.toBeInTheDocument()
  })
})
