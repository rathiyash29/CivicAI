/**
 * Interactive Google Maps view of CivicAI hotspots.
 *
 * Design decisions worth knowing before changing anything here:
 *
 *  * The Google Maps JavaScript API is loaded by injecting its official
 *    bootstrap script, not by an npm wrapper. That keeps the dependency count
 *    at zero, works with the existing React 19 + Vite setup, and means the map
 *    degrades to an explicit "not configured" state rather than a broken frame
 *    when no key is present. The script is loaded once per page load and its
 *    promise is cached, so React 19's StrictMode double-mount cannot inject it
 *    twice.
 *
 *  * The key is read from `VITE_GOOGLE_MAPS_API_KEY`. It is a browser-visible
 *    key by nature and must be restricted by HTTP referrer in the Google Cloud
 *    console. It is never hardcoded, never logged and never sent to the backend.
 *
 *  * A marker is drawn ONLY for a hotspot with finite coordinates
 *    (`hasCoordinates` in api/hotspots.ts). Hotspots without a point are
 *    counted and reported below the map instead of being nudged to a default
 *    position, because a plausible-looking pin in the wrong place is worse than
 *    an honest "unresolved".
 *
 *  * Markers are placed at the ward centroid, so several hotspots in the same
 *    ward overlap. Category is encoded as a label suffix and severity drives
 *    the pin colour and size, so a cluster of pins still reads at a glance.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Hotspot } from '../api/hotspots'
import { hasCoordinates } from '../api/hotspots'

const API_KEY: string = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? ''

/** Pune city centre, used for the initial camera position. */
const PUNE_CENTER = { lat: 18.5204, lng: 73.8567 }

const MAP_STYLES: google.maps.MapTypeStyle[] = [
  { elementType: 'geometry', stylers: [{ color: '#eef3f8' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#5c7186' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#ffffff' }] },
  { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#ffffff' }] },
  { featureType: 'road.arterial', elementType: 'geometry', stylers: [{ color: '#dbe6f0' }] },
  { featureType: 'transit', stylers: [{ visibility: 'off' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#cfe0ee' }] },
]

const LEVEL_COLOURS: Record<string, { fill: string; stroke: string; label: string }> = {
  High: { fill: '#c0392b', stroke: '#7d1c13', label: 'High priority' },
  Medium: { fill: '#e0a33a', stroke: '#8a5f0b', label: 'Medium priority' },
  Low: { fill: '#3f8fbf', stroke: '#1f4f6b', label: 'Low priority' },
}

function levelColour(level: string) {
  return LEVEL_COLOURS[level] ?? LEVEL_COLOURS.Low
}

/** Bigger pin for a hotter hotspot, so severity survives a zoomed-out view. */
function levelScale(level: string): number {
  if (level === 'High') return 15
  if (level === 'Medium') return 12
  return 10
}

type LoaderState = 'idle' | 'loading' | 'ready' | 'error' | 'unconfigured'

let googleMapsPromise: Promise<typeof google> | null = null

/**
 * Load the Maps JS API exactly once and hand back the `google` namespace.
 * A missing key rejects immediately rather than injecting a script that Google
 * would only refuse to serve.
 */
function loadGoogleMaps(apiKey: string): Promise<typeof google> {
  if (!apiKey) {
    return Promise.reject(new Error('VITE_GOOGLE_MAPS_API_KEY is not set'))
  }
  if (googleMapsPromise) return googleMapsPromise

  googleMapsPromise = new Promise<typeof google>((resolve, reject) => {
    const callbackName = '__civicaiMapsReady'
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-civicai-google-maps]',
    )

    const finish = () => {
      delete (window as unknown as Record<string, unknown>)[callbackName]
      if (window.google?.maps) {
        resolve(window.google)
      } else {
        googleMapsPromise = null
        reject(new Error('Google Maps loaded but the API was unavailable'))
      }
    }

    ;(window as unknown as Record<string, () => void>)[callbackName] = finish

    if (existing) {
      existing.addEventListener('load', finish, { once: true })
      existing.addEventListener('error', () => {
        googleMapsPromise = null
        reject(new Error('Google Maps script failed to load'))
      }, { once: true })
      return
    }

    const script = document.createElement('script')
    script.dataset.civicaiGoogleMaps = 'true'
    script.async = true
    script.defer = true
    script.src =
      'https://maps.googleapis.com/maps/api/js' +
      `?key=${encodeURIComponent(apiKey)}` +
      '&v=weekly&loading=async&callback=' +
      `${callbackName}&libraries=geometry`
    script.addEventListener('error', () => {
      googleMapsPromise = null
      reject(new Error('Google Maps script failed to load'))
    })
    document.head.appendChild(script)
  })

  return googleMapsPromise
}

function otherSeverityCount(hotspot: Hotspot): number {
  return Math.max(
    0,
    hotspot.complaint_count - hotspot.high_severity_count - hotspot.medium_severity_count,
  )
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

interface HotspotsMapProps {
  hotspots: Hotspot[]
  /** Ward + category of the hotspot the page wants focused, if any. */
  focusedKey: string | null
  onSelect: (key: string | null) => void
}

export function hotspotKey(hotspot: Hotspot): string {
  return `${hotspot.location}|${hotspot.category}`
}

export function HotspotsMap({ hotspots, focusedKey, onSelect }: HotspotsMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<google.maps.Map | null>(null)
  const infoRef = useRef<google.maps.InfoWindow | null>(null)
  const markersRef = useRef<Map<string, google.maps.Marker>>(new Map())
  // Key -> the exact literal the marker was placed at. Needed because a Marker
  // cannot hand back a plain `{lat, lng}`.
  const positionsRef = useRef<Map<string, google.maps.LatLngLiteral>>(new Map())
  const mapReadyRef = useRef(false)

  const [state, setState] = useState<LoaderState>('idle')

  const plottable = useMemo(
    () => hotspots.filter((hotspot) => hasCoordinates(hotspot)),
    [hotspots],
  )

  const unresolved = useMemo(
    () => hotspots.filter((hotspot) => !hasCoordinates(hotspot)),
    [hotspots],
  )

  // ---- load the API, then build the map once -------------------------------
  useEffect(() => {
    if (!API_KEY) {
      setState('unconfigured')
      return
    }
    let cancelled = false
    setState('loading')

    loadGoogleMaps(API_KEY)
      .then(() => {
        if (cancelled || !containerRef.current || mapRef.current) return
        const center = { lat: PUNE_CENTER.lat, lng: PUNE_CENTER.lng }
        mapRef.current = new window.google.maps.Map(containerRef.current, {
          center,
          zoom: 12,
          minZoom: 10,
          maxZoom: 18,
          clickableIcons: false,
          streetViewControl: false,
          fullscreenControl: false,
          mapTypeControl: false,
          gestureHandling: 'greedy',
          styles: MAP_STYLES,
          backgroundColor: '#e8eff6',
        })
        infoRef.current = new window.google.maps.InfoWindow()
        mapReadyRef.current = true
        setState('ready')
      })
      .catch(() => {
        if (!cancelled) setState('error')
      })

    return () => {
      cancelled = true
    }
  }, [])

  // ---- teardown ------------------------------------------------------------
  useEffect(
    () => () => {
      markersRef.current.forEach((marker) => marker.setMap(null))
      markersRef.current.clear()
      positionsRef.current.clear()
      mapRef.current = null
      mapReadyRef.current = false
    },
    [],
  )

  // ---- keep markers in sync with the filtered hotspot list -----------------
  useEffect(() => {
    if (state !== 'ready' || !mapRef.current) return

    const markers = markersRef.current
    const wanted = new Set(plottable.map(hotspotKey))

    // Drop markers for hotspots filtered out of view.
    for (const [key, marker] of markers) {
      if (!wanted.has(key)) {
        marker.setMap(null)
        markers.delete(key)
        positionsRef.current.delete(key)
      }
    }

    for (const hotspot of plottable) {
      const key = hotspotKey(hotspot)
      if (markers.has(key)) continue

      const colour = levelColour(hotspot.hotspot_level)
      const position: google.maps.LatLngLiteral = {
        lat: hotspot.latitude,
        lng: hotspot.longitude,
      }
      const marker = new window.google.maps.Marker({
        map: mapRef.current,
        position,
        title: `${hotspot.location} — ${hotspot.category}`,
        icon: {
          path: window.google.maps.SymbolPath.CIRCLE,
          scale: levelScale(hotspot.hotspot_level),
          fillColor: colour.fill,
          fillOpacity: 0.88,
          strokeColor: colour.stroke,
          strokeWeight: 2,
        },
        label: {
          text: String(hotspot.complaint_count),
          color: '#ffffff',
          fontSize: '11px',
          fontWeight: '700',
        },
      })

      const info = window.google.maps.InfoWindow
        ? new window.google.maps.InfoWindow({
            content: buildInfoHtml(hotspot),
          })
        : null
      if (info) infoRef.current = info

      marker.addListener('click', () => {
        if (info) {
          info.open({ map: mapRef.current, anchor: marker })
        }
        onSelect(key)
      })

      markers.set(key, marker)
      positionsRef.current.set(key, position)
    }
  }, [plottable, state, onSelect])

  // ---- fit the camera to what is actually plotted -------------------------
  useEffect(() => {
    if (state !== 'ready' || !mapRef.current || plottable.length === 0) return
    const bounds = new window.google.maps.LatLngBounds()
    plottable.forEach((hotspot) => {
      bounds.extend({ lat: hotspot.latitude, lng: hotspot.longitude })
    })
    mapRef.current.fitBounds(bounds, 48)
  }, [plottable, state])

  // ---- focus a marker when its card is selected ----------------------------
  useEffect(() => {
    if (state !== 'ready' || !mapRef.current || !focusedKey) return
    const marker = markersRef.current.get(focusedKey)
    if (!marker) return
    // Pan to the recorded literal rather than reading it back off the marker:
    // `Marker.getPosition()` returns a `LatLng` whose lat/lng are methods, not
    // the plain numbers the camera options expect.
    const position = positionsRef.current.get(focusedKey)
    if (!position) return
    mapRef.current.panTo(position)
    if (mapRef.current.getZoom() !== undefined && mapRef.current.getZoom()! < 14) {
      mapRef.current.setZoom(14)
    }
    window.google.maps.event.trigger(marker, 'click')
  }, [focusedKey, state])

  return (
    <section className="card map-card">
      <div className="map-head">
        <div>
          <h3 className="card-title">Geographic distribution</h3>
          <p className="muted small">
            One pin per ward-and-category hotspot, placed at the ward centroid.
            {plottable.length > 0
              ? ` ${plottable.length} of ${hotspots.length} shown.`
              : ' Nothing to plot yet.'}
          </p>
        </div>
      </div>

      {state === 'unconfigured' ? (
        <div className="state" role="status">
          <span className="state-glyph" aria-hidden="true">
            &#128506;
          </span>
          <h3>Map view not available</h3>
          <p>
            The geographic map could not be enabled for this deployment. Every
            hotspot below is still listed with its ward, score and severity
            breakdown, so no information is hidden.
          </p>
        </div>
      ) : null}

      {state === 'error' ? (
        <div className="state error" role="alert">
          <span className="state-glyph danger" aria-hidden="true">
            !
          </span>
          <h3>Map unavailable</h3>
          <p>
            The geographic map could not be loaded. The hotspot list below
            remains unaffected and shows every affected area in full.
          </p>
        </div>
      ) : null}

      {state === 'loading' ? <LoadingState label="Loading map…" /> : null}

      <div
        ref={containerRef}
        className="map-canvas"
        hidden={state !== 'ready'}
        aria-label="Map of CivicAI hotspots across Pune"
        role="application"
      />

      {state === 'ready' && plottable.length === 0 ? (
        <div className="map-empty" role="status">
          No hotspot in view has recorded coordinates, so no pins are drawn.
          Nothing is being approximated onto the map.
        </div>
      ) : null}

      {state === 'ready' ? <MapLegend /> : null}

      {unresolved.length > 0 ? (
        <div className="unresolved-note">
          <strong>Location unresolved</strong>
          <span>
            {unresolved.length} hotspot{unresolved.length === 1 ? '' : 's'} could
            not be placed because no coordinates are recorded for{' '}
            {[
              ...new Set(
                unresolved.map((hotspot) =>
                  hotspot.location === 'Unassigned'
                    ? 'unresolved complaint locations'
                    : hotspot.location,
                ),
              ),
            ].join(', ')}
            . They are excluded from the map rather than plotted approximately.
          </span>
        </div>
      ) : null}
    </section>
  )
}

function MapLegend() {
  return (
    <div className="map-legend" aria-label="Map legend">
      <span className="legend-title">Hotspot priority</span>
      {(['High', 'Medium', 'Low'] as const).map((level) => {
        const colour = levelColour(level)
        return (
          <span className="legend-item" key={level}>
            <span
              className="legend-swatch"
              style={{ background: colour.fill, borderColor: colour.stroke }}
              aria-hidden="true"
            />
            {colour.label}
          </span>
        )
      })}
      <span className="legend-divider" aria-hidden="true" />
      <span className="legend-item">
        <span className="legend-pin" aria-hidden="true">
          7
        </span>
        Number inside a pin = complaints in that ward-and-category group
      </span>
    </div>
  )
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="state" role="status">
      <span className="spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  )
}

function buildInfoHtml(hotspot: Hotspot): string {
  const colour = levelColour(hotspot.hotspot_level)
  const clusters = hotspot.cluster_ids.length
    ? hotspot.cluster_ids.join(', ')
    : 'None recorded'
  const place = hotspot.area ?? hotspot.location

  return [
    '<div class="map-info">',
    `<div class="map-info-head"><strong>${escapeHtml(place)}</strong>`,
    `<span class="map-info-level" style="background:${colour.fill}">${escapeHtml(hotspot.hotspot_level)}</span></div>`,
    `<p class="map-info-sub">${escapeHtml(hotspot.location)} &middot; ${escapeHtml(hotspot.category)}</p>`,
    '<dl class="map-info-grid">',
    `<div><dt>Complaints</dt><dd>${hotspot.complaint_count}</dd></div>`,
    `<div><dt>High severity</dt><dd>${hotspot.high_severity_count}</dd></div>`,
    `<div><dt>Medium severity</dt><dd>${hotspot.medium_severity_count}</dd></div>`,
    `<div><dt>Other severity</dt><dd>${otherSeverityCount(hotspot)}</dd></div>`,
    `<div><dt>Hotspot score</dt><dd>${hotspot.hotspot_score.toFixed(1)}</dd></div>`,
    `<div><dt>Cluster IDs</dt><dd>${escapeHtml(clusters)}</dd></div>`,
    '</dl>',
    '<p class="map-info-foot">Ward centroid, not an individual incident point.</p>',
    '</div>',
  ].join('')
}
