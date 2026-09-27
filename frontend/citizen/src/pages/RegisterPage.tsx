import { useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './AuthPage.css';

export function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [formData, setFormData] = useState({
    full_name: '',
    email: '',
    password: '',
    confirmPassword: '',
    role: 'citizen' as 'citizen' | 'officer',
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
        role: formData.role,
      });
      navigate('/complaint');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <header className="header">
        <div className="container">
          <div className="logo">CivicAI</div>
          <nav className="nav">
            <Link to="/" className="nav-link">Home</Link>
          </nav>
        </div>
      </header>

      <main className="main">
        <div className="container">
          <div className="auth-container">
            <div className="auth-card">
              <div className="auth-header">
                <h1>Create Account</h1>
                <p>Join CivicAI to report community issues and make your voice heard</p>
              </div>

              {error && (
                <div className="error-banner" role="alert">
                  <span>{error}</span>
                </div>
              )}

              <form onSubmit={handleSubmit} className="auth-form" noValidate>
                <div className="form-group">
                  <label htmlFor="full_name" className="label">
                    Full Name <span className="required">*</span>
                  </label>
                  <input
                    type="text"
                    id="full_name"
                    className="input"
                    placeholder="Enter your full name"
                    value={formData.full_name}
                    onChange={(e) => handleChange('full_name', e.target.value)}
                    required
                    autoComplete="name"
                    disabled={isLoading}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="email" className="label">
                    Email <span className="required">*</span>
                  </label>
                  <input
                    type="email"
                    id="email"
                    className="input"
                    placeholder="Enter your email"
                    value={formData.email}
                    onChange={(e) => handleChange('email', e.target.value)}
                    required
                    autoComplete="email"
                    disabled={isLoading}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="password" className="label">
                    Password <span className="required">*</span>
                  </label>
                  <input
                    type="password"
                    id="password"
                    className="input"
                    placeholder="Create a password (min 8 characters)"
                    value={formData.password}
                    onChange={(e) => handleChange('password', e.target.value)}
                    required
                    autoComplete="new-password"
                    disabled={isLoading}
                  />
                  <p className="helper-text">Minimum 8 characters</p>
                </div>

                <div className="form-group">
                  <label htmlFor="confirmPassword" className="label">
                    Confirm Password <span className="required">*</span>
                  </label>
                  <input
                    type="password"
                    id="confirmPassword"
                    className="input"
                    placeholder="Confirm your password"
                    value={formData.confirmPassword}
                    onChange={(e) => handleChange('confirmPassword', e.target.value)}
                    required
                    autoComplete="new-password"
                    disabled={isLoading}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="role" className="label">
                    Register As <span className="required">*</span>
                  </label>
                  <select
                    id="role"
                    className="select"
                    value={formData.role}
                    onChange={(e) => handleChange('role', e.target.value as 'citizen' | 'officer')}
                    required
                    disabled={isLoading}
                  >
                    <option value="citizen">Citizen</option>
                    <option value="officer">Officer</option>
                  </select>
                </div>

                <button
                  type="submit"
                  className="btn btn-primary btn-large btn-full"
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <>
                      <span className="spinner"></span>
                      Creating account...
                    </>
                  ) : (
                    'Create Account'
                  )}
                </button>
              </form>

              <div className="auth-footer">
                <p>Already have an account? <Link to="/login">Sign in</Link></p>
              </div>
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