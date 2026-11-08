import { useLayoutEffect, useRef, useState } from 'react'
import { AlertsTab } from './Notifications.jsx'
import { BellIcon, CheckIcon, ChevronUpIcon, CloseIcon, CrookIcon, InfoIcon, WarningIcon } from './icons.jsx'

// The phone app's one screen, map-first (modelled on scooter apps like Lime and
// Bird): the map fills the screen and everything else floats over it.
//   top left    area chip (Shepherd mark + place name)
//   top right   compact alert / evacuation card; tap it for the details
//   right rail  Alerts, Map key, Report, I'm safe (just above the route panel)
//   bottom      route panel: shelter cards you swipe sideways + Start evacuating,
//               closable to a one-line strip; full-width Need help bar under it
//
// Props:
//   renderMap(framePadding)  the live MapView, told what the floating chrome covers
//   alert                    <EvacCard/> or <AlertBanner/>
//   details                  <RouteDetails/> for the current state
//   more                     <RouteMore/>: extra detail you scroll the panel down to
//   mapKey                   <MapKey/>
//   areaName, notifications, location, route, routeError, trip, version
//   actions: { report, safe, help, canReport, sending }

// Map padding (px) roughly matching the floating chrome, so "frame my route"
// keeps the route clear of the top cards, the rail and the route panel.
const FRAME_PADDING = { top: 90, bottom: 260, right: 84 }

// A simple modal bottom sheet (same scrim/sheet styles as the report sheet).
function Sheet({ title, onClose, children }) {
  return (
    <div className="sheet-scrim" onClick={onClose}>
      <div className="sheet ms-modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
        <div className="ms-modal-body">{children}</div>
      </div>
    </div>
  )
}

// The alert / evacuation card, compact in the top-right corner: just its headline.
// Tapping it opens it to full width with the detail lines.
function CornerAlert({ children }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={open ? 'ms-alert is-open' : 'ms-alert'}>
      {children}
      <button
        type="button"
        className="ms-alert-toggle"
        aria-expanded={open}
        aria-label={open ? 'Hide alert details' : 'Show alert details'}
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronUpIcon />
      </button>
    </div>
  )
}

// The open route panel. It opens at the height of its main content (the cards,
// drive mode, Start evacuating), so it looks the same as before; the "Route
// details" heading just peeks under it, and the extra detail is a scroll away.
// Reopening it from the strip slides it up from the bottom.
function RoutePanel({ details, more, shared, slideIn, onClose }) {
  const mainRef = useRef(null)
  const [mainH, setMainH] = useState(null)
  useLayoutEffect(() => {
    const el = mainRef.current
    if (!el) return undefined
    const measure = () => setMainH(el.offsetHeight)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return (
    <section className={slideIn ? 'ms-panel is-sliding' : 'ms-panel'} aria-label="Your route">
      {/* Floats just above the panel's corner (the rail is hidden while open). */}
      <button type="button" className="ms-panel-close" aria-label="Close route panel" onClick={onClose}>
        <CloseIcon />
      </button>
      <div className="ms-panel-scroll" style={more && mainH != null ? { '--main-h': `${mainH}px` } : undefined}>
        <div className="ms-panel-main" ref={mainRef}>
          {details}
          {shared && <p className="ms-shared">Your location is shared with responders.</p>}
        </div>
        {more}
      </div>
    </section>
  )
}

// One-line summary of where you stand, for the closed route panel.
function routeSummary({ location, route, routeError, trip }) {
  if (trip) return { title: 'Evacuating', line: route?.shelter_name ?? 'Following your route' }
  if (!location) return { title: 'Tap the map where you are', line: 'Shepherd finds the safest open shelter' }
  if (routeError === 'no_route') return { title: 'No safe route found', line: 'Call 911', urgent: true }
  // Keep showing the last good route while a poll is retrying (slow /route).
  if (routeError && !route) return { title: "Can't route right now", line: 'Retrying…' }
  if (!route) return { title: 'Finding your route…', line: '' }
  return {
    title: route.shelter_name,
    line: route.eta_min != null ? `${route.eta_min} min · ${Number(route.distance_km).toFixed(1)} km` : '',
  }
}

export default function MapScreen({
  renderMap,
  alert,
  details,
  more,
  mapKey,
  areaName,
  notifications,
  location,
  route,
  routeError,
  trip,
  version,
  actions,
}) {
  const [sheet, setSheet] = useState(null) // 'alerts' | 'key' | null
  // The route panel opens for each new location; closing it applies to that one.
  const here = location ? location.join(',') : 'none'
  const [closedFor, setClosedFor] = useState(null)
  // Slide up only when the person reopens the panel from the strip.
  const [slideIn, setSlideIn] = useState(false)
  const panelOpen = closedFor !== here
  const sum = routeSummary({ location, route, routeError, trip })

  return (
    <div className="ms">
      {renderMap(FRAME_PADDING)}

      <div className="ms-top">
        <div className="ms-chip">
          <span className="brand-mark" aria-hidden="true">
            <CrookIcon />
          </span>
          <span className="ms-area" title={areaName}>
            {areaName}
          </span>
        </div>
        <CornerAlert>{alert}</CornerAlert>
      </div>

      <div className="ms-bottom">
        {/* The rail steps aside while the route panel is open, so the panel isn't crowded. */}
        <div className="ms-rail" hidden={panelOpen}>
          <button type="button" className="ms-fab" aria-label={`Official alerts (${notifications.length})`} onClick={() => setSheet('alerts')}>
            <BellIcon />
            <span>Alerts</span>
            {notifications.length > 0 && <span className="ms-badge num">{notifications.length}</span>}
          </button>
          <button type="button" className="ms-fab" onClick={() => setSheet('key')}>
            <InfoIcon />
            <span>Key</span>
          </button>
          <button type="button" className="ms-fab" disabled={!actions.canReport} onClick={actions.report}>
            <WarningIcon />
            <span>Report</span>
          </button>
          <button type="button" className="ms-fab" disabled={!actions.canReport} onClick={actions.safe}>
            <CheckIcon />
            <span>Safe</span>
          </button>
        </div>

        {panelOpen ? (
          <RoutePanel
            details={details}
            more={more}
            shared={Boolean(location)}
            slideIn={slideIn}
            onClose={() => {
              setSlideIn(false)
              setClosedFor(here)
            }}
          />
        ) : (
          <button type="button" className={sum.urgent ? 'ms-strip is-urgent' : 'ms-strip'} aria-label={`Show route: ${sum.title}`} onClick={() => {
              setSlideIn(true)
              setClosedFor(null)
            }}>
            <span className="ms-strip-text">
              <strong>{sum.title}</strong>
              {sum.line && <span className="num">{sum.line}</span>}
            </span>
            <ChevronUpIcon />
          </button>
        )}

        <button type="button" className="ms-help" disabled={actions.sending} onClick={actions.help}>
          Need help
        </button>
      </div>

      {sheet === 'alerts' && (
        <Sheet title="Official alerts" onClose={() => setSheet(null)}>
          <AlertsTab notifications={notifications} />
          <p className="ms-version num" title="Git revision for this UI build">
            {version}
          </p>
        </Sheet>
      )}
      {sheet === 'key' && (
        <Sheet title="Map key" onClose={() => setSheet(null)}>
          {mapKey}
        </Sheet>
      )}
    </div>
  )
}
