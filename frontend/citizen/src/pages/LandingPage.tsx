import { Link } from 'react-router-dom';
import { PageShell } from '../components/PageShell';
import {
  IconArrowRight,
  IconChart,
  IconCheckCircle,
  IconClock,
  IconGlobe,
  IconMapPin,
  IconMic,
  IconShield,
  IconTag,
  IconText,
  IconUsers,
} from '../components/Icons';
import './LandingPage.css';

/**
 * The report panel on the right of the hero.
 *
 * It is deliberately a static preview, not a form: the textarea-looking block
 * and the pills are presentation only (`aria-hidden`), so a resident cannot type
 * into something that does nothing. The single real control is the "Start a
 * Report" link to the report page. Nothing here is a dead control.
 */
function ReportPanel() {
  return (
    <aside className="report-panel" aria-labelledby="report-panel-title">
      <span className="report-panel__eyebrow">Start a report</span>
      <h2 className="report-panel__title" id="report-panel-title">
        What is happening in your community?
      </h2>

      <div className="report-panel__preview" aria-hidden="true">
        <div className="report-panel__field">
          <span className="report-panel__field-icon">
            <IconText size={16} />
          </span>
          <span className="report-panel__field-text">
            Describe the problem in your own words
          </span>
          <span className="report-panel__mic">
            <IconMic size={15} />
            Voice
          </span>
        </div>
        <div className="report-panel__field">
          <span className="report-panel__field-icon">
            <IconMapPin size={16} />
          </span>
          <span className="report-panel__field-text">
            Add your area or a nearby landmark
          </span>
        </div>
      </div>

      <Link to="/complaint" className="btn btn--accent btn--block">
        Start a Report
        <IconArrowRight size={17} />
      </Link>

      <p className="report-panel__note">
        Write or speak in English, Hindi or Marathi.
      </p>
    </aside>
  );
}

const ASSURANCES = [
  { Icon: IconGlobe, title: 'English, Hindi, Marathi', body: 'Report in the language you speak.' },
  { Icon: IconMic, title: 'Text or voice', body: 'Type it, or simply speak your report.' },
  { Icon: IconClock, title: 'Track your requests', body: 'Follow each report you have submitted.' },
  { Icon: IconCheckCircle, title: 'Free for every resident', body: 'No cost and no account needed to report.' },
];

/**
 * The CivicAI pipeline.
 *
 * Requirement 3 asked for a REPORT → UNDERSTAND → AGGREGATE → PRIORITIZE →
 * DECIDE workflow, and requirement 4 asked to keep the existing five-step
 * explanation. Those are the same five stages, so they are one section rather
 * than two: a stage rail carrying the full explanation. The `how-it-works` id
 * keeps the header anchor and the "See How It Works" button working.
 */
const STAGES = [
  {
    Icon: IconText,
    title: 'Report',
    body: 'A resident submits a local issue by text or voice, in English, Hindi or Marathi, together with its location.',
  },
  {
    Icon: IconChart,
    title: 'Understand',
    body: 'CivicAI reads the report and identifies its category, severity, urgency and the community affected.',
  },
  {
    Icon: IconUsers,
    title: 'Aggregate',
    body: 'Similar reports from the same area are grouped, so a single voice becomes many and recurring problems become visible.',
  },
  {
    Icon: IconTag,
    title: 'Prioritize',
    body: 'Citizen demand, infrastructure gaps, population impact, urgency and investment combine into an evidence-based priority.',
  },
  {
    Icon: IconShield,
    title: 'Decide',
    body: 'Government officers review the evidence and decide what to do.',
  },
];

export function LandingPage() {
  return (
    <PageShell>
      {/* Hero ------------------------------------------------------- */}
      <section className="hero">
        <div className="container hero__inner">
          <div className="hero__copy">
            <span className="eyebrow">CivicAI Citizen Portal</span>
            <h1 className="hero__title">
              Your Voice. Your Community.
              <br />
              Your Priorities.
            </h1>
            <p className="hero__lead">
              Report local infrastructure and community issues in your preferred
              language. CivicAI reads every report, groups the ones that share a
              cause, and turns them into clear priorities your local government
              can act on.
            </p>

            <div className="hero__actions">
              <Link to="/complaint" className="btn btn--primary btn--lg">
                Report an Issue
              </Link>
              <a href="#how-it-works" className="btn btn--secondary btn--lg">
                See How It Works
              </a>
            </div>

            <ul className="hero__points">
              <li>
                <IconCheckCircle size={17} />
                English, Hindi and Marathi
              </li>
              <li>
                <IconCheckCircle size={17} />
                Write it or speak it
              </li>
              <li>
                <IconCheckCircle size={17} />
                Track every request you make
              </li>
            </ul>
          </div>

          <ReportPanel />
        </div>
      </section>

      {/* Assurances ------------------------------------------------- */}
      <section className="assurances" aria-label="What reporting with CivicAI gives you">
        <div className="container">
          <ul className="assurances__grid">
            {ASSURANCES.map((item) => (
              <li className="assurance" key={item.title}>
                <span className="assurance__icon" aria-hidden="true">
                  <item.Icon size={19} />
                </span>
                <div>
                  <h3 className="assurance__title">{item.title}</h3>
                  <p className="assurance__body">{item.body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Pipeline --------------------------------------------------- */}
      <section id="how-it-works" className="section pipeline">
        <div className="container">
          <header className="pipeline__head">
            <div>
              <span className="eyebrow">How it works</span>
              <h2 className="pipeline__title">
                From one report to a government decision
              </h2>
            </div>
            <p className="pipeline__principle">
              <strong>AI recommends. Government decides.</strong>
              CivicAI organises evidence so officers can decide with a clear
              picture. It never makes the decision.
            </p>
          </header>

          <ol className="stage-rail">
            {STAGES.map((stage, index) => (
              <li className="stage" key={stage.title}>
                <div className="stage__top">
                  <span className="stage__number" aria-hidden="true">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="stage__icon" aria-hidden="true">
                    <stage.Icon size={19} />
                  </span>
                </div>
                <h3 className="stage__title">{stage.title}</h3>
                <p className="stage__body">{stage.body}</p>
              </li>
            ))}
          </ol>

          <div className="pipeline__cta">
            <p className="pipeline__cta-text">
              Seen a problem in your area? Reporting it takes under a minute.
            </p>
            <div className="pipeline__cta-actions">
              <Link to="/complaint" className="btn btn--primary btn--lg">
                Report an Issue
              </Link>
              <Link to="/login" className="btn btn--secondary btn--lg">
                Sign In to Track Requests
              </Link>
            </div>
          </div>
        </div>
      </section>
    </PageShell>
  );
}
