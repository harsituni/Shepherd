import { ReportKindIcon, reportLabel } from '../reportKinds.jsx'

// Newest first: highest sim_time, then highest id number as a tie-break.
function sortedReports(reports) {
  const idNum = (f) => Number(String(f.id ?? '').replace(/\D/g, '')) || 0
  return [...(reports?.features ?? [])].sort(
    (a, b) => (b.properties?.sim_time ?? 0) - (a.properties?.sim_time ?? 0) || idNum(b) - idNum(a),
  )
}

export default function ReportsList({ reports, onSelect }) {
  const items = sortedReports(reports)
  if (items.length === 0) return <p className="empty">No reports from phones yet.</p>
  return (
    <ul className="report-list">
      {items.map((f) => {
        const { kind, note, sim_time: t } = f.properties ?? {}
        const [lon, lat] = f.geometry.coordinates
        return (
          <li key={f.id}>
            <button type="button" className="report-item" onClick={() => onSelect(f)}>
              <span className="report-row">
                <strong className={kind === 'sos' ? 'report-kind sos' : 'report-kind'}>
                  <ReportKindIcon kind={kind} />
                  {reportLabel(kind)}
                </strong>
                <span className="num report-time">{t == null ? '' : `T+${t}`}</span>
              </span>
              {note && <span className="report-note">{note}</span>}
              <span className="num report-loc">
                {lat.toFixed(3)}, {lon.toFixed(3)}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
