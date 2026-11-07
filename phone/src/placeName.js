// Name of the area the map is showing, for the header ("Alberta", "Edmonton",
// "Rural South East"...). Uses OpenStreetMap's Nominatim reverse geocoder, the
// same data as the basemap. Nominatim allows ~1 request/second, so callers
// debounce and results are cached.

// Map zoom → how detailed a place to ask for (Nominatim zoom levels:
// 3 country, 5 state/province, 8 county, 10 city, 12 district, 14 neighbourhood).
function detailFor(zoom) {
  if (zoom < 4) return 3
  if (zoom < 7) return 5
  if (zoom < 9.5) return 8
  if (zoom < 12) return 10
  if (zoom < 14) return 12
  return 14
}

// Address fields to try at each level, most specific first.
const TOWN = ['city', 'town', 'village', 'municipality', 'county', 'state']
const FIELDS = {
  3: ['country'],
  5: ['state', 'province', 'country'],
  8: ['county', 'municipality', 'city', 'town', 'state_district', 'state'],
  10: TOWN,
  // Edmonton's districts ("Rural South East", "Greater Strathcona") are `suburb`.
  12: ['suburb', 'city_district', 'quarter', 'hamlet', ...TOWN],
  14: ['neighbourhood', 'suburb', 'quarter', 'city_district', 'hamlet', ...TOWN],
}

// Census divisions ("Division No. 11") mean nothing to residents; skip them.
const useless = (name) => !name || /^Division No\.?\s*\d+/i.test(name)

function pickName(data, detail) {
  const a = data.address ?? {}
  for (const f of FIELDS[detail]) if (!useless(a[f])) return a[f]
  return useless(data.name) ? null : data.name
}

const cache = new Map()

// Resolves to a place name, or null if nothing useful came back.
export async function placeName([lon, lat], zoom, signal) {
  const detail = detailFor(zoom)
  // Coarser rounding for coarser levels so small pans reuse the cached answer.
  const step = detail <= 5 ? 1 : detail <= 10 ? 0.05 : 0.005
  const key = `${detail}:${Math.round(lat / step)}:${Math.round(lon / step)}`
  if (cache.has(key)) return cache.get(key)

  const url =
    `https://nominatim.openstreetmap.org/reverse?format=jsonv2&addressdetails=1` +
    `&zoom=${detail}&lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}&accept-language=en`
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`nominatim ${res.status}`)
  const name = pickName(await res.json(), detail)
  cache.set(key, name)
  return name
}
