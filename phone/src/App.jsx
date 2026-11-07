import { useCallback, useEffect, useRef, useState } from 'react'
import { getHazards, getRoute, getShelters, postReport } from './api.js'
import { POLL_MS } from './config.js'
import AlertBanner from './components/AlertBanner.jsx'
import MapView from './components/MapView.jsx'
import RouteTab from './components/RouteTab.jsx'
import TipsTab from './components/TipsTab.jsx'
import ReportSheet from './components/ReportSheet.jsx'

const TABS = [
  ['route', 'Route'],
  ['tips', 'Survival tips'],
  ['gov', 'Gov updates'],
]

export default function App() {
  const [tab, setTab] = useState('route')
  const [location, setLocation] = useState(null) // [lon, lat]
  const [route, setRoute] = useState(null)
  const [routeError, setRouteError] = useState(null)
  const [hazards, setHazards] = useState(null)
  const [shelters, setShelters] = useState(null)
  const [focusKey, setFocusKey] = useState(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [toast, setToast] = useState(null)
  const toastTimer = useRef(null)
  const locationRef = useRef(location)

  useEffect(() => {
    locationRef.current = location
  }, [location])

  const showToast = useCallback((text) => {
    clearTimeout(toastTimer.current)
    setToast(text)
    toastTimer.current = setTimeout(() => setToast(null), 3000)
  }, [])

  const refresh = useCallback(async () => {
    const [h, s] = await Promise.allSettled([getHazards(), getShelters()])
    if (h.status === 'fulfilled') setHazards(h.value)
    if (s.status === 'fulfilled') setShelters(s.value)

    const loc = locationRef.current
    if (!loc) return
    try {
      const r = await getRoute(loc[1], loc[0])
      if (locationRef.current !== loc) return // location changed mid-request
      setRoute(r)
      setRouteError(null)
    } catch (err) {
      if (locationRef.current !== loc) return
      setRoute(null)
      setRouteError(err.code === 'no_route' ? 'no_route' : 'network')
    }
  }, [])

  useEffect(() => {
    const first = setTimeout(refresh, 0)
    const id = setInterval(refresh, POLL_MS)
    return () => {
      clearTimeout(first)
      clearInterval(id)
    }
  }, [refresh])

  const setLocationAndRoute = useCallback(
    (lngLat) => {
      locationRef.current = lngLat
      setLocation(lngLat)
      setRoute(null)
      setRouteError(null)
      setFocusKey(Date.now())
      refresh()
    },
    [refresh],
  )

  const sendReport = useCallback(
    async (kind, note) => {
      const loc = locationRef.current
      if (!loc) {
        showToast('Tap the map to set your location first.')
        setTab('route')
        return false
      }
      setSending(true)
      try {
        await postReport({ kind, lat: loc[1], lon: loc[0], note })
        showToast(
          kind === 'safe' ? "Marked as safe. Thank you." : kind === 'sos' ? 'Help request sent. Responders can see your location.' : 'Report sent. Thank you.',
        )
        return true
      } catch {
        showToast("Couldn't send. Check your connection and try again.")
        return false
      } finally {
        setSending(false)
      }
    },
    [showToast],
  )

  return (
    <div className="phone">
      <header className="header">
        <span className="brand">Shepherd</span>
        <span className="city">Edmonton</span>
      </header>

      <AlertBanner hazards={hazards} location={location} />

      <nav className="tabs" role="tablist" aria-label="Sections">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls="tab-panel"
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      <main className="content" id="tab-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {/* Keep the map mounted across tab switches; just hide it. */}
        <div hidden={tab !== 'route'}>
          <RouteTab
            map={
              <MapView
                hazards={hazards}
                shelters={shelters}
                route={route}
                location={location}
                onTap={setLocationAndRoute}
                focusKey={focusKey}
              />
            }
            location={location}
            route={route}
            routeError={routeError}
            shelters={shelters}
            onStartNavigation={() => setFocusKey(Date.now())}
          />
        </div>
        {tab === 'tips' && <TipsTab />}
        {tab === 'gov' && (
          <div className="gov">
            <p className="muted">No government updates yet. Updates sent by emergency officials will appear here.</p>
          </div>
        )}
      </main>

      <div className="action-bar">
        <button type="button" className="action" onClick={() => setSheetOpen(true)}>
          Report hazard
        </button>
        <button type="button" className="action action-safe" disabled={sending} onClick={() => sendReport('safe')}>
          I'm safe
        </button>
        <button type="button" className="action action-help" disabled={sending} onClick={() => sendReport('sos')}>
          Need help
        </button>
      </div>

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}

      {sheetOpen && (
        <ReportSheet
          sending={sending}
          onClose={() => setSheetOpen(false)}
          onSubmit={async ({ kind, note }) => {
            if (await sendReport(kind, note)) setSheetOpen(false)
            else if (!locationRef.current) setSheetOpen(false)
          }}
        />
      )}
    </div>
  )
}
