import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { normalizeErrorMessage } from '../api/client';
import { PageShell } from '../components/PageShell';
import { IconAlert } from '../components/Icons';
import './AuthPage.css';

export function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password.trim()) {
      setError('Please fill in all fields');
      return;
    }

    setIsLoading(true);

    try {
      await login(email.trim(), password);
      navigate('/complaint');
    } catch (err) {
      setError(normalizeErrorMessage(err, 'Sign-in failed. Please try again.'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <PageShell>
      <section className="section">
        <div className="container auth-page">
          <div className="card card--pad-lg auth-card">
            <header className="auth-card__header">
              <span className="eyebrow">Citizen Portal</span>
              <h1>Welcome back</h1>
              <p className="page-head__lead">
                Sign in to report issues and follow your requests.
              </p>
            </header>

            {error && (
              <div className="alert alert--error" role="alert">
                <span className="alert__icon" aria-hidden="true"><IconAlert size={18} /></span>
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="auth-form" noValidate>
              <div className="field">
                <label htmlFor="email" className="field__label">
                  Email <span className="field__required">*</span>
                </label>
                <input
                  type="email"
                  id="email"
                  className="input"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  disabled={isLoading}
                />
              </div>

              <div className="field">
                <label htmlFor="password" className="field__label">
                  Password <span className="field__required">*</span>
                </label>
                <input
                  type="password"
                  id="password"
                  className="input"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  disabled={isLoading}
                />
              </div>

              <button
                type="submit"
                className="btn btn--primary btn--block btn--lg"
                disabled={isLoading}
              >
                {isLoading ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    Signing in…
                  </>
                ) : (
                  'Sign In'
                )}
              </button>
            </form>

            <p className="auth-card__switch">
              Don&apos;t have an account? <Link to="/register">Create one</Link>
            </p>
          </div>
        </div>
      </section>
    </PageShell>
  );
}
