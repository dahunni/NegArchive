import {
  type Film,
  type Image,
  type Location,
  type RollLayout,
  barcodeUrl,
  getAllFilms,
  getFilm,
  getLocations,
  getRollLayout,
  getSettings,
  getSystemInfo,
  qrUrl,
} from "@/lib/api"

/** Where printed QR codes point: the setting, else the LAN address the backend found. */
export async function publicBase(): Promise<string> {
  const [settings, info] = await Promise.all([getSettings().catch(() => null), getSystemInfo().catch(() => null)])
  return (settings?.settings.public_base_url || info?.ui_url || "").replace(/\/$/, "")
}

export function rollCodes(base: string, film: Film) {
  const serial = film.archive_serial ?? `ROLL-${film.id}`
  return { qr: qrUrl(`${base}/s/${serial}`, 3), barcode: barcodeUrl(serial, 12), serial }
}

export function locationCodes(base: string, node: Location) {
  return { qr: qrUrl(`${base}/l/${node.id}`, 3), barcode: barcodeUrl(`LOC-${node.id}`, 12) }
}

/** Parse `?ids=1,2,3` into numbers. */
export function idsFromParam(raw: string | string[] | undefined): number[] {
  const text = Array.isArray(raw) ? raw.join(",") : raw ?? ""
  return text
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((n) => Number.isFinite(n) && n > 0)
}

export interface RollBundle {
  film: Film
  frames: Image[]
  layout: RollLayout
}

export async function loadRolls(ids: number[]): Promise<RollBundle[]> {
  const bundles = await Promise.all(
    ids.map(async (id) => {
      try {
        const [detail, layout] = await Promise.all([getFilm(id), getRollLayout(id)])
        return { film: detail.film, frames: detail.images, layout }
      } catch {
        return null
      }
    }),
  )
  return bundles.filter((b): b is RollBundle => b !== null)
}

export { getAllFilms, getLocations }
