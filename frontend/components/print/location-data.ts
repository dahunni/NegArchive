import { type Film, type Location, type LocationDetail, getAllFilms, getLocation, getLocations } from "@/lib/api"

export async function loadLocationBundle(id: number): Promise<{ detail: LocationDetail; all: Location[]; films: Film[] } | null> {
  try {
    const [detail, all, films] = await Promise.all([getLocation(id), getLocations(), getAllFilms()])
    return { detail, all, films }
  } catch {
    return null
  }
}

/** Every roll filed anywhere under a node, in page order where the node is a binder. */
export function rollsUnder(node: Location, all: Location[], films: Film[]): Film[] {
  const under = new Set(all.filter((n) => n.id === node.id || n.path_ids.includes(node.id)).map((n) => n.id))
  const order = new Map(all.map((n) => [n.id, n.sort_order]))
  return films
    .filter((f) => f.location_id !== null && under.has(f.location_id))
    .sort((a, b) => (order.get(a.location_id!) ?? 0) - (order.get(b.location_id!) ?? 0) || (a.archive_serial ?? "").localeCompare(b.archive_serial ?? ""))
}

export function yearRange(films: Film[]): string {
  const years = films
    .map((f) => (f.start_date ?? f.end_date ?? "").slice(0, 4))
    .filter((y) => /^\d{4}$/.test(y))
    .sort()
  if (years.length === 0) return "—"
  return years[0] === years[years.length - 1] ? years[0] : `${years[0]}–${years[years.length - 1]}`
}

export function serialRange(films: Film[]): string {
  const serials = films.map((f) => f.archive_serial).filter((s): s is string => Boolean(s)).sort()
  if (serials.length === 0) return "—"
  return serials.length === 1 ? serials[0] : `${serials[0]} … ${serials[serials.length - 1]}`
}
