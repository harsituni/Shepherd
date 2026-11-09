// One symbol per public report kind, drawn as 24×24 stroke paths (same weight as
// icons.jsx). Shared by the map markers (DOM) and the report sheet's type tiles,
// so what you pick in the sheet is what everyone sees on the map.
// Keep in step with dashboard/src/reportKinds.jsx (the Reports list uses the same symbols).
//
// Each kind has its own colour, set by the `rk-<kind>` class (index.css):
// fire = hazard orange, blocked road = yellow (a yellow barrier with a deep-yellow
// outline), other = a black caution sign.
// A part is a path `d`, or { d, fill: true } for a shape filled with the kind's fill.

export const REPORT_KINDS = {
  fire: {
    label: 'Fire',
    seen: 'Fire reported',
    paths: ['M12 3c.6 3.2 4.5 5.2 4.5 9.5a4.5 4.5 0 0 1-9 0c0-2.3 1.2-3.8 2.2-4.8.3 1.6 1.1 2.5 2.1 2.8-.5-2.8-.6-5.2.2-7.5z'],
  },
  blocked_road: {
    label: 'Blocked road',
    seen: 'Blocked road reported',
    paths: [{ d: 'M3.5 7.5h17v6.5h-17z', fill: true }, 'M8.5 7.5l-3 6.5M14 7.5l-3 6.5M19.5 7.5l-3 6.5', 'M6.5 14v5.5M17.5 14v5.5'],
  },
  other: {
    label: 'Other',
    seen: 'Hazard reported',
    paths: ['M12 3 2 20h20L12 3z', 'M12 10v4', 'M12 17h.01'],
  },
}

export const REPORT_KIND_ORDER = ['fire', 'blocked_road', 'other']

export const kindOf = (kind) => (REPORT_KINDS[kind] ? kind : 'other')
export const partsOf = (kind) =>
  REPORT_KINDS[kindOf(kind)].paths.map((p) => (typeof p === 'string' ? { d: p, fill: false } : p))

const SVG_NS = 'http://www.w3.org/2000/svg'

// An <svg> element for map markers (MapLibre markers are plain DOM, not React).
export function reportSvg(kind, size = 16) {
  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('width', String(size))
  svg.setAttribute('height', String(size))
  svg.setAttribute('fill', 'none')
  svg.setAttribute('stroke', 'currentColor')
  svg.setAttribute('stroke-width', '2')
  svg.setAttribute('stroke-linecap', 'round')
  svg.setAttribute('stroke-linejoin', 'round')
  svg.setAttribute('aria-hidden', 'true')
  svg.setAttribute('class', `rk rk-${kindOf(kind)}`)
  for (const { d, fill } of partsOf(kind)) {
    const path = document.createElementNS(SVG_NS, 'path')
    path.setAttribute('d', d)
    if (fill) path.setAttribute('class', 'rk-fill')
    svg.appendChild(path)
  }
  return svg
}
