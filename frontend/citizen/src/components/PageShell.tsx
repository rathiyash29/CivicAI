import type { ReactNode } from 'react';
import { SiteHeader } from './SiteHeader';
import { SiteFooter } from './SiteFooter';

/**
 * Page shell: header, main landmark, footer.
 *
 * Wrapping every route in this is what keeps the portal's chrome consistent. Each
 * page supplies only its own content, and the vertical flex here is what lets the
 * footer sit at the bottom of the viewport on short pages instead of floating
 * halfway down a tall one.
 */
export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className="page">
      <SiteHeader />
      <main className="page-body">{children}</main>
      <SiteFooter />
    </div>
  );
}
