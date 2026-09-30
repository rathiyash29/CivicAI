/**
 * The five weighted priority factors, rendered from the engine's own numbers.
 *
 * Shared by the complaint detail modal and the case thread, because both answer
 * the same question for a different audience: "why is this priority what it is?"
 * Two copies would be two places for the labels to drift from `db_priority`.
 *
 * The bar length is the factor's own 0-100 value, NOT its contribution to the
 * final score. Computing the contribution here would mean re-implementing the
 * weighted sum in the UI, which is exactly the duplication that lets a
 * dashboard disagree with its engine. The weight is printed beside each bar so
 * the arithmetic stays the officer's to do, and the numbers stay the engine's.
 */
import type { PriorityExplanation, PriorityFactorName } from '../api/complaints'

const DASH = '—'

/** The five factors, in the order the engine weights them, with plain labels. */
export const FACTOR_ROWS: Array<{ key: PriorityFactorName; label: string }> = [
  { key: 'citizen_demand', label: 'Citizen demand' },
  { key: 'infrastructure_gap', label: 'Infrastructure gap' },
  { key: 'population_impact', label: 'Population impact' },
  { key: 'urgency', label: 'Urgency' },
  { key: 'investment_gap', label: 'Investment gap' },
]

/**
 * Does the stored score still match these factors?
 *
 * They can diverge: the score is written when a complaint is scored, and the
 * factors are re-read live, so a change to the ward data moves the second
 * without the first. That is worth saying out loud rather than quietly showing
 * the fresher number as if it were the stored one.
 */
export function scoreHasDrifted(explanation: PriorityExplanation): boolean {
  const stored = explanation.stored_score
  return (
    typeof stored === 'number' &&
    stored !== explanation.current_score
  )
}

export function FactorTable({ explanation }: { explanation: PriorityExplanation }) {
  const { factors, weights, evidence } = explanation
  return (
    <div className="factor-table">
      {FACTOR_ROWS.map(({ key, label }) => {
        const score = factors[key]
        const weight = weights[key]
        return (
          <div key={key} className="factor-row">
            <div className="factor-label">
              <span>{label}</span>
              <span className="muted small">
                {typeof score === 'number' ? score.toFixed(0) : DASH}
                {typeof weight === 'number'
                  ? ` · ${Math.round(weight * 100)}% weight`
                  : ''}
              </span>
            </div>
            <div
              className="meter"
              role="img"
              aria-label={`${label}: ${typeof score === 'number' ? score : 'unavailable'} of 100`}
            >
              <div
                className="meter-fill"
                style={{
                  width: `${
                    typeof score === 'number' ? Math.max(0, Math.min(100, score)) : 0
                  }%`,
                }}
              />
            </div>
            <span className="muted small">{sourceFor(key, evidence)}</span>
          </div>
        )
      })}
      <p className="muted small">
        Citizen demand is scored from {evidence.complaints_in_demand_group}{' '}
        complaint{evidence.complaints_in_demand_group === 1 ? '' : 's'} in this
        demand group ({evidence.citizen_demand_basis}). Factors marked{' '}
        <em>default</em> had no resolved ward to read from, so the engine used a
        neutral constant rather than a measurement.
      </p>
    </div>
  )
}

/** Human-readable provenance line for one factor. */
function sourceFor(
  key: PriorityFactorName,
  evidence: PriorityExplanation['evidence'],
): string {
  if (key === 'citizen_demand') {
    return 'From complaint volume'
  }
  const source = evidence[`${key}_source` as 'infrastructure_gap_source']
  return source === 'database' ? 'From ward data' : 'Default — ward unresolved'
}
