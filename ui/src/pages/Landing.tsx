import { Link } from 'react-router-dom'

/**
 * Public marketing page shown before sign-in.
 *
 * Every claim here is deliberately limited to what the application actually
 * does today. A landing page that promises capabilities the product does not
 * have is the fastest way to lose the first operator it convinces -- and the
 * feature list below is checked against the shipped venues, strategies and
 * risk controls, not aspirations.
 */

const STEPS = [
  {
    title: 'Pick a venue and a strategy',
    body: 'Coinbase spot or futures, Tradovate futures, or the built-in paper venue that needs no credentials at all. The console only offers pairings it can actually execute.',
  },
  {
    title: 'Set the limits first',
    body: 'A per-bot and a global notional cap, applied before an order reaches the venue. Bots are created in dry-run, so nothing is sent to a real market until you arm it deliberately.',
  },
  {
    title: 'Watch it work, then arm it',
    body: 'Decisions, orders, fills, position and PnL stream to the dashboard as they happen. Going live is a separate, confirmed action — never a default.',
  },
]

const FEATURES = [
  {
    title: 'Credential-free paper trading',
    body: 'The paper venue simulates fills against real, live market data. You can watch a strategy trade a genuine market before handing over a single API key — and it can never be armed.',
  },
  {
    title: 'Risk limits that fail closed',
    body: 'Exposure is tracked per order, per bot and across the fleet. An order that would breach a cap is refused before submission, not reconciled afterwards.',
  },
  {
    title: 'A durable order ledger',
    body: 'Every submission, fill, cancellation and rejection is recorded as an event. Restarting the service replays the log, so the console and the venue do not drift apart.',
  },
  {
    title: 'Dry-run by default',
    body: 'Every bot starts logging orders instead of sending them. LIVE is a distinct mode with its own confirmation, its own audit entry, and an unmissable badge.',
  },
  {
    title: 'Every decision logged',
    body: 'Each evaluated bar records what the strategy decided and why it did or did not trade — so a quiet bot can be told apart from a broken one.',
  },
  {
    title: 'Run many bots at once',
    body: 'Bots on the same market share one data feed and one rate limiter, so request volume scales with the markets you trade rather than the number of bots.',
  },
]

const FAQ = [
  {
    q: 'Do I need exchange API keys to try it?',
    a: 'No. The paper venue needs no credentials. It reads real public market data and simulates the fills, so you can run a strategy end to end before deciding whether to connect an account.',
  },
  {
    q: 'What stops a bot from spending real money by accident?',
    a: 'Three things. Bots are created in dry-run and orders are logged rather than sent. Switching to LIVE is a separate confirmed action recorded in the audit log. And the paper venue refuses to be armed at all — the API rejects it at creation and at update.',
  },
  {
    q: 'Which markets are supported?',
    a: 'Coinbase spot and futures, and Tradovate futures. Paper trading runs on live Coinbase spot data. Support is declared per venue, so the console will not offer a strategy a venue cannot execute — a long-only spot market will not accept a short.',
  },
  {
    q: 'Can I bring my own strategy?',
    a: 'Yes. Strategies are plugins: implement one method, declare the history you need, and register it. The console handles data, routing, risk, execution and record-keeping.',
  },
  {
    q: 'What happens if the service restarts mid-trade?',
    a: 'Bot configurations are persisted, and the order ledger is rebuilt by replaying its log. Orders that were still open come back open and go straight onto the reconciliation worklist rather than being silently forgotten.',
  },
  {
    q: 'Is this financial advice, or a guarantee of profit?',
    a: 'Neither. It is execution infrastructure. It runs the strategy you give it, within the limits you set, and records exactly what happened. Whether that strategy makes money is entirely down to the strategy and the market.',
  },
]

export function Landing() {
  return (
    <div className="landing">
      <header className="landing-nav">
        <a className="landing-brand" href="#top">
          <span className="brand" aria-hidden="true">
            H
          </span>
          Helix
        </a>
        <nav className="landing-links" aria-label="Sections">
          <a href="#how">How it works</a>
          <a href="#features">Features</a>
          <a href="#faq">FAQ</a>
        </nav>
        <Link to="/login" className="button-link primary">
          Sign in
        </Link>
      </header>

      <main id="top">
        <section className="hero">
          <p className="eyebrow">
            <span className="eyebrow-dot" aria-hidden="true" />
            Dry-run by default
          </p>
          <h1 className="hero-title">
            Automate the trade.
            <br />
            <span className="accent-text">Keep the guardrails.</span>
          </h1>
          <p className="hero-sub">
            A console for running trading strategies against real markets — with notional caps
            enforced before submission, every order recorded in a durable ledger, and a paper venue
            that needs no credentials at all.
          </p>
          <div className="hero-cta">
            <Link to="/login" className="button-link primary">
              Sign in to the console
            </Link>
            <a href="#how" className="button-link">
              See how it works
            </a>
          </div>
          <ul className="hero-points">
            <li>No credentials needed to start</li>
            <li>Live market data</li>
            <li>LIVE is always opt-in</li>
          </ul>
        </section>

        <section id="how" className="landing-section">
          <h2>Three steps to a running bot.</h2>
          <p className="section-sub">
            The order matters: limits are set before anything can trade.
          </p>
          <ol className="step-grid">
            {STEPS.map((step, index) => (
              <li key={step.title} className="step">
                <span className="step-number" aria-hidden="true">
                  {index + 1}
                </span>
                <h3>{step.title}</h3>
                <p className="muted">{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="features" className="landing-section">
          <h2>Built for the boring parts.</h2>
          <p className="section-sub">
            The work that decides whether an automated strategy survives contact with a real venue.
          </p>
          <div className="feature-grid">
            {FEATURES.map((feature) => (
              <article key={feature.title} className="feature">
                <h3>{feature.title}</h3>
                <p className="muted">{feature.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="faq" className="landing-section">
          <h2>The honest answers.</h2>
          <div className="faq">
            {FAQ.map((item) => (
              <details key={item.q} className="faq-item">
                <summary>{item.q}</summary>
                <p className="muted">{item.a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="landing-cta">
          <h2>Start in dry-run. Arm it when you trust it.</h2>
          <p className="muted">Nothing reaches a real market until you say so, twice.</p>
          <Link to="/login" className="button-link primary">
            Sign in
          </Link>
        </section>
      </main>

      <footer className="landing-footer">
        <p className="muted">
          Helix — execution infrastructure, not investment advice. Trading carries risk, including
          loss of capital.
        </p>
      </footer>
    </div>
  )
}
