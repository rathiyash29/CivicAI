import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { API_BASE } from '../api/client';
import { getStoredComplaint, type Complaint } from '../api/complaints';
import { getAuthToken } from '../api/auth';
import { PageShell } from '../components/PageShell';
import {
  IconAlert,
  IconChart,
  IconCheckCircle,
  IconGlobe,
  IconMapPin,
  IconTag,
  IconUsers,
} from '../components/Icons';
import './AnalysisPage.css';

interface AnalysisData {
  language: string;
  category: string;
  location: string;
  severity: string;
  urgency: string;
  affectedGroup: string;
  issueSummary: string;
  recommendedAction: string;
}

interface SubmittedComplaint {
  text: string;
  language: string;
  location: string;
}

interface BackendAnalysisResponse {
  language: string;
  category: string;
  location: string;
  severity: string;
  urgency: string;
  affected_group: string;
  issue_summary: string;
  recommended_action: string;
  /**
   * Which provider actually produced this analysis: 'gemini' or 'mock'.
   *
   * This is NOT the server's configured AI_PROVIDER. The backend falls back to
   * the keyword engine when Gemini is unavailable, and the whole point of
   * reporting the real provider is that the page must not claim Gemini AI when
   * Gemini never ran.
   */
  provider_used?: string;
  /** Safe reason code, present only when a fallback occurred. */
  fallback_reason?: string | null;
}

interface PriorityData {
  priority_score: number;
  priority_level: string;
  /**
   * Per-factor contributions. Present for a fresh submission, where the whole
   * breakdown came back in one response. A complaint read back from storage
   * carries the score and level but not the individual factor values, so this is
   * optional and the breakdown is rendered only when it exists.
   */
  factors?: {
    citizen_demand: number;
    infrastructure_gap: number;
    population_impact: number;
    urgency: number;
    investment_gap: number;
  };
}

interface DuplicateData {
  is_duplicate: boolean;
  similar_complaints: Array<{
    id: number;
    text: string;
    location: string;
    similarity: number;
  }>;
  duplicate_count: number;
}

interface HotspotData {
  location: string;
  category: string;
  complaint_count: number;
  high_severity_count: number;
  hotspot_score: number;
  hotspot_level: string;
}

interface PageState {
  complaint: SubmittedComplaint;
  analysis: AnalysisData;
  priority?: PriorityData;
  duplicate?: DuplicateData;
  /**
   * Provenance carried alongside the analysis. Read from the raw backend
   * payload before normalization, because `normalizeAnalysis` deliberately
   * projects only the civic fields.
   */
  providerUsed?: string;
  fallbackReason?: string | null;
  /**
   * True when this page is showing a complaint that was read back from storage
   * rather than the result of a submission made in this session. Storage keeps
   * the analysis but not which provider produced it, so the provider badge is
   * not shown in that case rather than guessing at one.
   */
  stored?: boolean;
  /** The public id of the complaint on screen, when known. */
  complaintId?: string;
}

/**
 * How to describe the provider in the UI.
 *
 * 'gemini' is the only value that earns a "Gemini AI" label. Anything else --
 * the keyword fallback, or a payload from an older backend that predates
 * provenance reporting -- is described as fallback rather than guessed at, so
 * the page can never imply real AI that did not run.
 */
function providerLabel(providerUsed?: string): string {
  return providerUsed === 'gemini' ? 'Gemini AI' : 'Fallback AI';
}

/**
 * A short, honest explanation shown only when a fallback actually happened.
 *
 * Deliberately does not surface `fallback_reason` itself: the backend's reason
 * codes are for telemetry, and printing "quota_exhausted" to a citizen tells
 * them nothing actionable. The raw vendor error is never available here.
 */
const FALLBACK_MESSAGE =
  'Gemini was temporarily unavailable, so fallback analysis was used.';

/**
 * Badge tone per level. Presentation only: the level string itself always comes
 * from the payload and is rendered as-is, whatever the tone.
 */
const LEVEL_TONE: Record<string, string> = {
  High: 'danger',
  Critical: 'danger',
  Medium: 'warning',
  Low: 'success',
};

function toneFor(level: string): string {
  return `badge badge--${LEVEL_TONE[level] ?? 'neutral'}`;
}

/**
 * Locate the raw backend analysis payload and its provenance fields.
 *
 * The submit page navigates here with the AI reading under `analysis`. An older
 * version of that navigation put it under `complaint` instead, and provenance
 * lives on that raw payload, so both keys are checked rather than assuming one
 * shape. Keeping the fallback costs nothing and survives a stale bookmarked
 * session mid-upgrade.
 */
function readProvenance(state: PageState): {
  raw: BackendAnalysisResponse | undefined;
  providerUsed?: string;
  fallbackReason: string | null;
} {
  const candidates = [
    state.analysis as unknown as BackendAnalysisResponse,
    state.complaint as unknown as BackendAnalysisResponse,
  ];
  const raw = candidates.find(
    (candidate) => !!candidate && typeof candidate === 'object' && 'affected_group' in candidate,
  );
  return {
    raw,
    providerUsed: raw?.provider_used,
    fallbackReason: raw?.fallback_reason ?? null,
  };
}

function normalizeAnalysis(data: BackendAnalysisResponse | AnalysisData): AnalysisData {
  // No payload at all. Render a readable empty reading rather than letting
  // `'affected_group' in undefined` throw and blank the page.
  if (!data || typeof data !== 'object') {
    return {
      language: '',
      category: 'Not recorded',
      location: '',
      severity: 'Not recorded',
      urgency: 'Not recorded',
      affectedGroup: 'Not recorded',
      issueSummary: 'No summary was recorded.',
      recommendedAction: 'No recommended action was recorded.',
    };
  }

  if ('affected_group' in data) {
    return {
      language: data.language,
      category: data.category,
      location: data.location,
      severity: data.severity,
      urgency: data.urgency,
      affectedGroup: data.affected_group,
      issueSummary: data.issue_summary,
      recommendedAction: data.recommended_action,
    };
  }
  return data as AnalysisData;
}

/**
 * Project a complaint read back from storage onto the page's own shape.
 *
 * The stored columns and the submission payload use different names for the
 * same four AI fields, so they are mapped here. Values that were never written
 * stay `null` and render as unavailable rather than being invented.
 */
function fromStoredComplaint(row: Complaint): PageState {
  const priority =
    typeof row.priority_score === 'number'
      ? {
          priority_score: row.priority_score,
          priority_level: row.priority_level ?? '',
        }
      : undefined;

  return {
    complaint: {
      text: row.text ?? '',
      language: row.language ?? '',
      location: row.location ?? '',
    },
    analysis: {
      language: row.language,
      category: row.category ?? 'Not recorded',
      location: row.location,
      severity: row.severity ?? 'Not recorded',
      urgency: row.analysis_urgency ?? 'Not recorded',
      affectedGroup: row.analysis_affected_group ?? 'Not recorded',
      issueSummary: row.analysis_issue_summary ?? 'No summary was recorded.',
      recommendedAction:
        row.analysis_recommended_action ?? 'No recommended action was recorded.',
    },
    priority,
    stored: true,
    complaintId: row.complaint_id,
  };
}

/**
 * Coerce an incoming complaint into the exact shape the render path assumes.
 *
 * Router state is untyped at runtime, so a malformed or partial payload would
 * otherwise reach `complaint.text.slice(...)` as `undefined` and throw. Because
 * there is no ErrorBoundary in this app, that unmounts the tree and shows the
 * citizen a blank page. Normalising once here means every field below is a real
 * string, and a missing value degrades to a readable dash instead of a crash.
 *
 * This changes no data: it only guarantees the types the page already declares.
 */
function normalizeComplaint(value: unknown): SubmittedComplaint {
  const record = (value ?? {}) as Partial<SubmittedComplaint>;
  const asText = (input: unknown): string =>
    typeof input === 'string' ? input : '';

  return {
    text: asText(record.text),
    language: asText(record.language),
    location: asText(record.location),
  };
}

export function AnalysisPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [state, setState] = useState<PageState | null>(null);
  const [mounted, setMounted] = useState(false);
  const [hotspots, setHotspots] = useState<HotspotData[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Fetch hotspots on mount
  useEffect(() => {
    fetch(`${API_BASE}/hotspots`)
      .then(res => res.json())
      .then(data => {
        if (data.success && data.hotspots) {
          setHotspots(data.hotspots);
        }
      })
      .catch(() => {
        // Silently fail - hotspots are optional
      });
  }, []);

  /**
   * Decide what this visit is showing.
   *
   * Two ways in, and the URL is the durable one:
   *  1. Router state, right after a submission in this session.
   *  2. `?complaint_id=CA-000072`, used by "View Details" on My Requests.
   *
   * Reading the id from the URL rather than passing it through router state is
   * what makes a refresh, a bookmark or a pasted link work: router state lives
   * only in memory and is gone the moment the tab reloads.
   *
   * With neither, there is nothing to show, so the new-report form is the
   * correct destination.
   */
  useEffect(() => {
    setMounted(true);
    const pageState = location.state as PageState | undefined;

    if (pageState && pageState.complaint) {
      const { raw, providerUsed, fallbackReason } = readProvenance(pageState);
      const mergedState: PageState = {
        // Normalised: this state came from the router, so it is untyped at
        // runtime and must be coerced before anything renders it.
        complaint: normalizeComplaint(pageState.complaint),
        analysis: normalizeAnalysis(raw ?? pageState.analysis),
        priority: pageState.priority,
        duplicate: pageState.duplicate,
        // Read off the raw payload: normalizeAnalysis projects only the civic
        // fields. An older backend that omits these leaves them undefined,
        // which the label renders as a fallback rather than as Gemini.
        providerUsed,
        fallbackReason,
      };
      setState(mergedState);
      return;
    }

    const wantedId = searchParams.get('complaint_id');
    if (!wantedId) {
      navigate('/complaint', { replace: true });
      return;
    }

    // Reading a stored complaint is scoped to the citizen, so it needs a token.
    const token = getAuthToken();
    if (!token) {
      navigate('/login', { replace: true });
      return;
    }

    let cancelled = false;
    setLoadError(null);

    getStoredComplaint(token, wantedId)
      .then((row) => {
        if (cancelled) return;
        if (!row) {
          setLoadError(
            'That report could not be found in your requests. It may belong to another account.',
          );
          return;
        }
        setState(fromStoredComplaint(row));
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError('Your reports could not be loaded. Please try again shortly.');
        }
      });

    return () => {
      cancelled = true;
    };
  }, [location, navigate, searchParams]);

  if (!mounted || (!state && !loadError)) {
    return (
      <PageShell>
        <div className="loading-panel">
          <span className="spinner" aria-hidden="true" />
          <p>Preparing your report…</p>
        </div>
      </PageShell>
    );
  }

  if (loadError || !state) {
    return (
      <PageShell>
        <div className="section section--tight">
          <div className="container report">
            <div className="alert alert--error" role="alert">
              <span className="alert__icon" aria-hidden="true">
                <IconAlert size={18} />
              </span>
              <span>{loadError}</span>
            </div>
            <div className="report__actions">
              <Link to="/my-complaints" className="btn btn--primary">
                Back to My Requests
              </Link>
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => navigate('/complaint')}
              >
                Report an Issue
              </button>
            </div>
          </div>
        </div>
      </PageShell>
    );
  }

  const { complaint, analysis, priority, duplicate } = state;
  // True only when the backend explicitly said it fell back. An absent reason
  // is not a fallback, so a payload from an older backend is not mislabelled.
  const usedFallback = Boolean(state.fallbackReason) || state.providerUsed !== 'gemini';

  // Top 3 hotspots
  const topHotspots = hotspots.slice(0, 3);

  return (
    <PageShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb" aria-label="Breadcrumb">
            <span>CivicAI</span>
            <span className="breadcrumb__sep" aria-hidden="true">/</span>
            <span>Citizen Portal</span>
            <span className="breadcrumb__sep" aria-hidden="true">/</span>
            <span aria-current="page">Your Report</span>
          </nav>
        </div>
      </div>

      <section className="section section--tight">
        <div className="container report">
          <header className="report__header">
            <div>
              <span className="eyebrow">Citizen Portal</span>
              <h1>Your Report</h1>
              <p className="report__quote">
                Based on your report: &ldquo;{complaint.text.slice(0, 80)}{complaint.text.length > 80 ? '…' : ''}&rdquo;
              </p>
            </div>
            <div className="report__badges">
              {/* The complaint's own id, so it is obvious which record is open. */}
              {state.complaintId ? (
                <span className="badge badge--neutral">{state.complaintId}</span>
              ) : null}
              {/*
                Storage keeps the analysis but not which provider produced it, so
                a stored record is labelled as a recorded analysis. Claiming
                "Fallback AI" here would assert something the data does not say.
              */}
              <span
                className={`badge ${
                  state.stored
                    ? 'badge--neutral'
                    : state.providerUsed === 'gemini'
                      ? 'badge--info'
                      : 'badge--warning'
                }`}
              >
                {state.stored ? 'Recorded analysis' : providerLabel(state.providerUsed)}
              </span>
            </div>
          </header>

          {usedFallback && !state.stored ? (
            <div className="alert alert--info" role="status">
              <span className="alert__icon" aria-hidden="true"><IconAlert size={18} /></span>
              <span>{FALLBACK_MESSAGE}</span>
            </div>
          ) : null}

          {/* How CivicAI understood the report */}
          <section className="card card--pad-lg report__understanding">
            <h2 className="card__title">How CivicAI understood your report</h2>
            <p className="report__understanding-lead">
              An automated reading of what you wrote. It organises your report so it
              can be compared with other reports from your area.
            </p>

            <dl className="fact-grid">
              <div className="fact">
                <dt className="fact__label">
                  <span className="fact__icon" aria-hidden="true"><IconTag size={16} /></span>
                  Issue category
                </dt>
                <dd className="fact__value">{analysis.category}</dd>
              </div>
              <div className="fact">
                <dt className="fact__label">
                  <span className="fact__icon" aria-hidden="true"><IconMapPin size={16} /></span>
                  Location
                </dt>
                <dd className="fact__value">{analysis.location}</dd>
              </div>
              <div className="fact">
                <dt className="fact__label">
                  <span className="fact__icon" aria-hidden="true"><IconGlobe size={16} /></span>
                  Language
                </dt>
                <dd className="fact__value">{analysis.language}</dd>
              </div>
              <div className="fact">
                <dt className="fact__label">
                  <span className="fact__icon" aria-hidden="true"><IconUsers size={16} /></span>
                  Affected group
                </dt>
                <dd className="fact__value">{analysis.affectedGroup}</dd>
              </div>
              <div className="fact">
                <dt className="fact__label">Severity</dt>
                <dd className="fact__value"><span className={toneFor(analysis.severity)}>{analysis.severity}</span></dd>
              </div>
              <div className="fact">
                <dt className="fact__label">Urgency</dt>
                <dd className="fact__value"><span className={toneFor(analysis.urgency)}>{analysis.urgency}</span></dd>
              </div>
            </dl>

            <div className="narrative">
              <div className="narrative__block">
                <h3 className="narrative__title">Summary</h3>
                <p className="narrative__text">{analysis.issueSummary}</p>
              </div>
              <div className="narrative__block">
                <h3 className="narrative__title">Recommended action</h3>
                <p className="narrative__text">{analysis.recommendedAction}</p>
              </div>
            </div>
          </section>

          {/* Priority */}
          {priority && (
            <section className="card report__priority">
              <div className="report__priority-head">
                <div>
                  <h2 className="card__title">Priority</h2>
                  <p className="card__meta">
                    How your report compares with others on citizen demand,
                    infrastructure gaps, population impact, urgency and
                    investment.
                  </p>
                </div>
                <div className="report__priority-score">
                  <strong className="report__priority-value">{priority.priority_score}</strong>
                  <span className={`badge ${toneFor(priority.priority_level)}`}>
                    {priority.priority_level}
                  </span>
                </div>
              </div>
              {priority.factors ? (
                <ul className="factor-grid">
                  <li className="factor">
                    <span className="factor__label">Citizen demand</span>
                    <span className="factor__value">{priority.factors.citizen_demand}</span>
                  <span className="factor__weight">30% weight</span>
                </li>
                <li className="factor">
                  <span className="factor__label">Infrastructure gap</span>
                  <span className="factor__value">{priority.factors.infrastructure_gap}</span>
                  <span className="factor__weight">25% weight</span>
                </li>
                <li className="factor">
                  <span className="factor__label">Population impact</span>
                  <span className="factor__value">{priority.factors.population_impact}</span>
                  <span className="factor__weight">20% weight</span>
                </li>
                <li className="factor">
                  <span className="factor__label">Urgency</span>
                  <span className="factor__value">{priority.factors.urgency}</span>
                  <span className="factor__weight">15% weight</span>
                </li>
                <li className="factor">
                  <span className="factor__label">Investment gap</span>
                  <span className="factor__value">{priority.factors.investment_gap}</span>
                  <span className="factor__weight">10% weight</span>
                </li>
                </ul>
              ) : null}
            </section>
          )}

          {/* Community context */}
          {(duplicate || hotspots.length > 0) && (
            <section className="report__context">
              <h2 className="report__context-title">Community context</h2>
              <p className="report__context-lead">
                What other residents in your area have already reported.
              </p>

              <div className="context-grid">
                {duplicate && (
                  <div className="card">
                    <h3 className="card__title">Related community reports</h3>
                    {duplicate.is_duplicate ? (
                      <>
                        <p className="card__meta context-status context-status--warn">
                          <IconAlert size={16} aria-hidden="true" />
                          {duplicate.duplicate_count}{' '}
                          {duplicate.duplicate_count === 1 ? 'report resembles' : 'reports resemble'} yours.
                        </p>
                        <ul className="related-list">
                          {(duplicate.similar_complaints ?? []).map((item) => (
                            <li className="related-item" key={item.id}>
                              <div className="related-item__meta">
                                <span className="badge badge--info">{item.similarity}% match</span>
                                <span className="related-item__location">
                                  <IconMapPin size={14} aria-hidden="true" />
                                  {item.location}
                                </span>
                              </div>
                              <p className="related-item__text">&ldquo;{item.text}&rdquo;</p>
                            </li>
                          ))}
                        </ul>
                      </>
                    ) : (
                      <p className="card__meta context-status">
                        <IconCheckCircle size={16} aria-hidden="true" />
                        No closely matching report has been recorded yet.
                      </p>
                    )}
                  </div>
                )}

                {hotspots.length > 0 && (
                  <div className="card">
                    <h3 className="card__title">Active hotspots</h3>
                    <p className="card__meta">
                      Areas where repeated reports suggest concentrated needs.
                    </p>
                    <ul className="hotspot-list">
                      {topHotspots.map((hotspot) => (
                        <li
                          className="hotspot-item"
                          key={`${hotspot.location}-${hotspot.category}`}
                        >
                          <div className="hotspot-item__head">
                            <span className="hotspot-item__location">
                              <IconMapPin size={14} aria-hidden="true" />
                              {hotspot.location}
                            </span>
                            <span className={`badge ${toneFor(hotspot.hotspot_level)}`}>
                              {hotspot.hotspot_level}
                            </span>
                          </div>
                          <p className="hotspot-item__category">{hotspot.category}</p>
                          <dl className="hotspot-item__stats">
                            <div>
                              <dt>Score</dt>
                              <dd>{hotspot.hotspot_score}</dd>
                            </div>
                            <div>
                              <dt>Reports</dt>
                              <dd>{hotspot.complaint_count}</dd>
                            </div>
                            <div>
                              <dt>High severity</dt>
                              <dd>{hotspot.high_severity_count}</dd>
                            </div>
                          </dl>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </section>
          )}

          <div className="report__actions">
            <button
              type="button"
              className="btn btn--primary btn--lg"
              onClick={() => navigate('/complaint')}
            >
              Report Another Issue
            </button>
            <button
              type="button"
              className="btn btn--secondary btn--lg"
              onClick={() => navigate('/')}
            >
              Back to Home
            </button>
          </div>

          <div className="report__disclaimer">
            <IconChart size={16} aria-hidden="true" />
            <p>
              This understanding was produced by {providerLabel(state.providerUsed)}.
              CivicAI organises reports to help officers see patterns. It supports
              government decision-making; final decisions remain with authorized
              government officers.
            </p>
          </div>
        </div>
      </section>
    </PageShell>
  );
}
