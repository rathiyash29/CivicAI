import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getMyComplaints, type Complaint } from '../api/complaints';
import { getAuthToken } from '../api/auth';
import { PageShell } from '../components/PageShell';
import { IconAlert, IconArrowRight, IconClock, IconInbox } from '../components/Icons';
import './MyComplaintsPage.css';

/**
 * Badge tone per status.
 *
 * Only statuses the service actually returns are styled; anything unrecognised
 * falls through to a neutral badge rather than being guessed at, and the status
 * string itself is always rendered verbatim from the payload.
 */
const STATUS_TONE: Record<string, string> = {
  Submitted: 'info',
  'Under Review': 'warning',
  'In Progress': 'info',
  Completed: 'success',
  Resolved: 'success',
  Rejected: 'danger',
};

const PRIORITY_TONE: Record<string, string> = {
  High: 'danger',
  Medium: 'warning',
  Low: 'success',
};

export function MyComplaintsPage() {
  const navigate = useNavigate();
  const { isAuthenticated, isLoading: authLoading, logout } = useAuth();
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchComplaints = useCallback(async () => {
    const token = getAuthToken();
    if (!token) {
      setError('Please sign in to view your requests.');
      setIsLoading(false);
      return;
    }

    try {
      setError(null);
      const data = await getMyComplaints(token);
      setComplaints(data.complaints || []);
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Could not load your requests.');
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authLoading) {
      if (isAuthenticated) {
        fetchComplaints();
      } else {
        navigate('/login');
      }
    }
  }, [isAuthenticated, authLoading, fetchComplaints, navigate]);

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-IN', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (authLoading) {
    return (
      <PageShell>
        <div className="loading-panel">
          <span className="spinner" aria-hidden="true" />
          <p>Loading your requests…</p>
        </div>
      </PageShell>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <PageShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb" aria-label="Breadcrumb">
            <span>CivicAI</span>
            <span className="breadcrumb__sep" aria-hidden="true">/</span>
            <span>Citizen Portal</span>
            <span className="breadcrumb__sep" aria-hidden="true">/</span>
            <span aria-current="page">My Requests</span>
          </nav>

          <div className="requests__head">
            <div>
              <h1 className="page-head__title">My Requests</h1>
              <p className="page-head__lead">
                Track the issues you have reported and their current status.
              </p>
            </div>
            <div className="requests__head-actions">
              <Link to="/complaint" className="btn btn--primary btn--sm">
                Report an Issue
              </Link>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={logout}
              >
                Log out
              </button>
            </div>
          </div>
        </div>
      </div>

      <section className="section section--tight">
        <div className="container requests">
          {error && (
            <div className="alert alert--error" role="alert">
              <span className="alert__icon" aria-hidden="true"><IconAlert size={18} /></span>
              <span>{error}</span>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={fetchComplaints}
              >
                Retry
              </button>
            </div>
          )}

          {isLoading ? (
            <div className="loading-panel">
              <span className="spinner" aria-hidden="true" />
              <p>Loading your requests…</p>
            </div>
          ) : complaints.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state__icon" aria-hidden="true">
                <IconInbox size={22} />
              </span>
              <h2>No requests yet</h2>
              <p>
                You have not reported an issue yet. When you do, you will be able to
                follow its status here.
              </p>
              <Link to="/complaint" className="btn btn--primary">
                Report Your First Issue
              </Link>
            </div>
          ) : (
            <ul className="request-list">
              {complaints.map((complaint) => (
                <li key={complaint.complaint_id}>
                  <article className="card request">
                    <div className="request__head">
                      <div className="request__ident">
                        <span className="request__id">{complaint.complaint_id}</span>
                        <span className={`badge badge--${STATUS_TONE[complaint.status] ?? 'neutral'}`}>
                          {complaint.status}
                        </span>
                      </div>
                      <time className="request__date" dateTime={complaint.created_at}>
                        <IconClock size={14} aria-hidden="true" />
                        {formatDate(complaint.created_at)}
                      </time>
                    </div>

                    <p className="request__text">{complaint.text}</p>

                    <dl className="request__meta">
                      {complaint.location ? (
                        <div className="request__meta-item">
                          <dt>Location</dt>
                          <dd>{complaint.location}</dd>
                        </div>
                      ) : null}
                      {complaint.category ? (
                        <div className="request__meta-item">
                          <dt>Category</dt>
                          <dd>{complaint.category}</dd>
                        </div>
                      ) : null}
                      {complaint.severity ? (
                        <div className="request__meta-item">
                          <dt>Severity</dt>
                          <dd>
                            <span className={`badge badge--${PRIORITY_TONE[complaint.severity] ?? 'neutral'}`}>
                              {complaint.severity}
                            </span>
                          </dd>
                        </div>
                      ) : null}
                      {complaint.priority_score !== undefined && complaint.priority_level ? (
                        <div className="request__meta-item">
                          <dt>Priority</dt>
                          <dd>
                            {complaint.priority_score}{' '}
                            <span className={`badge badge--${PRIORITY_TONE[complaint.priority_level] ?? 'neutral'}`}>
                              {complaint.priority_level}
                            </span>
                          </dd>
                        </div>
                      ) : null}
                    </dl>

                    <div className="request__foot">
                      <Link
                        to={`/analysis?complaint_id=${complaint.complaint_id}`}
                        className="btn btn--secondary btn--sm"
                      >
                        View Details
                        <IconArrowRight size={15} />
                      </Link>
                    </div>
                  </article>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </PageShell>
  );
}
