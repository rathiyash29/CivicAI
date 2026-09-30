/**
 * The shared header for every citizen-portal page.
 *
 * Previously each page rendered its own copy of this markup, so the navigation
 * and the sign-in state differed from screen to screen. It is a component now,
 * which is what makes the portal feel like one product.
 *
 * Presentation only: it reads the existing auth context and calls the existing
 * `logout`. No auth behaviour is implemented here.
 */
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { IconClose, IconMenu } from './Icons';

export function SiteHeader() {
  const { isAuthenticated, user, logout } = useAuth();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);

  // Any navigation closes the mobile menu.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const isCurrent = (path: string) =>
    path === '/' ? pathname === '/' : pathname.startsWith(path);

  return (
    <header className="site-header">
      <div className="container site-header__inner">
        <Link to="/" className="brand">
          <span className="brand__mark" aria-hidden="true">
            C
          </span>
          <span>
            CivicAI
            <span className="brand__sub">Citizen Portal</span>
          </span>
        </Link>

        <button
          type="button"
          className="nav-toggle"
          aria-expanded={open}
          aria-controls="citizen-nav"
          aria-label={open ? 'Close menu' : 'Open menu'}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <IconClose /> : <IconMenu />}
        </button>

        <nav
          id="citizen-nav"
          className="site-nav"
          aria-label="Main"
          data-open={open ? 'true' : 'false'}
        >
          <div className="site-nav__links">
            <Link
              to="/#how-it-works"
              className="site-nav__link"
              aria-current={pathname === '/' ? 'page' : undefined}
            >
              How It Works
            </Link>
            <Link to="/complaint" className="site-nav__link">
              Report an Issue
            </Link>
            {isAuthenticated ? (
              <Link
                to="/my-complaints"
                className="site-nav__link"
                aria-current={isCurrent('/my-complaints') ? 'page' : undefined}
              >
                My Requests
              </Link>
            ) : null}
          </div>

          <div className="site-nav__actions">
            {isAuthenticated ? (
              <>
                <span className="site-nav__user">
                  {user?.full_name ?? 'Citizen'}
                </span>
                <button
                  type="button"
                  className="btn btn--primary-ghost btn--sm"
                  onClick={logout}
                >
                  Log out
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className="btn btn--primary-ghost btn--sm">
                  Sign In
                </Link>
                <Link to="/complaint" className="btn btn--primary btn--sm">
                  Get Started
                </Link>
              </>
            )}
          </div>
        </nav>
      </div>
    </header>
  );
}
