import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ProtectedRoute } from './components/ProtectedRoute'
import { DashboardLayout } from './components/DashboardLayout'
import { LoginPage } from './pages/LoginPage'
import { AccessDeniedPage } from './pages/AccessDeniedPage'
import { OverviewPage } from './pages/OverviewPage'
import { ComplaintsPage } from './pages/ComplaintsPage'
import { HotspotsPage } from './pages/HotspotsPage'
import { RecommendationsPage } from './pages/RecommendationsPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ImpactPage } from './pages/ImpactPage'
import { CaseThreadPage } from './pages/CaseThreadPage'

function App() {
  return (
    <AuthProvider>
      <BrowserRouter basename="/government">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/access-denied" element={<AccessDeniedPage />} />

          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashboardLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<OverviewPage />} />
            <Route path="complaints" element={<ComplaintsPage />} />
            <Route path="hotspots" element={<HotspotsPage />} />
            <Route
              path="recommendations"
              element={<RecommendationsPage />}
            />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="impact" element={<ImpactPage />} />
            {/* One civic issue end to end. Declared last so the literal
                "case" segment cannot be shadowed by a future sibling. */}
            <Route path="case/:cluster_id" element={<CaseThreadPage />} />
          </Route>

          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
