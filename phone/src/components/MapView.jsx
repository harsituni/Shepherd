import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, Map as MapLibreMap, Marker, setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { MAP_CENTER, MAP_ZOOM } from '../config.js'

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
const ROUTE_CYAN = '#00C2D7'

// OSM raster tiles, muted so the hazard and route stand out (as in the mockup).
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
      paint: { 'raster-saturation': -0.85, 'raster-contrast': -0.15, 'raster-opacity': 0.6 },
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
  label.className = 'you-label'
  label.textContent = 'You'
  el.appendChild(label)
  return el
}

function shelterElement(name) {
  const el = document.createElement('div')
  el.className = 'shelter-marker'
  el.title = name
  return el
}

export default function MapView({ hazards, shelters, route, location, onTap, focusKey }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const youMarker = useRef(null)
  const shelterMarkers = useRef(new Map())
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
        paint: { 'fill-color': HAZARD, 'fill-opacity': 0.85 },
      })
      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ROUTE_CYAN, 'line-width': 6 },
      })
      setLoaded(true)
    })

    map.on('click', (e) => tapRef.current?.([e.lngLat.lng, e.lngLat.lat]))

    const shelterStore = shelterMarkers.current
    return () => {
      shelterStore.clear()
      youMarker.current = null
      framed.current = false
      lastFocus.current = null
      map.remove()
      mapRef.current = null
      setLoaded(false)
    }
  }, [])

  // Hazard polygons.
  useEffect(() => {
    if (loaded) mapRef.current?.getSource('hazards')?.setData(hazards ?? EMPTY)
  }, [hazards, loaded])

  // Route line.
  useEffect(() => {
    if (!loaded) return
    const data = route?.geometry ? { type: 'Feature', properties: {}, geometry: route.geometry } : EMPTY
    mapRef.current?.getSource('route')?.setData(data)
  }, [route, loaded])

  // Shelters as navy squares.
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
    }
    for (const [id, m] of store) {
      if (!seen.has(id)) {
        m.remove()
        store.delete(id)
      }
    }
  }, [shelters, loaded])

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
    <div className="map-wrap">
      <div ref={containerRef} className="map" role="region" aria-label="Map. Tap to set your location." />
    </div>
  )
}
