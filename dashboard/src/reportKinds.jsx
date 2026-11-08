// Report symbols for the Reports list: the same 24×24 stroke symbols and colours the
// phone uses on its map and report sheet. Keep in step with phone/src/reportKinds.js.
// SOS and "I'm safe" are responder-only kinds, so only the dashboard draws them.
// Colours come from the `rk-<kind>` classes in index.css.

export const REPORT_KINDS = {
  fire: {
    label: 'Fire',
    paths: ['M12 3c.6 3.2 4.5 5.2 4.5 9.5a4.5 4.5 0 0 1-9 0c0-2.3 1.2-3.8 2.2-4.8.3 1.6 1.1 2.5 2.1 2.8-.5-2.8-.6-5.2.2-7.5z'],
  },
  flooded_road: {
    label: 'Flooded road',
    paths: ['M3 9.5c1.5-1.2 3-1.2 4.5 0s3 1.2 4.5 0 3-1.2 4.5 0 3 1.2 4.5 0', 'M3 15c1.5-1.2 3-1.2 4.5 0s3 1.2 4.5 0 3-1.2 4.5 0 3 1.2 4.5 0'],
  },
  blocked_road: {
    label: 'Blocked road',
    paths: [{ d: 'M3.5 7.5h17v6.5h-17z', fill: true }, 'M8.5 7.5l-3 6.5M14 7.5l-3 6.5M19.5 7.5l-3 6.5', 'M6.5 14v5.5M17.5 14v5.5'],
  },
  other: {
    label: 'Other',
    paths: ['M12 3 2 20h20L12 3z', 'M12 10v4', 'M12 17h.01'],
  },
  sos: {
    label: 'SOS',
    paths: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 7.5v5.5', 'M12 16.5h.01'],
  },
  safe: {
    label: "I'm safe",
    paths: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'm8 12.3 2.8 2.7L16 9.5'],
  },
}

export const kindOf = (kind) => (REPORT_KINDS[kind] ? kind : 'other')
export const reportLabel = (kind) => REPORT_KINDS[kind]?.label ?? kind
const partsOf = (kind) =>
  REPORT_KINDS[kindOf(kind)].paths.map((p) => (typeof p === 'string' ? { d: p, fill: false } : p))

// The same symbol as a plain <svg> element, for MapLibre markers (not React).
const SVG_NS = 'http://www.w3.org/2000/svg'
export function reportSvg(kind, size = 16) {
  const svg = document.createElementNS(SVG_NS, 'svg')
  for (const [k, v] of Object.entries({
    viewBox: '0 0 24 24',
    width: size,
    height: size,
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': 2,
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': 'true',
    class: `rk rk-${kindOf(kind)}`,
  }))
    svg.setAttribute(k, String(v))
  for (const { d, fill } of partsOf(kind)) {
    const path = document.createElementNS(SVG_NS, 'path')
    path.setAttribute('d', d)
    if (fill) path.setAttribute('class', 'rk-fill')
    svg.appendChild(path)
  }
  return svg
}

export function ReportKindIcon({ kind, size = 20 }) {
  const k = kindOf(kind)
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`rk rk-${k}`}
    >
      {partsOf(k).map(({ d, fill }) => (
        <path key={d} d={d} className={fill ? 'rk-fill' : undefined} />
      ))}
    </svg>
  )
}
