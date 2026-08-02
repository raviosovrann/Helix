import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Landing } from './Landing'

function renderLanding() {
  render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>,
  )
}

describe('Landing page', () => {
  it('offers a sign-in route from the navigation', () => {
    // The page exists to explain the product and then get out of the way.
    renderLanding()

    const nav = screen.getByRole('banner')
    const signIn = within(nav).getByRole('link', { name: /sign in/i })
    expect(signIn).toHaveAttribute('href', '/login')
  })

  it('has the three sections the nav links to', () => {
    // Anchor links that land nowhere are worse than no nav at all.
    renderLanding()

    // Scoped to the section nav: the hero also links to #how, and a global
    // query would match both.
    const nav = screen.getByRole('navigation', { name: /sections/i })
    for (const id of ['how', 'features', 'faq']) {
      expect(document.getElementById(id), `#${id} missing`).toBeTruthy()
      expect(within(nav).getByRole('link', { name: new RegExp(id, 'i') })).toHaveAttribute(
        'href',
        `#${id}`,
      )
    }
  })

  it('explains how it works in ordered steps', () => {
    renderLanding()

    const how = document.getElementById('how')
    expect(within(how as HTMLElement).getAllByRole('listitem')).toHaveLength(3)
  })

  it('lists features and FAQ entries', () => {
    renderLanding()

    expect(document.querySelectorAll('.feature')).toHaveLength(6)
    expect(document.querySelectorAll('.faq-item')).toHaveLength(6)
  })

  it('leads with a dry-run promise rather than a profit claim', () => {
    // This is trading software shown to people considering real money. The
    // hero must not imply returns, and the risk note must survive edits.
    renderLanding()

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/guardrails/i)
    expect(screen.getByText(/carries risk, including loss of capital/i)).toBeInTheDocument()
  })

  it('answers the credentials question without requiring any', () => {
    renderLanding()

    const faq = document.getElementById('faq') as HTMLElement
    expect(within(faq).getByText(/paper venue needs no credentials/i)).toBeInTheDocument()
  })

  it('every FAQ question is answered', () => {
    renderLanding()

    document.querySelectorAll('.faq-item').forEach((item) => {
      expect(item.querySelector('summary')?.textContent?.trim()).toBeTruthy()
      expect(item.querySelector('p')?.textContent?.trim()).toBeTruthy()
    })
  })
})
