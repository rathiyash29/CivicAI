import { EmptyState } from '../components/States'

/**
 * Placeholder for the sections that are not built yet (Complaints, Hotspots,
 * Recommendations, Projects, Impact). Routing and navigation are real; the
 * content is intentionally not implemented at this stage.
 */
export function PlaceholderPage({ section }: { section: string }) {
  return (
    <EmptyState
      title={`${section} — not built yet`}
      hint="This section is planned for a later milestone. Navigation and officer access control are already in place."
    />
  )
}
