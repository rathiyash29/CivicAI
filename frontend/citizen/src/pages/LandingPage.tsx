import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './LandingPage.css';

export function LandingPage() {
  const navigate = useNavigate();
  const { isAuthenticated, user } = useAuth();

  const handleReportClick = () => {
    navigate('/complaint');
  };

  return (
    <div className="landing-page">
      <header className="header">
        <div className="container">
          <div className="logo">CivicAI</div>
          <nav className="nav">
            <a href="#how-it-works" className="nav-link">How It Works</a>
            {isAuthenticated ? (
              <>
                <Link to="/my-complaints" className="nav-link">My Complaints</Link>
                <Link to="/complaint" className="btn btn-primary">Report a Problem</Link>
                <span className="user-info" style={{ color: '#64748b', marginLeft: '1rem', fontSize: '0.9rem' }}>
                  {user?.full_name}
                </span>
              </>
            ) : (
              <>
                <Link to="/login" className="nav-link">Sign In</Link>
                <Link to="/register" className="btn btn-primary">Get Started</Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="main">
        <section className="hero">
          <div className="container">
            <div className="hero-content">
              <h1 className="hero-title">CivicAI</h1>
              <p className="hero-tagline">"Your Voice. Your Community. Your Future."</p>
              <p className="hero-description">
                CivicAI empowers citizens to report local development and infrastructure problems 
                in their preferred language. Our AI-powered platform analyzes community feedback 
                to help authorities understand and prioritize community needs effectively.
              </p>
              <button className="btn btn-primary btn-large" onClick={handleReportClick}>
                Report a Problem
              </button>
            </div>
            <div className="hero-visual">
              <div className="visual-card">
                <div className="visual-icon">📍</div>
                <h3>Report Issues</h3>
                <p>Submit complaints in your language</p>
              </div>
              <div className="visual-card">
                <div className="visual-icon">🤖</div>
                <h3>AI Analysis</h3>
                <p>Smart categorization & priority</p>
              </div>
              <div className="visual-card">
                <div className="visual-icon">📊</div>
                <h3>Actionable Insights</h3>
                <p>Data-driven decisions for authorities</p>
              </div>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="how-it-works">
          <div className="container">
            <h2 className="section-title">How CivicAI Works</h2>
            <div className="steps">
              <div className="step">
                <div className="step-number">1</div>
                <h3>Submit Report</h3>
                <p>Describe the issue in your preferred language — English, Hindi, or Marathi. Add location details and optionally use voice input.</p>
              </div>
              <div className="step">
                <div className="step-number">2</div>
                <h3>AI Analysis</h3>
                <p>Our AI automatically categorizes the issue, assesses severity and urgency, identifies affected groups, and recommends actions.</p>
              </div>
              <div className="step">
                <div className="step-number">3</div>
                <h3>Authorities Act</h3>
                <p>Local authorities receive structured, prioritized insights to make data-driven decisions and allocate resources effectively.</p>
              </div>
            </div>
          </div>
        </section>

        <section className="features">
          <div className="container">
            <h2 className="section-title">Key Features</h2>
            <div className="features-grid">
              <div className="feature">
                <div className="feature-icon">🌐</div>
                <h3>Multilingual Support</h3>
                <p>Report in English, Hindi, or Marathi. More languages coming soon.</p>
              </div>
              <div className="feature">
                <div className="feature-icon">🎤</div>
                <h3>Voice Input Ready</h3>
                <p>Microphone integration for hands-free reporting (coming soon).</p>
              </div>
              <div className="feature">
                <div className="feature-icon">📍</div>
                <h3>Location Aware</h3>
                <p>Precise location tagging for accurate issue mapping.</p>
              </div>
              <div className="feature">
                <div className="feature-icon">⚡</div>
                <h3>Instant AI Analysis</h3>
                <p>Real-time categorization, severity assessment, and recommendations.</p>
              </div>
              <div className="feature">
                <div className="feature-icon">🔒</div>
                <h3>Privacy First</h3>
                <p>Your data is secure and used only for community improvement.</p>
              </div>
              <div className="feature">
                <div className="feature-icon">📈</div>
                <h3>Community Insights</h3>
                <p>Aggregate analytics help authorities spot trends and patterns.</p>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="footer">
        <div className="container">
          <p>&copy; 2026 CivicAI. Built for hackathon demo.</p>
        </div>
      </footer>
    </div>
  );
}