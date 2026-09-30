/**
 * Sidebar + header shell shared by every dashboard section.
 *
 * Section routes exist now so navigation is real and demonstrable; the
 * individual sections are intentional placeholders and say so.
 */
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

interface NavItem {
  to: string
  label: string
  icon: string
  description: string
  breadcrumb: string
}

export const NAV_ITEMS: NavItem[] = [
  {
    to: '/dashboard',
    label: 'Overview',
    icon: '◧',
    description: 'Pipeline totals across the CivicAI decision-support platform.',
    breadcrumb: 'Overview',
  },
  {
    to: '/dashboard/complaints',
    label: 'Complaints',
    icon: '✉',
    description: 'Citizen complaints submitted to the platform.',
    breadcrumb: 'Citizen Complaints',
  },
  {
    to: '/dashboard/hotspots',
    label: 'Hotspots',
    icon: '◎',
    description: 'Geographic clusters of concentrated citizen grievance.',
    breadcrumb: 'Hotspot Intelligence',
  },
  {
    to: '/dashboard/recommendations',
    label: 'Recommendations',
    icon: '✦',
    description: 'Evidence-based development recommendations.',
    breadcrumb: 'Recommendations',
  },
  {
    to: '/dashboard/projects',
    label: 'Projects',
    icon: '▤',
    description: 'Track initiatives driven by government decisions.',
    breadcrumb: 'Development Projects',
  },
  {
    to: '/dashboard/impact',
    label: 'Impact',
    icon: '▲',
    description: 'Measured outcomes of executed interventions.',
    breadcrumb: 'Impact Measurement',
  },
]

function roleLabel(role: string | undefined): string {
  return (role ?? '').trim().toLowerCase() === 'officer' ? 'Government Officer' : 'Officer'
}

export function DashboardLayout() {
  const { user, logout } = useAuth()
  const location = useLocation()

  const active = NAV_ITEMS.find((item) => item.to === location.pathname)
  const sectionTitle = active?.label ?? 'Overview'
  const initials = (user?.full_name ?? 'Officer')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            C
          </span>
          <div>
            <strong>CivicAI</strong>
            <small>Officer Dashboard</small>
          </div>
        </div>

        <nav className="nav" aria-label="Dashboard sections">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              <span className="nav-icon" aria-hidden="true">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <p className="muted small">CivicAI Government Portal</p>
        </div>
      </aside>

      <div className="main">
        <header className="header">
          <div>
            <nav className="breadcrumb" aria-label="Breadcrumb">
              <span className="breadcrumb-root">CivicAI</span>
              <span className="breadcrumb-sep" aria-hidden="true">
                /
              </span>
              <span className="breadcrumb-parent">Government Portal</span>
              <span className="breadcrumb-sep" aria-hidden="true">
                /
              </span>
              <span className="breadcrumb-current" aria-current="page">
                {active?.breadcrumb ?? 'Overview'}
              </span>
            </nav>
            <h1>{sectionTitle}</h1>
            <p className="muted small">
              {active?.description ?? 'CivicAI decision-support overview'}
            </p>
          </div>

          <div className="officer">
            <div className="avatar" aria-hidden="true">
              {initials || 'GO'}
            </div>
            <div className="officer-meta">
              <strong>Government Officer</strong>
              <span className="badge">{roleLabel(user?.role)}</span>
            </div>
            <button type="button" className="btn ghost" onClick={logout}>
              Log out
            </button>
          </div>
        </header>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
