import { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { submitComplaint } from '../api/complaints';
import { getAuthToken } from '../api/auth';
import { API_BASE } from '../api/client';
import { PageShell } from '../components/PageShell';
import { IconAlert, IconCheckCircle, IconGlobe, IconMic, IconStop } from '../components/Icons';
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
  const { isAuthenticated, logout } = useAuth();
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
        // Not authenticated: redirect to the analysis page with the results.
        //
        // The Analysis page needs the complaint ITSELF, not the AI reading of
        // it. `result.analysis` deliberately carries no `text` -- it is the
        // categorisation, not the submission -- so passing that left the page
        // reading `undefined` and crashing. `result.complaint` is the stored
        // record and does carry `text`. Where the backend omitted a field, fall
        // back to exactly what the citizen typed, which is what was submitted.
        const stored = result?.complaint ?? {};
        navigate('/analysis', {
          state: {
            complaint: {
              text: stored.text ?? complaint.text.trim(),
              language: stored.language ?? complaint.language,
              location: stored.location ?? complaint.location.trim(),
            },
            analysis: result.analysis,
            priority: result.priority,
            duplicate: result.duplicate,
          },
        });
      }
    } catch (err) {
      if (err instanceof TypeError && err.message.includes('fetch')) {
        setError(`Cannot connect to the CivicAI service at ${API_BASE || 'this address'}. Please try again shortly.`);
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
    <PageShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb" aria-label="Breadcrumb">
            <span>CivicAI</span>
            <span className="breadcrumb__sep" aria-hidden="true">/</span>
            <span>Citizen Portal</span>
            <span className="breadcrumb__sep" aria-hidden="true">/</span>
            <span aria-current="page">Report an Issue</span>
          </nav>
        </div>
      </div>

      <section className="section section--tight">
        <div className="container form-page">
          <div className="card card--pad-lg form-card">
            <header className="form-card__header">
              <span className="eyebrow">Citizen Portal</span>
              <h1>Report a Community Issue</h1>
              <p className="page-head__lead">
                Tell us what is happening in your area. You can write or speak in
                your preferred language.
              </p>
            </header>

            {!isAuthenticated ? (
              <div className="alert alert--info form-card__signin">
                <span className="alert__icon" aria-hidden="true"><IconAlert size={18} /></span>
                <p>
                  You are reporting as a guest.{' '}
                  <Link to="/login">Sign in</Link> or{' '}
                  <Link to="/register">create an account</Link> to keep track of
                  this request.
                </p>
              </div>
            ) : (
              <div className="form-card__signin">
                <button type="button" className="btn btn--secondary btn--sm" onClick={logout}>
                  Log out
                </button>
              </div>
            )}

            {error && (
              <div className="alert alert--error" role="alert">
                <span className="alert__icon" aria-hidden="true"><IconAlert size={18} /></span>
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="complaint-form" noValidate>
              <div className="field">
                <label htmlFor="complaint-text" className="field__label">
                  Describe the problem <span className="field__required">*</span>
                </label>
                <textarea
                  id="complaint-text"
                  className="textarea"
                  placeholder="Describe the issue in detail. For example: the main road near my house has large potholes that are causing accidents."
                  value={complaint.text}
                  onChange={(e) => handleChange('text', e.target.value)}
                  rows={6}
                  required
                  aria-describedby="complaint-text-hint"
                />
                <div className="voice-row">
                  <button
                    type="button"
                    className={`mic-button ${isListening ? 'is-listening' : ''}`}
                    onClick={toggleListening}
                    aria-pressed={isListening}
                    aria-label={isListening ? 'Stop voice input' : 'Start voice input'}
                  >
                    {isListening ? <IconStop size={18} /> : <IconMic size={18} />}
                    <span>{isListening ? 'Stop recording' : 'Speak instead of typing'}</span>
                  </button>
                  <span
                    className={`voice-state ${isListening ? 'is-listening' : ''}`}
                    role="status"
                    aria-live="polite"
                  >
                    {isListening ? 'Listening…' : 'Microphone ready'}
                  </span>
                </div>
                <p className="field__hint" id="complaint-text-hint">
                  Minimum 10 characters.
                </p>
                {speechError && (
                  <div className="alert alert--error" role="alert">
                    <span className="alert__icon" aria-hidden="true"><IconAlert size={18} /></span>
                    <span>{speechError}</span>
                  </div>
                )}
              </div>

              <div className="form-split">
                <div className="field">
                  <label htmlFor="language" className="field__label">
                    <IconGlobe size={16} className="field__label-icon" />
                    Language <span className="field__required">*</span>
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
                  <p className="field__hint">
                    Voice input uses the language selected here.
                  </p>
                </div>

                <div className="field">
                  <label htmlFor="location" className="field__label">
                    Location <span className="field__required">*</span>
                  </label>
                  <input
                    type="text"
                    id="location"
                    className="input"
                    placeholder="Pune, Maharashtra"
                    value={complaint.location}
                    onChange={(e) => handleChange('location', e.target.value)}
                    required
                    aria-describedby="location-hint"
                  />
                  <p className="field__hint" id="location-hint">
                    City, area or a nearby landmark.
                  </p>
                </div>
              </div>

              <div className="form-actions">
                <button
                  type="submit"
                  className="btn btn--primary btn--lg"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <span className="spinner" aria-hidden="true" />
                      Understanding your report…
                    </>
                  ) : (
                    <>
                      <IconCheckCircle size={18} />
                      Analyze Complaint
                    </>
                  )}
                </button>
                <Link to="/" className="btn btn--secondary btn--lg">
                  Cancel
                </Link>
              </div>
            </form>

            <p className="form-note">
              Your report is reviewed together with other reports from your area
              so that recurring problems become visible to government.
            </p>
          </div>
        </div>
      </section>
    </PageShell>
  );
}
