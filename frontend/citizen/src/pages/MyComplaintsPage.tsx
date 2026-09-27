import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getMyComplaints, type Complaint } from '../api/complaints';
import { getAuthToken } from '../api/auth';
import './MyComplaintsPage.css';

export function MyComplaintsPage() {
  const navigate = useNavigate();
  const { user, isAuthenticated, isLoading: authLoading, logout } = useAuth();
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchComplaints = useCallback(async () => {
    const token = getAuthToken();
    if (!token) {
      setError('Authentication required');
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
        setError('Failed to load complaints');
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

  const getPriorityColor = (level?: string) => {
    switch (level) {
      case 'High': return '#dc2626';
      case 'Medium': return '#f59e0b';
      case 'Low': return '#16a34a';
      default: return '#64748b';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'Submitted': return '#2563eb';
      case 'Under Review': return '#f59e0b';
      case 'In Progress': return '#8b5cf6';
      case 'Resolved': return '#16a34a';
      case 'Rejected': return '#dc2626';
      default: return '#64748b';
    }
  };

  if (authLoading) {
    return (
      <div className="my-complaints-page">
        <div className="loading-container">
          <div className="spinner-large"></div>
          <p>Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="my-complaints-page">
      <header className="header">
        <div className="container">
          <div className="logo">CivicAI</div>
          <nav className="nav">
            <Link to="/" className="nav-link">Home</Link>
            <Link to="/complaint" className="nav-link">Report a Problem</Link>
            <span className="user-info" style={{ color: '#64748b', marginRight: '1rem', fontSize: '0.9rem' }}>
              {user?.full_name} ({user?.role})
            </span>
            <button onClick={logout} className="btn btn-secondary" style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}>
              Logout
            </button>
          </nav>
        </div>
      </header>

      <main className="main">
        <div className="container">
          <div className="page-header">
            <h1>My Complaints</h1>
            <p className="subtitle">Track the status of complaints you've submitted</p>
          </div>

          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button onClick={fetchComplaints} className="btn btn-secondary btn-small">Retry</button>
            </div>
          )}

          {isLoading ? (
            <div className="loading-container">
              <div className="spinner"></div>
              <p>Loading your complaints...</p>
            </div>
          ) : complaints.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">📋</div>
              <h2>No Complaints Yet</h2>
              <p>You haven't submitted any complaints yet.</p>
              <Link to="/complaint" className="btn btn-primary btn-large">
                Report Your First Problem
              </Link>
            </div>
          ) : (
            <div className="complaints-list">
              {complaints.map((complaint) => (
                <article key={complaint.complaint_id} className="complaint-card">
                  <div className="complaint-header">
                    <div className="complaint-id-section">
                      <span className="complaint-id">{complaint.complaint_id}</span>
                      <span 
                        className="status-badge" 
                        style={{ backgroundColor: getStatusColor(complaint.status), color: '#fff' }}
                      >
                        {complaint.status}
                      </span>
                    </div>
                    <time className="complaint-date" dateTime={complaint.created_at}>
                      {formatDate(complaint.created_at)}
                    </time>
                  </div>

                  <div className="complaint-body">
                    <p className="complaint-text">{complaint.text}</p>
                    
                    <div className="complaint-meta">
                      <div className="meta-item">
                        <span className="meta-label">Location</span>
                        <span className="meta-value">{complaint.location}</span>
                      </div>
                      {complaint.category && (
                        <div className="meta-item">
                          <span className="meta-label">Category</span>
                          <span className="meta-value">{complaint.category}</span>
                        </div>
                      )}
                      {complaint.severity && (
                        <div className="meta-item">
                          <span className="meta-label">Severity</span>
                          <span className="meta-value">{complaint.severity}</span>
                        </div>
                      )}
                      {complaint.priority_score !== undefined && complaint.priority_level && (
                        <div className="meta-item priority-item">
                          <span className="meta-label">Priority</span>
                          <span 
                            className="meta-value priority-value"
                            style={{ color: getPriorityColor(complaint.priority_level) }}
                          >
                            {complaint.priority_score} ({complaint.priority_level})
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="complaint-footer">
                    <Link 
                      to={`/analysis?complaint_id=${complaint.complaint_id}`} 
                      className="btn btn-secondary btn-small"
                    >
                      View Details
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </main>

      <footer className="footer">
        <div className="container">
          <p>&copy; 2026 CivicAI. Built for hackathon demo.</p>
        </div>
      </footer>
    </div>
  );
}