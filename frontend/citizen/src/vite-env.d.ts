/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL of the CivicAI backend. Leave empty in local development: the
   * Vite server is same-origin, so no CORS configuration is needed.
   *
   * In production, set this to the origin the built app is served from, e.g.
   * `https://api.civicai.example`. Never put a secret here -- only a URL.
   */
  readonly VITE_API_BASE_URL?: string
}