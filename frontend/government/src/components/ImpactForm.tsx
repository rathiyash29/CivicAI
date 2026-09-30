import { useState, type ChangeEvent, type FormEvent } from 'react'
import { type ImpactRecordRequest } from '../api/projects'

interface ImpactFormProps {
  /** The project for which impact is being recorded */
  project: { id: number; title: string | null }
  /** Optional pre-filled data when editing existing impact */
  initialData?: Partial<ImpactRecordRequest> | null
  /** Whether auto-calculation is enabled */
  autoCalculate?: boolean
  /** Called when form is submitted successfully */
  onSubmit: (body: ImpactRecordRequest) => Promise<void>
  /** Called when user cancels */
  onCancel: () => void
  /** Whether submission is in progress */
  submitting?: boolean
}

/**
 * Form for recording or updating project impact measurements.
 *
 * Fields map to the backend ImpactRecordRequest. Auto-calculated fields
 * are shown but marked as calculated. Manual fields can be edited.
 */
export function ImpactForm({
  project,
  initialData,
  autoCalculate = true,
  onSubmit,
  onCancel,
  submitting = false,
}: ImpactFormProps) {
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Form state - officer-provided fields
  const [beforeComplaintCount, setBeforeComplaintCount] = useState<number | ''>(
    initialData?.before_complaint_count ?? ''
  )
  const [afterComplaintCount, setAfterComplaintCount] = useState<number | ''>(
    initialData?.after_complaint_count ?? ''
  )
  const [complaintsResolved, setComplaintsResolved] = useState<number | ''>(
    initialData?.complaints_resolved ?? ''
  )
  const [beforeAvgSeverityScore, setBeforeAvgSeverityScore] = useState<number | ''>(
    initialData?.before_avg_severity_score ?? ''
  )
  const [afterAvgSeverityScore, setAfterAvgSeverityScore] = useState<number | ''>(
    initialData?.after_avg_severity_score ?? ''
  )
  const [beforeAvgPriorityScore, setBeforeAvgPriorityScore] = useState<number | ''>(
    initialData?.before_avg_priority_score ?? ''
  )
  const [afterAvgPriorityScore, setAfterAvgPriorityScore] = useState<number | ''>(
    initialData?.after_avg_priority_score ?? ''
  )
  const [measurementPeriodStart, setMeasurementPeriodStart] = useState<string>(
    initialData?.measurement_period_start ?? ''
  )
  const [measurementPeriodEnd, setMeasurementPeriodEnd] = useState<string>(
    initialData?.measurement_period_end ?? ''
  )
  const [officerNotes, setOfficerNotes] = useState<string>(
    initialData?.officer_notes ?? ''
  )
  const [autoCalc, setAutoCalc] = useState<boolean>(autoCalculate)

  function handleNumberChange(
    event: ChangeEvent<HTMLInputElement>,
    setter: (val: number | '') => void
  ) {
    const value = event.target.value
    if (value === '' || /^\d+$/.test(value)) {
      setter(value === '' ? '' : parseInt(value, 10))
    }
  }

  function handleFloatChange(
    event: ChangeEvent<HTMLInputElement>,
    setter: (val: number | '') => void
  ) {
    const value = event.target.value
    if (value === '' || /^\d*\.?\d*$/.test(value)) {
      setter(value === '' ? '' : parseFloat(value))
    }
  }

  function validate(): string | null {
    const fields = [
      { name: 'Before complaint count', value: beforeComplaintCount },
      { name: 'After complaint count', value: afterComplaintCount },
      { name: 'Complaints resolved', value: complaintsResolved },
      { name: 'Before avg severity', value: beforeAvgSeverityScore },
      { name: 'After avg severity', value: afterAvgSeverityScore },
      { name: 'Before avg priority', value: beforeAvgPriorityScore },
      { name: 'After avg priority', value: afterAvgPriorityScore },
    ]

    for (const field of fields) {
      if (field.value !== '' && typeof field.value === 'number') {
        if (field.name.includes('count') || field.name.includes('resolved')) {
          if (field.value < 0) return `${field.name} cannot be negative.`
        }
        if (field.name.includes('severity') || field.name.includes('priority')) {
          if (field.value < 0 || field.value > 100) {
            return `${field.name} must be between 0 and 100.`
          }
        }
      }
    }

    // At least one field or notes must be provided
    const hasAnyValue =
      beforeComplaintCount !== '' ||
      afterComplaintCount !== '' ||
      complaintsResolved !== '' ||
      beforeAvgSeverityScore !== '' ||
      afterAvgSeverityScore !== '' ||
      beforeAvgPriorityScore !== '' ||
      afterAvgPriorityScore !== '' ||
      officerNotes.trim() !== ''

    if (!hasAnyValue) {
      return 'At least one measurement field or officer notes must be provided.'
    }

    return null
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSuccess(null)

    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }

    const body: ImpactRecordRequest = {
      before_complaint_count: beforeComplaintCount === '' ? undefined : beforeComplaintCount,
      after_complaint_count: afterComplaintCount === '' ? undefined : afterComplaintCount,
      complaints_resolved: complaintsResolved === '' ? undefined : complaintsResolved,
      before_avg_severity_score:
        beforeAvgSeverityScore === '' ? undefined : beforeAvgSeverityScore,
      after_avg_severity_score:
        afterAvgSeverityScore === '' ? undefined : afterAvgSeverityScore,
      before_avg_priority_score:
        beforeAvgPriorityScore === '' ? undefined : beforeAvgPriorityScore,
      after_avg_priority_score:
        afterAvgPriorityScore === '' ? undefined : afterAvgPriorityScore,
      measurement_period_start: measurementPeriodStart || undefined,
      measurement_period_end: measurementPeriodEnd || undefined,
      officer_notes: officerNotes.trim() || undefined,
      auto_calculate: autoCalc,
    }

    try {
      await onSubmit(body)
      setSuccess('Impact recorded successfully.')
      // Don't reset form - let parent close modal
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Failed to record impact')
    }
  }

  return (
    <form className="decision-form" onSubmit={handleSubmit}>
      <div className="impact-form-notice">
        <span className="notice-icon" aria-hidden="true">📋</span>
        <div>
          <strong>Record Impact Measurement</strong>
          <p className="muted small">
            Provide observed measurements for project <strong>{project.title || ` #${project.id}`}</strong>.
            Auto-calculated fields are derived from complaint data when dates are provided.
            These are <em>observed measurements only</em> — they do not imply the project caused
            the change.
          </p>
        </div>
      </div>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      {success ? (
        <p className="decision-success" role="status">
          {success}
        </p>
      ) : null}

      <div className="form-section">
        <h4 className="detail-subhead">Complaint Metrics</h4>
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="before-complaints">
              Before complaint count
              {autoCalc ? <span className="calc-badge">Auto</span> : null}
            </label>
            <input
              id="before-complaints"
              type="number"
              min="0"
              value={beforeComplaintCount}
              onChange={(e) => handleNumberChange(e, setBeforeComplaintCount)}
              placeholder="Auto-calculated"
              disabled={autoCalc}
              aria-describedby="before-complaints-help"
            />
            <p id="before-complaints-help" className="muted small">
              Total complaints in the cluster before the measurement period
            </p>
          </div>

          <div className="form-field">
            <label htmlFor="after-complaints">
              After complaint count
              {autoCalc ? <span className="calc-badge">Auto</span> : null}
            </label>
            <input
              id="after-complaints"
              type="number"
              min="0"
              value={afterComplaintCount}
              onChange={(e) => handleNumberChange(e, setAfterComplaintCount)}
              placeholder="Auto-calculated"
              disabled={autoCalc}
              aria-describedby="after-complaints-help"
            />
            <p id="after-complaints-help" className="muted small">
              Total complaints in the cluster after the measurement period
            </p>
          </div>

          <div className="form-field">
            <label htmlFor="complaints-resolved">Complaints resolved (manual)</label>
            <input
              id="complaints-resolved"
              type="number"
              min="0"
              value={complaintsResolved}
              onChange={(e) => handleNumberChange(e, setComplaintsResolved)}
              placeholder="Officer estimate"
              aria-describedby="resolved-help"
            />
            <p id="resolved-help" className="muted small">
              Number of complaints the officer considers resolved by this project
            </p>
          </div>
        </div>
      </div>

      <div className="form-section">
        <h4 className="detail-subhead">Severity Metrics (0–100 scale)</h4>
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="before-severity">
              Before avg severity
              {autoCalc ? <span className="calc-badge">Auto</span> : null}
            </label>
            <input
              id="before-severity"
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={beforeAvgSeverityScore}
              onChange={(e) => handleFloatChange(e, setBeforeAvgSeverityScore)}
              placeholder="Auto-calculated"
              disabled={autoCalc}
            />
            <p className="muted small">Average severity score before (Low=10, Medium=50, High=90)</p>
          </div>

          <div className="form-field">
            <label htmlFor="after-severity">
              After avg severity
              {autoCalc ? <span className="calc-badge">Auto</span> : null}
            </label>
            <input
              id="after-severity"
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={afterAvgSeverityScore}
              onChange={(e) => handleFloatChange(e, setAfterAvgSeverityScore)}
              placeholder="Auto-calculated"
              disabled={autoCalc}
            />
            <p className="muted small">Average severity score after (Low=10, Medium=50, High=90)</p>
          </div>
        </div>
      </div>

      <div className="form-section">
        <h4 className="detail-subhead">Priority Metrics (0–100 scale)</h4>
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="before-priority">
              Before avg priority
              {autoCalc ? <span className="calc-badge">Auto</span> : null}
            </label>
            <input
              id="before-priority"
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={beforeAvgPriorityScore}
              onChange={(e) => handleFloatChange(e, setBeforeAvgPriorityScore)}
              placeholder="Auto-calculated"
              disabled={autoCalc}
            />
            <p className="muted small">Average priority score before measurement period</p>
          </div>

          <div className="form-field">
            <label htmlFor="after-priority">
              After avg priority
              {autoCalc ? <span className="calc-badge">Auto</span> : null}
            </label>
            <input
              id="after-priority"
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={afterAvgPriorityScore}
              onChange={(e) => handleFloatChange(e, setAfterAvgPriorityScore)}
              placeholder="Auto-calculated"
              disabled={autoCalc}
            />
            <p className="muted small">Average priority score after measurement period</p>
          </div>
        </div>
      </div>

      <div className="form-section">
        <h4 className="detail-subhead">Measurement Period</h4>
        <div className="form-row">
          <div className="form-field">
            <label htmlFor="period-start">Period start</label>
            <input
              id="period-start"
              type="datetime-local"
              value={measurementPeriodStart}
              onChange={(e) => setMeasurementPeriodStart(e.target.value)}
            />
            <p className="muted small">
              Defaults to project creation date if not specified
            </p>
          </div>

          <div className="form-field">
            <label htmlFor="period-end">Period end</label>
            <input
              id="period-end"
              type="datetime-local"
              value={measurementPeriodEnd}
              onChange={(e) => setMeasurementPeriodEnd(e.target.value)}
            />
            <p className="muted small">
              Defaults to project creation date if not specified
            </p>
          </div>
        </div>
      </div>

      <div className="form-section">
        <h4 className="detail-subhead">Officer Notes</h4>
        <textarea
          id="officer-notes"
          rows={3}
          value={officerNotes}
          onChange={(e) => setOfficerNotes(e.target.value)}
          placeholder="Context, methodology, caveats, or qualitative observations"
        />
        <p className="muted small">
          Record any qualitative observations, methodology notes, or caveats about these measurements.
        </p>
      </div>

      <div className="form-section">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={autoCalc}
            onChange={(e) => setAutoCalc(e.target.checked)}
          />
          <span>
            Auto-calculate missing fields from complaint data
            <span className="muted small">
              (uses measurement period dates or project creation date as boundary)
            </span>
          </span>
        </label>
      </div>

      <div className="decision-row">
        <button
          type="submit"
          className="btn primary"
          disabled={submitting}
        >
          {submitting ? 'Saving…' : initialData ? 'Update Impact' : 'Record Impact'}
        </button>
        <button
          type="button"
          className="btn ghost"
          onClick={onCancel}
          disabled={submitting}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}