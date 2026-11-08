import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, Map as MapLibreMap, Marker, setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { MAP_CENTER, MAP_ZOOM } from '../config.js'
import { isCurrentCore, isPredicted, ringCentroid } from '../geo.js'
import { dangerRings, evacZones, unsafeShelterIds, UNSAFE_SHELTER_TEXT } from '../evacuation.js'
import { kindOf, REPORT_KINDS, reportSvg } from '../reportKinds.js'

// MapLibre 6 looks for its worker next to its own module URL, which breaks once
// Vite pre-bundles or bundles it. Point it at the worker file explicitly.
setWorkerUrl(maplibreWorkerUrl)

const EMPTY = { type: 'FeatureCollection', features: [] }
// Map layer colours come from the CSS tokens in index.css (see /DESIGN.md);
// the hex fallbacks only apply if the stylesheet hasn't loaded.
const cssVar = (name, fallback) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
const HAZARD = cssVar('--hazard', '#D9480F')
const TORNADO = cssVar('--tornado', '#4A3A6B')
const MAP_BG = cssVar('--map-bg', '#F3F7FB')
const ROUTE = cssVar('--blue', '#0070C4')
const ALT = cssVar('--muted-2', '#5B7590')
const CLOSED = cssVar('--closed', '#C62828')
const PREDICTED_COLOR = cssVar('--predicted', '#C62828')
const EVAC_STRIPE = cssVar('--evac-stripe', '#FFD400')
const EVAC_EDGE = cssVar('--evac-edge', '#9A6B00')
const KIND_COLOR = ['match', ['get', 'kind'], 'tornado', TORNADO, HAZARD]

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

// Hollow pin where the person tapped, while they confirm it as their location.
function pendingElement() {
  const el = document.createElement('div')
  el.className = 'pending-marker'
  return el
}

// Hazard reports from every phone (GET /reports): a white circle with the kind's
// stroke symbol in hazard orange. Tap for what was reported, when, and the note.
function reportElement(id, kind, onToggle) {
  const el = document.createElement('div')
  el.className = `report-marker rk-${kindOf(kind)}`
  el.dataset.id = id
  el.tabIndex = 0
  el.setAttribute('role', 'button')
  el.setAttribute('aria-expanded', 'false')
  el.append(reportSvg(kind), Object.assign(document.createElement('div'), { className: 'shelter-popup report-popup' }))
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

// The report's message is written for emergency personnel, so the public pop-up
// shows only what was reported and when.
function updateReport(el, { kind, sim_time: t }) {
  const info = REPORT_KINDS[kind] ?? REPORT_KINDS.other
  const lines = [['shelter-popup-title', info.seen]]
  // sim_time is 0 when no scenario is running; "T+0" would mean nothing to a resident.
  if (t) lines.push(['report-popup-time num', `T+${t} min`])
  el.querySelector('.report-popup').replaceChildren(
    ...lines.map(([cls, text]) => Object.assign(document.createElement('div'), { className: cls, textContent: text })),
  )
  el.setAttribute('aria-label', lines.map(([, text]) => text).join('. '))
}

// The pin being dropped for a new report: a hazard-orange teardrop map pin with a
// white centre, anchored at its tip. Draggable while placing.
const SVG_NS = 'http://www.w3.org/2000/svg'
function reportPinElement() {
  const el = document.createElement('div')
  el.className = 'report-pin'
  el.setAttribute('aria-label', 'Report pin. Drag to where the hazard is.')
  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('viewBox', '0 0 32 42')
  svg.setAttribute('width', '32')
  svg.setAttribute('height', '42')
  svg.setAttribute('aria-hidden', 'true')
  const body = document.createElementNS(SVG_NS, 'path')
  body.setAttribute('d', 'M16 40.5S3 26.4 3 15.5a13 13 0 0 1 26 0C29 26.4 16 40.5 16 40.5z')
  body.setAttribute('class', 'report-pin-body')
  const dot = document.createElementNS(SVG_NS, 'circle')
  dot.setAttribute('cx', '16')
  dot.setAttribute('cy', '15.5')
  dot.setAttribute('r', '5')
  dot.setAttribute('class', 'report-pin-dot')
  svg.append(body, dot)
  el.appendChild(svg)
  return el
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

// Framing padding: an even `fallback` all round, plus whatever a map-first layout
// says its floating controls cover ({ top, bottom, left, right } in px).
const pad = (extra, fallback) => ({
  top: fallback + (extra?.top ?? 0),
  right: fallback + (extra?.right ?? 0),
  bottom: fallback + (extra?.bottom ?? 0),
  left: fallback + (extra?.left ?? 0),
})

export default function MapView({
  hazards,
  shelters,
  route,
  location,
  pending, // [lon, lat] tapped but not yet confirmed, or null
  reports, // public hazard reports (GET /reports, filtered in api.js)
  reportPin, // [lon, lat] of a report being placed, or null
  reportStep, // 'place' | 'details' | null: where the pin should sit on screen
  onReportPinMove, // ([lon, lat]) after the pin is dragged
  onTap,
  onViewChange,
  focusKey,
  tall = false,
  framePadding, // map-first layouts: px hidden behind floating controls
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const youMarker = useRef(null)
  const pendingMarker = useRef(null)
  const reportPinMarker = useRef(null)
  const reportMarkers = useRef(new Map())
  const shelterMarkers = useRef(new Map())
  const predictedMarkers = useRef(new Map())
  const tapRef = useRef(onTap)
  const framed = useRef(false)
  const lastFocus = useRef(null)
  const openShelter = useRef(null) // id of the shelter whose pop-up is open
  const [loaded, setLoaded] = useState(false)

  // One pop-up open at a time across shelters and reports, keyed "s:<id>" / "r:<id>".
  const showShelterPopup = useRef((key) => {
    openShelter.current = key
    const stores = [
      ['s:', shelterMarkers.current],
      ['r:', reportMarkers.current],
    ]
    for (const [prefix, store] of stores) {
      for (const m of store.values()) {
        const el = m.getElement()
        const isOpen = key === prefix + el.dataset.id
        el.classList.toggle('is-open', isOpen)
        el.setAttribute('aria-expanded', String(isOpen))
      }
    }
  }).current
  const togglePopup = (key) => showShelterPopup(openShelter.current === key ? null : key)
  const toggleShelterPopup = useRef((id) => togglePopup(`s:${id}`)).current
  const toggleReportPopup = useRef((id) => togglePopup(`r:${id}`)).current

  const viewRef = useRef(onViewChange)
  const pinMoveRef = useRef(onReportPinMove)
  useEffect(() => {
    pinMoveRef.current = onReportPinMove
  }, [onReportPinMove])

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
      // Tornado damage scar: faint fill + edge so it reads as a path, not a purple lake.
      map.addLayer({
        id: 'hazard-scar',
        type: 'fill',
        source: 'hazards',
        filter: ['all', CURRENT, ['==', ['get', 'role'], 'damage_path']],
        paint: { 'fill-color': KIND_COLOR, 'fill-opacity': 0.14 },
      })
      map.addLayer({
        id: 'hazard-scar-outline',
        type: 'line',
        source: 'hazards',
        filter: ['all', CURRENT, ['==', ['get', 'role'], 'damage_path']],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': KIND_COLOR, 'line-width': 2, 'line-opacity': 0.75 },
      })
      map.addLayer({
        id: 'hazard-buffer',
        type: 'fill',
        source: 'hazards',
        filter: [
          'all',
          CURRENT,
          ['==', ['get', 'zone'], 'buffer'],
          ['!=', ['get', 'role'], 'damage_path'],
        ],
        paint: { 'fill-color': KIND_COLOR, 'fill-opacity': 0.22 },
      })
      map.addLayer({
        id: 'hazard-core',
        type: 'fill',
        source: 'hazards',
        filter: ['all', CURRENT, ['==', ['get', 'zone'], 'core']],
        paint: { 'fill-color': KIND_COLOR, 'fill-opacity': 0.85 },
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
    map.on('move', () => {
      placeShelterLabels(map, shelterMarkers.current)
      placeShelterLabels(map, reportMarkers.current)
    })
    const reportView = () => {
      const c = map.getCenter()
      viewRef.current?.([c.lng, c.lat], map.getZoom())
    }
    map.on('moveend', reportView)
    map.once('load', reportView)

    const stores = [shelterMarkers.current, predictedMarkers.current, reportMarkers.current]
    return () => {
      stores.forEach((s) => s.clear())
      youMarker.current = null
      pendingMarker.current = null
      reportPinMarker.current = null
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
        if (openShelter.current === `s:${id}`) openShelter.current = null
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

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    if (!pending) {
      pendingMarker.current?.remove()
      pendingMarker.current = null
    } else if (pendingMarker.current) pendingMarker.current.setLngLat(pending)
    else pendingMarker.current = new Marker({ element: pendingElement() }).setLngLat(pending).addTo(map)
  }, [pending, loaded])

  // Hazard reports from every phone, refreshed on each poll (even while one is open).
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    const store = reportMarkers.current
    const seen = new Set()
    for (const f of reports?.features ?? []) {
      const id = String(f.id)
      seen.add(id)
      if (store.has(id)) store.get(id).setLngLat(f.geometry.coordinates)
      else
        store.set(
          id,
          new Marker({ element: reportElement(id, f.properties.kind, toggleReportPopup) })
            .setLngLat(f.geometry.coordinates)
            .addTo(map),
        )
      updateReport(store.get(id).getElement(), f.properties)
    }
    for (const [id, m] of store) {
      if (!seen.has(id)) {
        m.remove()
        store.delete(id)
        if (openShelter.current === `r:${id}`) openShelter.current = null
      }
    }
    placeShelterLabels(map, store)
  }, [reports, loaded])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !loaded) return
    if (!reportPin) {
      reportPinMarker.current?.remove()
      reportPinMarker.current = null
      return
    }
    const marker = reportPinMarker.current
    if (marker) marker.setLngLat(reportPin)
    else {
      const m = new Marker({ element: reportPinElement(), anchor: 'bottom', draggable: true })
      m.on('dragend', () => {
        const p = m.getLngLat()
        pinMoveRef.current?.([p.lng, p.lat])
      })
      reportPinMarker.current = m.setLngLat(reportPin).addTo(map)
    }
    reportPinMarker.current.setDraggable(reportStep === 'place')
    reportPinMarker.current.getElement().classList.toggle('is-placing', reportStep === 'place')
  }, [reportPin, reportStep, loaded])

  // Only when the step changes (not on every drag): with the sheet open it covers the
  // bottom of the screen, so slide the pin into the strip above it; while placing,
  // bring it back to the middle, clear of the instruction card at the top.
  useEffect(() => {
    const map = mapRef.current
    const pin = reportPinMarker.current
    if (!map || !loaded || !pin || !reportStep) return
    const h = map.getContainer().clientHeight
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const offset = reportStep === 'details' ? [0, -h * 0.22] : [0, h * 0.1]
    map.easeTo({ center: pin.getLngLat(), offset, duration: reduce ? 0 : 400 })
  }, [reportStep, loaded])

  // First load: frame hazards and shelters so the fire is on screen.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map || framed.current || !hazards || !shelters) return
    const b = boundsOf([
      ...hazards.features.flatMap((f) => f.geometry?.coordinates?.[0] ?? []),
      ...shelters.features.map((f) => f.geometry.coordinates),
    ])
    if (b) map.fitBounds(b, { padding: pad(framePadding, 30), maxZoom: 13, duration: 0 })
    framed.current = true
  }, [hazards, shelters, loaded, framePadding])

  // New location or "Start navigation": frame the route once it arrives.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map || !route?.geometry || focusKey == null || lastFocus.current === focusKey) return
    const b = boundsOf([...route.geometry.coordinates, ...(location ? [location] : [])])
    if (b) map.fitBounds(b, { padding: pad(framePadding, 40), maxZoom: 14, duration: 600 })
    lastFocus.current = focusKey
  }, [route, location, focusKey, loaded, framePadding])

  return (
    <div className={tall ? 'map-wrap map-wrap-tall' : 'map-wrap'}>
      <div ref={containerRef} className="map" role="region" aria-label="Map. Tap to set your location." />
    </div>
  )
}
