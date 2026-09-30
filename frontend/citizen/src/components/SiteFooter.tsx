import { Link } from 'react-router-dom';

/**
 * The shared footer. One definition for the whole portal, so the closing band is
 * identical everywhere instead of being copy-pasted per page.
 */
export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container site-footer__inner">
        <p>&copy; 2026 CivicAI — Citizen Portal.</p>
        <nav className="site-footer__links" aria-label="Footer">
          <Link to="/">Home</Link>
          <Link to="/complaint">Report an Issue</Link>
          <Link to="/login">Sign In</Link>
        </nav>
      </div>
    </footer>
  );
}
