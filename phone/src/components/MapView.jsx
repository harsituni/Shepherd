import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, Map as MapLibreMap, Marker, setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { MAP_CENTER, MAP_ZOOM } from '../config.js'
import { isCurrentCore, isPredicted, ringCentroid } from '../geo.js'
import { dangerRings, evacZones, unsafeShelterIds, UNSAFE_SHELTER_TEXT } from '../evacuation.js'

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
const ALT = cssVar('--muted-2', '#5B7590')
const CLOSED = cssVar('--closed', '#C62828')
const PREDICTED_COLOR = cssVar('--predicted', '#C62828')
const EVAC_STRIPE = cssVar('--evac-stripe', '#FFD400')
const EVAC_EDGE = cssVar('--evac-edge', '#9A6B00')

// Diagonal yellow stripes on a transparent tile, used as the evacuation zone's fill
// pattern (same as the dashboard). Drawn at 2× for sharp lines. Solid colour only.
function hatchImage(color) {
  const size = 8 // device px; 4 CSS px per tile (dense stripes)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const g = canvas.getContext('2d')
  g.strokeStyle = color
  g.lineWidth = 2
  g.lineCap = 'square'
  g.beginPath()
  for (const o of [-size, 0, size]) {
    g.moveTo(o, size)
    g.lineTo(o + size, 0)
  }
  g.stroke()
  return g.getImageData(0, 0, size, size)
}

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
// so the map stays readable at phone size. Tapping a square opens a small pop-up
// with how full it is (same content as the dashboard's hover pop-up).
function shelterElement(id, name, onToggle) {
  const el = document.createElement('div')
  el.className = 'shelter-marker'
  el.dataset.id = id
  el.tabIndex = 0
  el.setAttribute('role', 'button')
  el.setAttribute('aria-expanded', 'false')
  const label = document.createElement('span')
  label.className = 'map-label shelter-label'
  label.textContent = name
  const popup = document.createElement('div')
  popup.className = 'shelter-popup'
  el.append(label, popup)
  // Stop the tap reaching the map, where it would set "You" here.
  el.addEventListener('click', (e) => {
    e.stopPropagation()
    onToggle(id)
  })
  el.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return
    e.preventDefault()
    onToggle(id)
  })
  return el
}

const fmt = (n) => Number(n ?? 0).toLocaleString('en-CA')

// e.g. "312/2,000 (16%)", plus "Closed" if the shelter is shut. Unsafe (the fire is
// or is forecast to be near it): red square, red pop-up, and a one-line warning.
function updateShelter(el, { name, capacity, occupancy, open }, unsafe) {
  const pct = capacity ? Math.round(((occupancy ?? 0) / capacity) * 100) : 0
  const lines = [['shelter-popup-title', `${fmt(occupancy)}/${fmt(capacity)} (${pct}%)`]]
  if (open === false) lines.push(['shelter-popup-detail', 'Closed'])
  if (unsafe) lines.push(['shelter-popup-warning', UNSAFE_SHELTER_TEXT])
  el.classList.toggle('is-unsafe', unsafe)
  el.querySelector('.shelter-popup').replaceChildren(
    ...lines.map(([cls, text]) => {
      const line = document.createElement('div')
      line.className = cls
      line.textContent = text
      return line
    }),
  )
  el.setAttribute('aria-label', `${name}. ${lines.map(([, t]) => t).join('. ')}`)
}

// Put the destination's name on whichever side of its square has more room, and
// keep an open pop-up from running off the map's left or right edge.
function placeShelterLabels(map, store) {
  const width = map.getContainer().clientWidth
  for (const m of store.values()) {
    const el = m.getElement()
    const x = map.project(m.getLngLat()).x
    if (el.classList.contains('is-target')) el.classList.toggle('label-left', x > width / 2)
    el.classList.toggle('popup-start', x < 90)
    el.classList.toggle('popup-end', x > width - 90)
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

export default function MapView({ hazards, shelters, route, location, onTap, onViewChange, focusKey, tall = false }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const youMarker = useRef(null)
  const shelterMarkers = useRef(new Map())
  const predictedMarkers = useRef(new Map())
  const tapRef = useRef(onTap)
  const framed = useRef(false)
  const lastFocus = useRef(null)
  const openShelter = useRef(null) // id of the shelter whose pop-up is open
  const [loaded, setLoaded] = useState(false)

  // Open one shelter's pop-up (or none), closing any other.
  const showShelterPopup = useRef((id) => {
    openShelter.current = id
    for (const m of shelterMarkers.current.values()) {
      const el = m.getElement()
      const isOpen = el.dataset.id === id
      el.classList.toggle('is-open', isOpen)
      el.setAttribute('aria-expanded', String(isOpen))
    }
  }).current
  const toggleShelterPopup = useRef((id) => showShelterPopup(openShelter.current === id ? null : id)).current

  const viewRef = useRef(onViewChange)

  useEffect(() => {
    tapRef.current = onTap
    viewRef.current = onViewChange
  }, [onTap, onViewChange])

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
      // Evacuation zone first (bottom): yellow diagonal stripes with a darker yellow edge.
      map.addImage('evac-hatch', hatchImage(EVAC_STRIPE), { pixelRatio: 2 })
      map.addSource('evac', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'evac-fill',
        type: 'fill',
        source: 'evac',
        paint: { 'fill-pattern': 'evac-hatch', 'fill-opacity': 1 },
      })
      map.addLayer({
        id: 'evac-edge',
        type: 'line',
        source: 'evac',
        layout: { 'line-join': 'round' },
        paint: { 'line-color': EVAC_EDGE, 'line-width': 2 },
      })
      map.addSource('hazards', { type: 'geojson', data: EMPTY })
      map.addSource('route', { type: 'geojson', data: EMPTY })
      // Predicted spread first, so the current hazard draws on top of it.
      // No fill: a dotted red outline around each predicted ring (as on the dashboard).
      map.addLayer({
        id: 'hazard-predicted-outline',
        type: 'line',
        source: 'hazards',
        filter: PREDICTED,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': PREDICTED_COLOR, 'line-opacity': 0.9, 'line-width': 2, 'line-dasharray': [0, 2] },
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
      // The other route options: thin and dashed, blocked ones in closure red.
      map.addSource('route-alts', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'route-alts',
        type: 'line',
        source: 'route-alts',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['case', ['==', ['get', 'status'], 'blocked'], CLOSED, ALT],
          'line-width': 3,
          'line-dasharray': [2, 2],
          'line-opacity': 0.85,
        },
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

    // A tap on the map closes an open shelter pop-up; only otherwise does it set "You".
    map.on('click', (e) => {
      if (openShelter.current != null) return showShelterPopup(null)
      tapRef.current?.([e.lngLat.lng, e.lngLat.lat])
    })
    map.on('move', () => placeShelterLabels(map, shelterMarkers.current))
    const reportView = () => {
      const c = map.getCenter()
      viewRef.current?.([c.lng, c.lat], map.getZoom())
    }
    map.on('moveend', reportView)
    map.once('load', reportView)

    const stores = [shelterMarkers.current, predictedMarkers.current]
    return () => {
      stores.forEach((s) => s.clear())
      youMarker.current = null
      openShelter.current = null
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
    map.getSource('evac')?.setData(evacZones(hazards))

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
    const alts = (route?.options ?? [])
      .filter((o) => o.id !== route.route_id && o.geometry)
      .map((o) => ({ type: 'Feature', properties: { status: o.status }, geometry: o.geometry }))
    mapRef.current?.getSource('route-alts')?.setData({ type: 'FeatureCollection', features: alts })
  }, [route, loaded])

  // Shelters as navy squares; the route's destination shows its name.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    const store = shelterMarkers.current
    const seen = new Set()
    // The fire now + every forecast outline (fixtures only have the 30 / 60 min ones).
    const outlines = hazards?.forecast ?? (hazards?.features ?? []).filter(isPredicted)
    const unsafe = unsafeShelterIds(shelters, dangerRings(hazards, outlines))
    for (const f of shelters?.features ?? []) {
      seen.add(f.id)
      if (store.has(f.id)) store.get(f.id).setLngLat(f.geometry.coordinates)
      else
        store.set(
          f.id,
          new Marker({ element: shelterElement(f.id, f.properties.name, toggleShelterPopup) })
            .setLngLat(f.geometry.coordinates)
            .addTo(map),
        )
      const el = store.get(f.id).getElement()
      el.classList.toggle('is-target', f.id === route?.shelter_id)
      updateShelter(el, f.properties, unsafe.has(f.id)) // refreshes on every poll, even while open
    }
    for (const [id, m] of store) {
      if (!seen.has(id)) {
        m.remove()
        store.delete(id)
        if (openShelter.current === id) openShelter.current = null
      }
    }
    placeShelterLabels(map, store)
  }, [shelters, hazards, route, loaded])

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
