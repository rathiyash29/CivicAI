/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional override for the backend base URL. See .env.example. */
  readonly VITE_API_BASE_URL?: string
  /**
   * Optional path prefix placed before every backend route, e.g. `/api` when
   * the service is mounted behind a gateway. Defaults to `/api` in development
   * (the Vite proxy strips it) and to nothing in production, where the backend's
   * real paths are used.
   */
  readonly VITE_API_PATH_PREFIX?: string
  /**
   * Browser-restricted Google Maps JS API key used by the hotspots map.
   * Never a secret: restrict it by HTTP referrer in the Google Cloud console
   * and never commit a filled-in .env.
   */
  readonly VITE_GOOGLE_MAPS_API_KEY?: string
}
