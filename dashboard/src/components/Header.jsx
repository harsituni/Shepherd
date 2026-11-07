import { CrookIcon } from './icons.jsx'

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export default function Header({ mode, onModeChange, lastUpdated, connectionError, sampleData }) {
  let status
  if (connectionError) status = 'Backend unreachable · retrying'
  else if (lastUpdated) status = `Updated ${formatTime(lastUpdated)}${sampleData ? ' · sample data' : ''}`
  else status = 'Loading…'

  return (
    <header className="header">
      <div className="brand">
        <div className="brand-mark" style={{ color: 'var(--navy)' }}>
          <CrookIcon />
        </div>
        <div className="brand-text">
          <span className="brand-name">Shepherd</span>
          <span className="brand-sub">Disaster monitoring · Alberta</span>
        </div>
      </div>
      <div className="header-right">
        <div className="mode-switch" role="group" aria-label="Mode">
          {['live', 'drill'].map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => onModeChange(m)}
            >
              {m === 'live' ? 'Live' : 'Simulation'}
            </button>
          ))}
        </div>
        <span className="updated num" role="status">
          {status}
        </span>
      </div>
    </header>
  )
}
