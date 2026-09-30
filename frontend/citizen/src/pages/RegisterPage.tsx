import { useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { normalizeErrorMessage } from '../api/client';
import { PageShell } from '../components/PageShell';
import { IconAlert } from '../components/Icons';
import './AuthPage.css';

export function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [formData, setFormData] = useState({
    full_name: '',
    email: '',
    password: '',
    confirmPassword: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleChange = useCallback((field: keyof typeof formData, value: string) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    setError(null);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!formData.full_name.trim() || !formData.email.trim() || !formData.password || !formData.confirmPassword) {
      setError('Please fill in all fields');
      return;
    }

    if (formData.password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setIsLoading(true);

    try {
      await register({
        full_name: formData.full_name.trim(),
        email: formData.email.trim(),
        password: formData.password,
      });
      navigate('/complaint');
    } catch (err) {
      setError(
        normalizeErrorMessage(err, 'Registration failed. Please try again.'),
      );
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
              <h1>Create your CivicAI account</h1>
              <p className="page-head__lead">
                An account lets you follow the status of every issue you report.
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
                <label htmlFor="full_name" className="field__label">
                  Full name <span className="field__required">*</span>
                </label>
                <input
                  type="text"
                  id="full_name"
                  className="input"
                  placeholder="Your name"
                  value={formData.full_name}
                  onChange={(e) => handleChange('full_name', e.target.value)}
                  required
                  autoComplete="name"
                  disabled={isLoading}
                />
              </div>

              <div className="field">
                <label htmlFor="email" className="field__label">
                  Email <span className="field__required">*</span>
                </label>
                <input
                  type="email"
                  id="email"
                  className="input"
                  placeholder="you@example.com"
                  value={formData.email}
                  onChange={(e) => handleChange('email', e.target.value)}
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
                  placeholder="Create a password"
                  value={formData.password}
                  onChange={(e) => handleChange('password', e.target.value)}
                  required
                  autoComplete="new-password"
                  disabled={isLoading}
                />
                <p className="field__hint">Minimum 8 characters.</p>
              </div>

              <div className="field">
                <label htmlFor="confirmPassword" className="field__label">
                  Confirm password <span className="field__required">*</span>
                </label>
                <input
                  type="password"
                  id="confirmPassword"
                  className="input"
                  placeholder="Repeat your password"
                  value={formData.confirmPassword}
                  onChange={(e) => handleChange('confirmPassword', e.target.value)}
                  required
                  autoComplete="new-password"
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
                    Creating account…
                  </>
                ) : (
                  'Create Account'
                )}
              </button>
            </form>

            <p className="auth-card__switch">
              Already have an account? <Link to="/login">Sign in</Link>
            </p>
          </div>
        </div>
      </section>
    </PageShell>
  );
}
