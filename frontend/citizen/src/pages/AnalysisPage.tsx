import { useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
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
}

interface PriorityData {
  priority_score: number;
  priority_level: string;
  factors: {
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
}

const SEVERITY_COLORS: Record<string, string> = {
  High: '#dc2626',
  Medium: '#f59e0b',
  Low: '#22c55e',
  Critical: '#7c2d12',
};

const URGENCY_COLORS: Record<string, string> = {
  High: '#dc2626',
  Medium: '#f59e0b',
  Low: '#22c55e',
};

const PRIORITY_COLORS: Record<string, string> = {
  High: '#dc2626',
  Medium: '#f59e0b',
  Low: '#22c55e',
};

const HOTSPOT_COLORS: Record<string, string> = {
  High: '#dc2626',
  Medium: '#f59e0b',
  Low: '#22c55e',
};

function normalizeAnalysis(data: BackendAnalysisResponse | AnalysisData): AnalysisData {
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

export function AnalysisPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, setState] = useState<PageState | null>(null);
  const [mounted, setMounted] = useState(false);
  const [hotspots, setHotspots] = useState<HotspotData[]>([]);

  // Fetch hotspots on mount
  useEffect(() => {
    fetch('http://127.0.0.1:8000/hotspots')
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

  useEffect(() => {
    setMounted(true);
    const pageState = location.state as PageState | undefined;
    if (pageState && pageState.complaint) {
      const mergedState: PageState = {
        complaint: pageState.complaint,
        analysis: normalizeAnalysis(pageState.analysis as any),
        priority: pageState.priority,
        duplicate: pageState.duplicate,
      };
      setState(mergedState);
    } else {
      navigate('/complaint', { replace: true });
    }
  }, [location, navigate]);

  if (!mounted || !state) {
    return (
      <div className="analysis-page loading">
        <div className="loading-spinner"></div>
        <p>Loading analysis...</p>
      </div>
    );
  }

  const { complaint, analysis, priority, duplicate } = state;

  const getSeverityColor = (severity: string) => SEVERITY_COLORS[severity] || '#6b7280';
  const getUrgencyColor = (urgency: string) => URGENCY_COLORS[urgency] || '#6b7280';
  const getPriorityColor = (level: string) => PRIORITY_COLORS[level] || '#6b7280';
  const getHotspotColor = (level: string) => HOTSPOT_COLORS[level] || '#6b7280';

  // Top 3 hotspots
  const topHotspots = hotspots.slice(0, 3);

  return (
    <div className="analysis-page">
      <header className="header">
        <div className="container">
          <div className="logo">CivicAI</div>
          <nav className="nav">
            <a href="/" className="nav-link">Home</a>
          </nav>
        </div>
      </header>

      <main className="main">
        <div className="container">
          <div className="analysis-container">
            <div className="analysis-header">
              <div className="mock-banner">MOCK AI ANALYSIS</div>
              <h1>AI Analysis Results</h1>
              <p className="analysis-subtitle">Based on your complaint: <strong>"{complaint.text.slice(0, 80)}{complaint.text.length > 80 ? '...' : ''}"</strong></p>
            </div>

            {priority && (
              <div className="priority-section">
                <div className="priority-header">
                  <h2>Priority Scoring</h2>
                  <div className="priority-score-card">
                    <div className="priority-score">
                      <span className="score-value">{priority.priority_score}</span>
                      <span className="score-label">Priority Score</span>
                    </div>
                    <div className="priority-level-badge" style={{ backgroundColor: getPriorityColor(priority.priority_level), color: 'white' }}>
                      {priority.priority_level}
                    </div>
                  </div>
                </div>
                <div className="priority-factors">
                  <h3>Factor Breakdown</h3>
                  <div className="factors-grid">
                    <div className="factor-item">
                      <span className="factor-label">Citizen Demand</span>
                      <span className="factor-value">{priority.factors.citizen_demand}</span>
                      <span className="factor-weight">(30%)</span>
                    </div>
                    <div className="factor-item">
                      <span className="factor-label">Infrastructure Gap</span>
                      <span className="factor-value">{priority.factors.infrastructure_gap}</span>
                      <span className="factor-weight">(25%)</span>
                    </div>
                    <div className="factor-item">
                      <span className="factor-label">Population Impact</span>
                      <span className="factor-value">{priority.factors.population_impact}</span>
                      <span className="factor-weight">(20%)</span>
                    </div>
                    <div className="factor-item">
                      <span className="factor-label">Urgency</span>
                      <span className="factor-value">{priority.factors.urgency}</span>
                      <span className="factor-weight">(15%)</span>
                    </div>
                    <div className="factor-item">
                      <span className="factor-label">Investment Gap</span>
                      <span className="factor-value">{priority.factors.investment_gap}</span>
                      <span className="factor-weight">(10%)</span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {duplicate && (
              <div className="duplicate-section">
                <div className="duplicate-header">
                  <h2>Duplicate Check</h2>
                  <div className="duplicate-status">
                    {duplicate.is_duplicate ? (
                      <span className="status-badge duplicate-found">
                        ⚠ Potential duplicate found ({duplicate.duplicate_count})
                      </span>
                    ) : (
                      <span className="status-badge no-duplicate">
                        ✓ No similar complaint found
                      </span>
                    )}
                  </div>
                </div>
                {duplicate.is_duplicate && duplicate.similar_complaints.length > 0 && (
                  <div className="duplicate-list">
                    {duplicate.similar_complaints.map((item) => (
                      <div key={item.id} className="duplicate-item">
                        <div className="duplicate-item-header">
                          <span className="duplicate-similarity">{item.similarity}% match</span>
                          <span className="duplicate-location">📍 {item.location}</span>
                        </div>
                        <p className="duplicate-text">"{item.text}"</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {hotspots.length > 0 && (
              <div className="hotspot-section">
                <div className="hotspot-header">
                  <h2>Community Hotspots</h2>
                  <span className="hotspot-disclaimer">Based on prototype mock community data</span>
                </div>
                <div className="hotspot-grid">
                  {topHotspots.map((hotspot) => (
                    <div key={`${hotspot.location}-${hotspot.category}`} className="hotspot-card">
                      <div className="hotspot-card-header">
                        <div className="hotspot-location-category">
                          <span className="hotspot-location">📍 {hotspot.location}</span>
                          <span className="hotspot-category">{hotspot.category}</span>
                        </div>
                        <div className="hotspot-level-badge" style={{ backgroundColor: getHotspotColor(hotspot.hotspot_level), color: 'white' }}>
                          {hotspot.hotspot_level}
                        </div>
                      </div>
                      <div className="hotspot-stats">
                        <div className="hotspot-stat">
                          <span className="hotspot-stat-value">{hotspot.hotspot_score}</span>
                          <span className="hotspot-stat-label">Score</span>
                        </div>
                        <div className="hotspot-stat">
                          <span className="hotspot-stat-value">{hotspot.complaint_count}</span>
                          <span className="hotspot-stat-label">Complaints</span>
                        </div>
                        <div className="hotspot-stat">
                          <span className="hotspot-stat-value">{hotspot.high_severity_count}</span>
                          <span className="hotspot-stat-label">High Severity</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="analysis-grid">
              <div className="analysis-card primary">
                <div className="card-header">
                  <span className="card-icon">🌐</span>
                  <h2>Language</h2>
                </div>
                <p className="card-value">{analysis.language}</p>
              </div>

              <div className="analysis-card primary">
                <div className="card-header">
                  <span className="card-icon">🏷️</span>
                  <h2>Category</h2>
                </div>
                <p className="card-value">{analysis.category}</p>
              </div>

              <div className="analysis-card primary">
                <div className="card-header">
                  <span className="card-icon">📍</span>
                  <h2>Location</h2>
                </div>
                <p className="card-value">{analysis.location}</p>
              </div>

              <div className="analysis-card severity">
                <div className="card-header">
                  <span className="card-icon">⚠️</span>
                  <h2>Severity</h2>
                </div>
                <div className="badge severity-badge" style={{ backgroundColor: getSeverityColor(analysis.severity), color: 'white' }}>
                  {analysis.severity}
                </div>
              </div>

              <div className="analysis-card urgency">
                <div className="card-header">
                  <span className="card-icon">🚨</span>
                  <h2>Urgency</h2>
                </div>
                <div className="badge urgency-badge" style={{ backgroundColor: getUrgencyColor(analysis.urgency), color: 'white' }}>
                  {analysis.urgency}
                </div>
              </div>

              <div className="analysis-card primary">
                <div className="card-header">
                  <span className="card-icon">👥</span>
                  <h2>Affected Group</h2>
                </div>
                <p className="card-value">{analysis.affectedGroup}</p>
              </div>
            </div>

            <div className="analysis-detail">
              <div className="detail-card">
                <div className="detail-header">
                  <span className="detail-icon">📝</span>
                  <h2>Issue Summary</h2>
                </div>
                <p className="detail-text">{analysis.issueSummary}</p>
              </div>

              <div className="detail-card">
                <div className="detail-header">
                  <span className="detail-icon">✅</span>
                  <h2>Recommended Action</h2>
                </div>
                <p className="detail-text">{analysis.recommendedAction}</p>
              </div>
            </div>

            <div className="analysis-actions">
              <button className="btn btn-primary btn-large" onClick={() => navigate('/complaint')}>
                Report Another Issue
              </button>
              <a href="/" className="btn btn-secondary btn-large">
                Back to Home
              </a>
            </div>

            <div className="disclaimer">
              <p><strong>Disclaimer:</strong> This analysis, priority scoring, duplicate detection, and hotspot data are generated using mock AI for hackathon demonstration purposes. No real AI processing or backend integration is implemented.</p>
            </div>
          </div>
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