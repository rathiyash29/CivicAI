import { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { submitComplaint } from '../api/complaints';
import { getAuthToken } from '../api/auth';
import './ComplaintPage.css';

interface ComplaintData {
  text: string;
  language: string;
  location: string;
}

const LANGUAGES = [
  { value: 'English', label: 'English' },
  { value: 'Hindi', label: 'Hindi' },
  { value: 'Marathi', label: 'Marathi' },
];

const SPEECH_LANG_MAP: Record<string, string> = {
  English: 'en-IN',
  Hindi: 'hi-IN',
  Marathi: 'mr-IN',
};

export function ComplaintPage() {
  const navigate = useNavigate();
  const { user, isAuthenticated, logout } = useAuth();
  const [complaint, setComplaint] = useState<ComplaintData>({
    text: '',
    language: 'English',
    location: '',
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isListening, setIsListening] = useState(false);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  // Initialize speech recognition
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = SPEECH_LANG_MAP[complaint.language];

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        let finalTranscript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          }
        }
        if (finalTranscript) {
          setComplaint(prev => ({
            ...prev,
            text: prev.text ? prev.text + ' ' + finalTranscript : finalTranscript
          }));
        }
      };

      recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          setSpeechError('Microphone permission denied. Please allow microphone access in your browser settings.');
        } else if (event.error === 'no-speech') {
          setSpeechError('No speech detected. Please try again.');
        } else if (event.error === 'audio-capture') {
          setSpeechError('Microphone not found. Please check your device.');
        } else if (event.error === 'language-not-supported') {
          setSpeechError('Selected language not supported for speech recognition.');
        } else {
          setSpeechError(`Speech recognition error: ${event.error}`);
        }
        setIsListening(false);
      };

      recognition.onend = () => {
        if (isListening) {
          // Restart if still supposed to be listening
          try {
            recognition.start();
          } catch {
            setIsListening(false);
          }
        }
      };

      recognitionRef.current = recognition;
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, [complaint.language, isListening]);

  const handleChange = useCallback((field: keyof ComplaintData, value: string) => {
    setComplaint(prev => ({ ...prev, [field]: value }));
    setError(null);
  }, []);

  const toggleListening = () => {
    const recognition = recognitionRef.current;
    if (!recognition) {
      setSpeechError('Speech recognition not supported in this browser. Please use Chrome, Edge, or Safari.');
      return;
    }

    if (isListening) {
      recognition.stop();
      setIsListening(false);
      setSpeechError(null);
    } else {
      recognition.lang = SPEECH_LANG_MAP[complaint.language];
      try {
        recognition.start();
        setIsListening(true);
        setSpeechError(null);
      } catch {
        setSpeechError('Could not start speech recognition. Please try again.');
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!complaint.text.trim()) {
      setError('Please describe the problem');
      return;
    }

    if (complaint.text.trim().length < 10) {
      setError('Description must be at least 10 characters');
      return;
    }

    if (!complaint.location.trim()) {
      setError('Please enter a location');
      return;
    }

    setIsSubmitting(true);

    try {
      const token = getAuthToken();
      const result = await submitComplaint(
        {
          text: complaint.text.trim(),
          language: complaint.language,
          location: complaint.location.trim(),
        },
        token || undefined
      );

      if (token && result.complaint?.complaint_id) {
        // Authenticated: redirect to My Complaints
        navigate('/my-complaints');
      } else {
        // Not authenticated: redirect to analysis page with results
        navigate('/analysis', {
          state: {
            complaint: result.analysis,
            priority: result.priority,
            duplicate: result.duplicate,
            submittedComplaint: complaint,
          },
        });
      }
    } catch (err) {
      if (err instanceof TypeError && err.message.includes('fetch')) {
        setError('Cannot connect to backend. Make sure the server is running at http://127.0.0.1:8000');
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('An unexpected error occurred. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="complaint-page">
      <header className="header">
        <div className="container">
          <div className="logo">CivicAI</div>
          <nav className="nav">
            <Link to="/" className="nav-link">Home</Link>
            {isAuthenticated ? (
              <>
                <span className="user-info" style={{ color: '#64748b', marginRight: '1rem', fontSize: '0.9rem' }}>
                  {user?.full_name} ({user?.role})
                </span>
                <button 
                  onClick={logout} 
                  className="btn btn-secondary" 
                  style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className="nav-link">Sign In</Link>
                <Link to="/register" className="btn btn-primary" style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}>Get Started</Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="main">
        <div className="container">
          <div className="form-container">
            <div className="form-header">
              <h1>Report a Problem</h1>
              <p className="subtitle">Describe the issue in your preferred language. Our AI will analyze and categorize it for authorities.</p>
            </div>

            {error && (
              <div className="error-banner" role="alert">
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="complaint-form" noValidate>
              <div className="form-group">
                <label htmlFor="complaint-text" className="label">
                  Describe the Problem <span className="required">*</span>
                </label>
                <div className="textarea-wrapper">
                  <textarea
                    id="complaint-text"
                    className="textarea"
                    placeholder="Describe the issue in detail... (e.g., 'The main road near my house has large potholes causing accidents')"
                    value={complaint.text}
                    onChange={(e) => handleChange('text', e.target.value)}
                    rows={5}
                    required
                  />
                  <button
                    type="button"
                    className={`mic-button ${isListening ? 'listening' : ''}`}
                    onClick={toggleListening}
                    aria-label={isListening ? 'Stop voice input' : 'Start voice input'}
                    title={isListening ? 'Click to stop listening' : 'Click to start voice input'}
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
                      <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                      <line x1="12" y1="19" x2="12" y2="22"></line>
                      <line x1="8" y1="22" x2="16" y2="22"></line>
                    </svg>
                  </button>
                  {isListening && (
                    <span className="listening-indicator" aria-live="polite">🎤 Listening...</span>
                  )}
                </div>
                <p className="helper-text">Minimum 10 characters</p>
                {speechError && (
                  <p className="speech-error" role="alert">{speechError}</p>
                )}
              </div>

              <div className="form-group">
                <label htmlFor="language" className="label">
                  Language <span className="required">*</span>
                </label>
                <select
                  id="language"
                  className="select"
                  value={complaint.language}
                  onChange={(e) => handleChange('language', e.target.value)}
                  required
                >
                  {LANGUAGES.map(lang => (
                    <option key={lang.value} value={lang.value}>
                      {lang.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="location" className="label">
                  Location <span className="required">*</span>
                </label>
                <input
                  type="text"
                  id="location"
                  className="input"
                  placeholder="Enter location (e.g., Pune, Maharashtra)"
                  value={complaint.location}
                  onChange={(e) => handleChange('location', e.target.value)}
                  required
                />
                <p className="helper-text">City, area, or landmark</p>
              </div>

              <div className="form-actions">
                <button
                  type="submit"
                  className="btn btn-primary btn-large"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <span className="spinner"></span>
                      Analyzing...
                    </>
                  ) : (
                    'Analyze Complaint'
                  )}
                </button>
                <a href="/" className="btn btn-secondary btn-large">
                  Cancel
                </a>
              </div>
            </form>

            <div className="form-footer">
              <p>This is a hackathon demo. Data is sent to the backend for AI analysis, priority scoring, and duplicate detection.</p>
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