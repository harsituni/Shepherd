import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, Map as MapLibreMap, Marker, setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { MAP_CENTER, MAP_ZOOM } from '../config.js'
import { isCurrentCore, isPredicted, ringCentroid } from '../geo.js'

// MapLibre 6 looks for its worker next to its own module URL, which breaks once
// Vite pre-bundles or bundles it. Point it at the worker file explicitly.
setWorkerUrl(maplibreWorkerUrl)

const EMPTY = { type: 'FeatureCollection', features: [] }
// Map layer colours come from the CSS tokens in index.css (see /DESIGN.md);
// the hex fallbacks only apply if the stylesheet hasn't loaded.
const cssVar = (name, fallback) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
const HAZARD = cssVar('--hazard', '#D9480F')
const MAP_BG = cssVar('--map-bg', '#F3F7FB')
const ROUTE = cssVar('--blue', '#0070C4')

// Predicted features carry `predicted_min`; everything else is the hazard now.
const PREDICTED = ['has', 'predicted_min']
const CURRENT = ['!', PREDICTED]

// OSM raster tiles, muted so the hazard and route stand out, but not so faint
// that street names disappear on a phone outdoors.
const BASE_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': MAP_BG } },
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
      paint: { 'raster-saturation': -0.85, 'raster-contrast': -0.15, 'raster-opacity': 0.8 },
    },
  ],
}

function boundsOf(coords) {
  if (coords.length === 0) return null
  return coords.reduce((b, c) => b.extend(c), new LngLatBounds(coords[0], coords[0]))
}

function youElement() {
  const el = document.createElement('div')
  el.className = 'you-marker'
  const label = document.createElement('span')
  label.className = 'map-label you-label'
  label.textContent = 'You'
  el.appendChild(label)
  return el
}

// Every shelter is a navy square; only the one the route goes to shows its name,
// so the map stays readable at phone size.
function shelterElement(name) {
  const el = document.createElement('div')
  el.className = 'shelter-marker'
  el.title = name
  const label = document.createElement('span')
  label.className = 'map-label shelter-label'
  label.textContent = name
  el.appendChild(label)
  return el
}

// Put the destination's name on whichever side of its square has more room,
// so it isn't cut off at the map edge.
function placeShelterLabels(map, store) {
  const half = map.getContainer().clientWidth / 2
  for (const m of store.values()) {
    const el = m.getElement()
    if (el.classList.contains('is-target')) el.classList.toggle('label-left', map.project(m.getLngLat()).x > half)
  }
}

function predictedLabel(minutes) {
  const el = document.createElement('div')
  el.className = 'map-label predicted-label'
  el.textContent = `T+${minutes}`
  return el
}

// Where to put a "T+30" label: the ring vertex farthest from the current hazard,
// i.e. the leading edge of the predicted spread.
function leadingEdge(feature, from) {
  const ring = feature.geometry?.coordinates?.[0]
  if (!ring?.length) return null
  if (!from) return ringCentroid(ring)
  let best = ring[0]
  let bestD = -1
  for (const p of ring) {
    const d = (p[0] - from[0]) ** 2 + (p[1] - from[1]) ** 2
    if (d > bestD) [best, bestD] = [p, d]
  }
  return best
}

export default function MapView({ hazards, shelters, route, location, onTap, focusKey, tall = false }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const youMarker = useRef(null)
  const shelterMarkers = useRef(new Map())
  const predictedMarkers = useRef(new Map())
  const tapRef = useRef(onTap)
  const framed = useRef(false)
  const lastFocus = useRef(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    tapRef.current = onTap
  }, [onTap])

  // Create the map once.
  useEffect(() => {
    const map = new MapLibreMap({
      container: containerRef.current,
      style: BASE_STYLE,
      center: MAP_CENTER,
      zoom: MAP_ZOOM,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    })
    map.touchZoomRotate.disableRotation()
    mapRef.current = map

    map.on('load', () => {
      map.addSource('hazards', { type: 'geojson', data: EMPTY })
      map.addSource('route', { type: 'geojson', data: EMPTY })
      // Predicted spread first, so the current hazard draws on top of it.
      map.addLayer({
        id: 'hazard-predicted',
        type: 'fill',
        source: 'hazards',
        filter: PREDICTED,
        paint: { 'fill-color': ROUTE, 'fill-opacity': 0.06 },
      })
      map.addLayer({
        id: 'hazard-predicted-outline',
        type: 'line',
        source: 'hazards',
        filter: PREDICTED,
        paint: { 'line-color': ROUTE, 'line-opacity': 0.7, 'line-width': 1.5, 'line-dasharray': [3, 3] },
      })
      map.addLayer({
        id: 'hazard-buffer',
        type: 'fill',
        source: 'hazards',
        filter: ['all', CURRENT, ['==', ['get', 'zone'], 'buffer']],
        paint: { 'fill-color': HAZARD, 'fill-opacity': 0.3 },
      })
      map.addLayer({
        id: 'hazard-core',
        type: 'fill',
        source: 'hazards',
        filter: ['all', CURRENT, ['==', ['get', 'zone'], 'core']],
        paint: { 'fill-color': HAZARD, 'fill-opacity': 0.85 },
      })
      // White casing under the blue line keeps it legible over grey tiles and orange hazards.
      map.addLayer({
        id: 'route-casing',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#FFFFFF', 'line-width': 9 },
      })
      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ROUTE, 'line-width': 5 },
      })
      setLoaded(true)
    })

    map.on('click', (e) => tapRef.current?.([e.lngLat.lng, e.lngLat.lat]))
    map.on('move', () => placeShelterLabels(map, shelterMarkers.current))

    const stores = [shelterMarkers.current, predictedMarkers.current]
    return () => {
      stores.forEach((s) => s.clear())
      youMarker.current = null
      framed.current = false
      lastFocus.current = null
      map.remove()
      mapRef.current = null
      setLoaded(false)
    }
  }, [])

  // The map is taller until a location is set; keep the canvas in step.
  useEffect(() => {
    mapRef.current?.resize()
  }, [tall])

  // Hazard polygons + "T+30 / T+60" labels on the predicted rings.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    map.getSource('hazards')?.setData(hazards ?? EMPTY)

    const features = hazards?.features ?? []
    const core = features.find(isCurrentCore)
    const from = core ? ringCentroid(core.geometry.coordinates[0]) : null
    const store = predictedMarkers.current
    const seen = new Set()
    for (const f of features.filter(isPredicted)) {
      const at = leadingEdge(f, from)
      if (!at) continue
      const key = `${f.id}:${f.properties.predicted_min}`
      seen.add(key)
      if (store.has(key)) store.get(key).setLngLat(at)
      else store.set(key, new Marker({ element: predictedLabel(f.properties.predicted_min) }).setLngLat(at).addTo(map))
    }
    for (const [key, m] of store) {
      if (!seen.has(key)) {
        m.remove()
        store.delete(key)
      }
    }
  }, [hazards, loaded])

  // Route line.
  useEffect(() => {
    if (!loaded) return
    const data = route?.geometry ? { type: 'Feature', properties: {}, geometry: route.geometry } : EMPTY
    mapRef.current?.getSource('route')?.setData(data)
  }, [route, loaded])

  // Shelters as navy squares; the route's destination shows its name.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    const store = shelterMarkers.current
    const seen = new Set()
    for (const f of shelters?.features ?? []) {
      seen.add(f.id)
      if (store.has(f.id)) store.get(f.id).setLngLat(f.geometry.coordinates)
      else
        store.set(
          f.id,
          new Marker({ element: shelterElement(f.properties.name) }).setLngLat(f.geometry.coordinates).addTo(map),
        )
      store.get(f.id).getElement().classList.toggle('is-target', f.id === route?.shelter_id)
    }
    for (const [id, m] of store) {
      if (!seen.has(id)) {
        m.remove()
        store.delete(id)
      }
    }
    placeShelterLabels(map, store)
  }, [shelters, route, loaded])

  // "You" marker.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    if (!location) {
      youMarker.current?.remove()
      youMarker.current = null
    } else if (youMarker.current) youMarker.current.setLngLat(location)
    else youMarker.current = new Marker({ element: youElement() }).setLngLat(location).addTo(map)
  }, [location, loaded])

  // First load: frame hazards and shelters so the fire is on screen.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map || framed.current || !hazards || !shelters) return
    const b = boundsOf([
      ...hazards.features.flatMap((f) => f.geometry?.coordinates?.[0] ?? []),
      ...shelters.features.map((f) => f.geometry.coordinates),
    ])
    if (b) map.fitBounds(b, { padding: 30, maxZoom: 13, duration: 0 })
    framed.current = true
  }, [hazards, shelters, loaded])

  // New location or "Start navigation": frame the route once it arrives.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map || !route?.geometry || focusKey == null || lastFocus.current === focusKey) return
    const b = boundsOf([...route.geometry.coordinates, ...(location ? [location] : [])])
    if (b) map.fitBounds(b, { padding: { top: 40, right: 40, bottom: 40, left: 40 }, maxZoom: 14, duration: 600 })
    lastFocus.current = focusKey
  }, [route, location, focusKey, loaded])

  return (
    <div className={tall ? 'map-wrap map-wrap-tall' : 'map-wrap'}>
      <div ref={containerRef} className="map" role="region" aria-label="Map. Tap to set your location." />
    </div>
  )
}
