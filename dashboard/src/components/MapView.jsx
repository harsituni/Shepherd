import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, Map as MapLibreMap, Marker, setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

// MapLibre 6 looks for its worker next to its own module URL, which breaks once
// Vite pre-bundles or bundles it. Point it at the worker file explicitly.
setWorkerUrl(maplibreWorkerUrl)
import { MAP_CENTER, MAP_ZOOM } from '../config.js'
import MapLegend from './MapLegend.jsx'
import { MinusIcon, PlusIcon } from './icons.jsx'
import { evacZones, UNSAFE_SHELTER_TEXT } from '../evacuation.js'

const EMPTY = { type: 'FeatureCollection', features: [] }
const NO_IDS = new Set()
// Map layer colours come from the CSS tokens in index.css (see /DESIGN.md);
// the hex fallbacks only apply if the stylesheet hasn't loaded.
const cssVar = (name, fallback) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
const HAZARD = cssVar('--hazard', '#D9480F')
const HAZARD_HIGH = cssVar('--hazard-high', '#7A1F0A')
const PREDICTED_COLOR = cssVar('--predicted', '#C62828')
const MAP_BG = cssVar('--map-bg', '#F3F7FB')
const SURFACE = cssVar('--surface', '#FFFFFF')
const BLUE = cssVar('--blue', '#0070C4')
const EVAC_STRIPE = cssVar('--evac-stripe', '#FFD400')
const EVAC_EDGE = cssVar('--evac-edge', '#9A6B00')

// Diagonal yellow stripes on a transparent tile, used as the evacuation zone's fill
// pattern. Drawn at 2× for sharp lines on high-DPI screens. Solid colour only.
function hatchImage(color) {
  const size = 8 // device px; 4 CSS px per tile (dense stripes)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const g = canvas.getContext('2d')
  g.strokeStyle = color
  g.lineWidth = 2
  g.lineCap = 'square'
  g.beginPath()
  // One diagonal plus the two corner pieces, so stripes join up across tiles.
  for (const o of [-size, 0, size]) {
    g.moveTo(o, size)
    g.lineTo(o + size, 0)
  }
  g.stroke()
  return g.getImageData(0, 0, size, size)
}

// OSM raster tiles, muted so our orange/blue layers stand out (as in the mockup).
const BASE_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
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

function ringCentroid(feature) {
  const ring = feature.geometry?.coordinates?.[0]
  if (!ring?.length) return null
  const pts = ring.length > 1 ? ring.slice(0, -1) : ring
  return [
    pts.reduce((s, p) => s + p[0], 0) / pts.length,
    pts.reduce((s, p) => s + p[1], 0) / pts.length,
  ]
}

// Keep a set of HTML markers in sync with a list of { id, lngLat, build, update? }.
// `update(el)` runs on every sync, for markers whose content changes between polls.
function syncMarkers(map, store, items) {
  const seen = new Set()
  for (const { id, lngLat, build, update } of items) {
    seen.add(id)
    let marker = store.get(id)
    if (marker) marker.setLngLat(lngLat)
    else {
      marker = new Marker({ element: build(), anchor: 'center' }).setLngLat(lngLat).addTo(map)
      store.set(id, marker)
    }
    update?.(marker.getElement())
  }
  for (const [id, marker] of store) {
    if (!seen.has(id)) {
      marker.remove()
      store.delete(id)
    }
  }
}

// Shelter: navy square + name label, with a capacity pop-up on hover or keyboard focus.
function shelterElement(name) {
  const el = document.createElement('div')
  el.className = 'shelter-marker'
  el.tabIndex = 0
  const label = document.createElement('span')
  label.className = 'shelter-label'
  label.textContent = name
  const popup = document.createElement('div')
  popup.className = 'shelter-popup'
  popup.setAttribute('role', 'tooltip')
  el.append(label, popup)
  return el
}

const fmt = (n) => Number(n ?? 0).toLocaleString('en-CA')

// unsafe = the fire is (or is forecast to be) within the evacuation buffer of it:
// the square turns red and the pop-up says so, in red.
function updateShelter(el, { name, capacity, occupancy, open }, unsafe) {
  const pct = capacity ? Math.round(((occupancy ?? 0) / capacity) * 100) : 0
  // e.g. "312/2,000 (16%)"
  const lines = [['shelter-popup-title', `${fmt(occupancy)}/${fmt(capacity)} (${pct}%)`]]
  if (open === false) lines.push(['shelter-popup-detail', 'Closed'])
  if (unsafe) lines.push(['shelter-popup-warning', UNSAFE_SHELTER_TEXT])
  el.classList.toggle('is-unsafe', unsafe)
  const popup = el.querySelector('.shelter-popup')
  popup.replaceChildren(...lines.map(([cls, text]) => textElement(cls, text)))
  el.setAttribute('aria-label', `${name}. ${lines.map(([, t]) => t).join('. ')}`)
}

function textElement(className, text) {
  const el = document.createElement('div')
  el.className = className
  el.textContent = text
  return el
}

const nowElement = () => textElement('now-label', '')

// Priority resident (a phone registered with an Alberta disability ID): navy
// diamond, with a pop-up of what responders need: needs, ID type, note.
const PRIORITY_ID_LABEL = {
  dats: 'DATS (Edmonton)',
  parking_placard: 'Accessible parking placard',
  aish: 'AISH card',
  adap: 'ADAP client ID',
  pdd: 'PDD program',
  cnib: 'CNIB card',
  other: 'Other ID',
}
const PRIORITY_NEED_LABEL = {
  mobility: 'Wheelchair or mobility aid',
  no_vehicle: 'No vehicle',
  vision: 'Blind or low vision',
  hearing: 'Deaf or hard of hearing',
  medical: 'Medical equipment or oxygen',
  cognitive: 'Cognitive or developmental',
  other: 'Other needs',
}

function priorityElement() {
  const el = document.createElement('div')
  el.className = 'priority-marker'
  el.tabIndex = 0
  const mark = document.createElement('span')
  mark.className = 'priority-diamond'
  const popup = document.createElement('div')
  popup.className = 'shelter-popup priority-popup'
  popup.setAttribute('role', 'tooltip')
  el.append(mark, popup)
  return el
}

function updatePriority(el, p) {
  const needs = (p.priority_needs ?? []).map((n) => PRIORITY_NEED_LABEL[n] ?? n)
  const lines = [['shelter-popup-title', 'Priority resident']]
  if (needs.length) lines.push(['priority-popup-line', needs.join(', ')])
  lines.push(['priority-popup-line', `ID: ${PRIORITY_ID_LABEL[p.priority_id_type] ?? 'Disability ID'}`])
  if (p.priority_note) lines.push(['priority-popup-line', `Note: ${p.priority_note}`])
  el.querySelector('.priority-popup').replaceChildren(...lines.map(([cls, text]) => textElement(cls, text)))
  el.setAttribute('aria-label', lines.map(([, t]) => t).join('. '))
}

function startElement() {
  const el = document.createElement('div')
  el.className = 'start-marker'
  el.title = 'Start point'
  return el
}

// Predicted-spread features from the backend carry `predicted_min` (e.g. 30, 60).
const isPredicted = (f) => f.properties?.predicted_min != null
const PREDICTED = ['has', 'predicted_min']
const CURRENT = ['!', PREDICTED]

// Wildfire intensity: nested copies of each burning (core) polygon, shrunk toward
// its centre, so the fire reads orange at the edge and dark red where it's
// hottest. The backend sends one outline per zone, so this is drawn client-side.
const INTENSITY_SCALES = [0.75, 0.5, 0.25] // band levels 1..3
function intensityBands(hazards) {
  const bands = []
  for (const f of hazards?.features ?? []) {
    const p = f.properties ?? {}
    if (isPredicted(f) || p.zone !== 'core' || p.kind !== 'wildfire') continue
    const c = ringCentroid(f)
    const ring = f.geometry?.coordinates?.[0]
    if (!c || !ring) continue
    INTENSITY_SCALES.forEach((s, i) =>
      bands.push({
        type: 'Feature',
        properties: { level: i + 1 },
        geometry: {
          type: 'Polygon',
          coordinates: [ring.map(([x, y]) => [c[0] + (x - c[0]) * s, c[1] + (y - c[1]) * s])],
        },
      }),
    )
  }
  return { type: 'FeatureCollection', features: bands }
}

// Where to put a "T+30" label: the ring vertex farthest from the current hazard,
// i.e. the leading edge of the predicted spread.
function leadingEdge(feature, from) {
  const ring = feature.geometry?.coordinates?.[0]
  if (!ring?.length) return null
  if (!from) return ringCentroid(feature)
  let best = ring[0]
  let bestD = -1
  for (const p of ring) {
    const d = (p[0] - from[0]) ** 2 + (p[1] - from[1]) ** 2
    if (d > bestD) [best, bestD] = [p, d]
  }
  return best
}

export default function MapView({
  hazards,
  nowLabel = 'Now', // "T+42" while the history slider is off live
  shelters,
  unsafeShelters = NO_IDS, // Set of shelter ids the fire is forecast to reach (evacuation.js)
  evacuees, // GET /evacuees FeatureCollection
  onlyPriority = false, // hide ordinary phones, keep priority residents
  reports,
  focus,
  startPoint,
  showPredicted = true,
  onMapClick,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const shelterMarkers = useRef(new Map())
  const nowMarkers = useRef(new Map())
  const predictedMarkers = useRef(new Map())
  const startMarkers = useRef(new Map())
  const priorityMarkers = useRef(new Map())
  const clickRef = useRef(onMapClick)
  const framed = useRef(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    clickRef.current = onMapClick
  }, [onMapClick])

  // Create the map once.
  useEffect(() => {
    const map = new MapLibreMap({
      container: containerRef.current,
      style: BASE_STYLE,
      center: MAP_CENTER,
      zoom: MAP_ZOOM,
      attributionControl: { compact: true },
    })
    mapRef.current = map
    map.getCanvas().style.cursor = 'crosshair'

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
      // Predicted spread first, so the current hazard draws on top of it.
      // No fill: just a dotted outline around each predicted ring.
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
      map.addSource('hazard-intensity', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'hazard-intensity',
        type: 'fill',
        source: 'hazard-intensity',
        paint: {
          'fill-color': ['interpolate', ['linear'], ['get', 'level'], 0, HAZARD, 3, HAZARD_HIGH],
          'fill-opacity': 0.9,
        },
      })
      map.addLayer({
        id: 'hazard-outline',
        type: 'line',
        source: 'hazards',
        filter: CURRENT,
        paint: { 'line-color': HAZARD, 'line-width': 1.5 },
      })
      // Phone reports: white dot with an orange ring (matches the legend swatch).
      map.addSource('reports', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'report-pins',
        type: 'circle',
        source: 'reports',
        paint: {
          'circle-radius': 6,
          'circle-color': SURFACE,
          'circle-stroke-color': HAZARD,
          'circle-stroke-width': 2.5,
        },
      })
      // Phones that have set a location (GET /evacuees): the same blue dot with a
      // white ring the phone shows for "You", a little smaller. On top of everything.
      map.addSource('evacuees', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'evacuee-dots',
        type: 'circle',
        source: 'evacuees',
        paint: {
          'circle-radius': 6,
          'circle-color': BLUE,
          'circle-stroke-color': SURFACE,
          'circle-stroke-width': 2.5,
        },
      })
      setLoaded(true)
    })

    map.on('click', (e) => clickRef.current?.(e.lngLat))

    const stores = [shelterMarkers, nowMarkers, predictedMarkers, startMarkers, priorityMarkers].map((r) => r.current)
    return () => {
      stores.forEach((s) => s.clear())
      map.remove()
      mapRef.current = null
      framed.current = false
      setLoaded(false)
    }
  }, [])

  // Once, when the first data arrives: frame every hazard and shelter so the
  // fire is on screen (the contract start view can leave it just off the edge).
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map || framed.current || !hazards || !shelters) return
    const coords = [
      ...hazards.features.flatMap((f) => f.geometry?.coordinates?.[0] ?? []),
      ...shelters.features.map((f) => f.geometry.coordinates),
    ]
    if (coords.length === 0) return
    const bounds = coords.reduce((b, c) => b.extend(c), new LngLatBounds(coords[0], coords[0]))
    map.fitBounds(bounds, { padding: { top: 70, right: 250, bottom: 70, left: 70 }, maxZoom: 13, duration: 800 })
    framed.current = true
  }, [hazards, shelters, loaded])

  // Hazards: polygons + a "Now" label on each core zone.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    map.getSource('hazards')?.setData(hazards ?? EMPTY)
    map.getSource('hazard-intensity')?.setData(intensityBands(hazards))
    map.getSource('evac')?.setData(evacZones(hazards)) // follows the slider, like the fire
    const features = hazards?.features ?? []
    const current = features.filter((f) => !isPredicted(f) && f.properties?.zone === 'core')
    const items = current
      .map((f) => ({
        id: f.id,
        lngLat: ringCentroid(f),
        build: nowElement,
        update: (el) => {
          el.textContent = nowLabel
        },
      }))
      .filter((i) => i.lngLat)
    syncMarkers(map, nowMarkers.current, items)

    const from = current.length ? ringCentroid(current[0]) : null
    const labels = showPredicted
      ? features
          .filter(isPredicted)
          .map((f) => ({
            id: `${f.id}:${f.properties.predicted_min}`,
            lngLat: leadingEdge(f, from),
            build: () => textElement('predicted-label', `T+${f.properties.predicted_min}`),
          }))
          .filter((i) => i.lngLat)
      : []
    syncMarkers(map, predictedMarkers.current, labels)
  }, [hazards, nowLabel, showPredicted, loaded])

  // "Show predicted path" toggle.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    const visibility = showPredicted ? 'visible' : 'none'
    map.setLayoutProperty('hazard-predicted-outline', 'visibility', visibility)
  }, [showPredicted, loaded])

  // Start point picked on the map, before the simulation is started.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    const items = startPoint ? [{ id: 'start', lngLat: [startPoint.lng, startPoint.lat], build: startElement }] : []
    syncMarkers(map, startMarkers.current, items)
  }, [startPoint, loaded])

  // Shelters: navy squares with Public Sans name labels.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    const items = (shelters?.features ?? []).map((f) => ({
      id: f.id,
      lngLat: f.geometry.coordinates,
      build: () => shelterElement(f.properties.name),
      update: (el) => updateShelter(el, f.properties, unsafeShelters.has(f.id)),
    }))
    syncMarkers(map, shelterMarkers.current, items)
  }, [shelters, unsafeShelters, loaded])

  // Evacuees: one dot per phone, redrawn on every poll.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    // Ordinary phones are blue dots; priority residents are diamond markers on top.
    const all = evacuees?.features ?? []
    const plain = onlyPriority ? [] : all.filter((f) => !f.properties?.priority)
    map.getSource('evacuees')?.setData({ type: 'FeatureCollection', features: plain })
    const items = all
      .filter((f) => f.properties?.priority)
      .map((f) => ({
        id: f.id,
        lngLat: f.geometry.coordinates,
        build: priorityElement,
        update: (el) => updatePriority(el, f.properties),
      }))
    syncMarkers(map, priorityMarkers.current, items)
  }, [evacuees, onlyPriority, loaded])

  // Reports: pins redrawn on every poll.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    map.getSource('reports')?.setData(reports ?? EMPTY)
  }, [reports, loaded])

  // Centre on a report picked from the side panel.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map || !focus) return
    map.flyTo({ center: focus.lngLat, zoom: Math.max(map.getZoom(), 14), duration: 800 })
  }, [focus, loaded])

  return (
    <div className="map-wrap">
      <div
        ref={containerRef}
        className="map"
        role="region"
        aria-label="Map of Edmonton. Click to place the hazard start point."
      />
      <MapLegend />
      <div className="zoom">
        <button type="button" aria-label="Zoom in" onClick={() => mapRef.current?.zoomIn()}>
          <PlusIcon />
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => mapRef.current?.zoomOut()}>
          <MinusIcon />
        </button>
      </div>
    </div>
  )
}
