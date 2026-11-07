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

const EMPTY = { type: 'FeatureCollection', features: [] }
const HAZARD = '#D9480F'

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
    { id: 'background', type: 'background', paint: { 'background-color': '#F3F7FB' } },
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
      paint: { 'raster-saturation': -0.85, 'raster-contrast': -0.15, 'raster-opacity': 0.6 },
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

// Keep a set of HTML markers in sync with a list of { id, lngLat, build }.
function syncMarkers(map, store, items) {
  const seen = new Set()
  for (const { id, lngLat, build } of items) {
    seen.add(id)
    const existing = store.get(id)
    if (existing) existing.setLngLat(lngLat)
    else store.set(id, new Marker({ element: build(), anchor: 'center' }).setLngLat(lngLat).addTo(map))
  }
  for (const [id, marker] of store) {
    if (!seen.has(id)) {
      marker.remove()
      store.delete(id)
    }
  }
}

function shelterElement(name) {
  const el = document.createElement('div')
  el.className = 'shelter-marker'
  const label = document.createElement('span')
  label.className = 'shelter-label'
  label.textContent = name
  el.appendChild(label)
  return el
}

function nowElement() {
  const el = document.createElement('div')
  el.className = 'now-label'
  el.textContent = 'Now'
  return el
}

export default function MapView({ hazards, shelters, onMapClick }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const shelterMarkers = useRef(new Map())
  const nowMarkers = useRef(new Map())
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
      map.addSource('hazards', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'hazard-buffer',
        type: 'fill',
        source: 'hazards',
        filter: ['==', ['get', 'zone'], 'buffer'],
        paint: { 'fill-color': HAZARD, 'fill-opacity': 0.3 },
      })
      map.addLayer({
        id: 'hazard-core',
        type: 'fill',
        source: 'hazards',
        filter: ['==', ['get', 'zone'], 'core'],
        paint: { 'fill-color': HAZARD, 'fill-opacity': 0.82 },
      })
      map.addLayer({
        id: 'hazard-outline',
        type: 'line',
        source: 'hazards',
        paint: { 'line-color': HAZARD, 'line-width': 1.5 },
      })
      setLoaded(true)
    })

    map.on('click', (e) => clickRef.current?.(e.lngLat))

    const shelterStore = shelterMarkers.current
    const nowStore = nowMarkers.current
    return () => {
      shelterStore.clear()
      nowStore.clear()
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
    const items = (hazards?.features ?? [])
      .filter((f) => f.properties?.zone === 'core')
      .map((f) => ({ id: f.id, lngLat: ringCentroid(f), build: nowElement }))
      .filter((i) => i.lngLat)
    syncMarkers(map, nowMarkers.current, items)
  }, [hazards, loaded])

  // Shelters: navy squares with Public Sans name labels.
  useEffect(() => {
    const map = mapRef.current
    if (!loaded || !map) return
    const items = (shelters?.features ?? []).map((f) => ({
      id: f.id,
      lngLat: f.geometry.coordinates,
      build: () => shelterElement(f.properties.name),
    }))
    syncMarkers(map, shelterMarkers.current, items)
  }, [shelters, loaded])

  return (
    <div className="map-wrap">
      <div
        ref={containerRef}
        className="map"
        role="region"
        aria-label="Map of Edmonton. Click to place a hazard."
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
