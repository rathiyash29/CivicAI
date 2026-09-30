import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The citizen portal is served from its own dev origin but calls the CivicAI
// service with same-origin, relative URLs (see `src/api/client.ts`, where an
// empty `VITE_API_BASE_URL` is the documented local-development default). That
// only works if the dev server forwards those requests, so this proxy does it.
//
// It is dev-only and path-preserving: `/auth/login` is forwarded to
// `/auth/login`. No endpoint is rewritten, prefixed or added, and the deployed
// build is unaffected -- there the app is served from the same origin as the
// service. This mirrors the setup the government dashboard already uses.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const backendTarget = env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: false,
      proxy: {
        '/auth': { target: backendTarget, changeOrigin: true },
        '/complaints': { target: backendTarget, changeOrigin: true },
        '/hotspots': { target: backendTarget, changeOrigin: true },
      },
    },
  }
})
