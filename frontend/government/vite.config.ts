import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The officer dashboard runs alongside the citizen app, so it takes port 5174
// (5173 stays with frontend/citizen).
//
// The FastAPI app's CORS allow-list only covers the citizen origin, so instead
// of widening that list this dev server proxies `/api/*` to the backend. The
// proxy strips the `/api` prefix, so the backend sees the exact documented
// paths (`/auth/login`, `/auth/me`, `/intelligence/stats`). The same-origin
// setup also matches how the production build will be served.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const backendTarget = env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    // The officer dashboard is served under /government/ on the citizen
    // deployment (https://civicai-liart.vercel.app/government), which the
    // citizen Vercel build rewrites to this app's own deployment. Setting the
    // Vite base here makes every asset URL in the built index.html start with
    // /government/, so static assets load correctly through that prefix. The
    // dev and preview servers serve the same base path.
    base: '/government/',
    server: {
      port: 5174,
      strictPort: false,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
    preview: {
      port: 5174,
    },
  }
})
