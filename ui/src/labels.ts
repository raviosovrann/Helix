/**
 * Display names for wire values.
 *
 * The API speaks lowercase identifiers (`coinbase`, `futures`) because they are
 * keys, not prose — they are compared, routed on and stored. Rendering them raw
 * put "coinbase" and "spot" in front of the operator, which reads as unfinished
 * next to the proper nouns they actually are.
 *
 * Only the label changes. Every value sent to the API stays lowercase.
 */

const VENUE_LABELS: Record<string, string> = {
  coinbase: 'Coinbase',
  tradovate: 'Tradovate',
  paper: 'Paper',
}

const MARKET_LABELS: Record<string, string> = {
  spot: 'Spot',
  futures: 'Futures',
}

/** Capitalise an unknown identifier rather than showing it raw. */
function capitalise(value: string): string {
  return value.length === 0 ? value : value[0].toUpperCase() + value.slice(1)
}

/** Display name for a venue id, e.g. `coinbase` → `Coinbase`. */
export function venueLabel(venue: string): string {
  return VENUE_LABELS[venue] ?? capitalise(venue)
}

/** Display name for a market type, e.g. `futures` → `Futures`. */
export function marketLabel(marketType: string): string {
  return MARKET_LABELS[marketType] ?? capitalise(marketType)
}
