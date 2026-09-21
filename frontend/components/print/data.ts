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

/**
 * One image per frame number, preferring the exported positive.
 *
 * A roll scanned through NegPy holds two files per frame: the raw negative off
 * the scanner and the positive NegPy exported from it. Paper wants the positive
 * — an index card of orange negatives tells you nothing about the roll — and it
 * wants 36 thumbnails to mean 36 frames, not the first 18 twice. Between two
 * positives the newest export wins; with no positive at all the first frame in
 * display order stands, exactly as before. The backend applies the same rule to
 * the sleeve grid (`app/services/strips.py`, `better_for_paper`) and to the roll
 * list's cover strip, so every surface shows the same picture of a frame.
 */
export function onePerFrame(frames: Image[]): Image[] {
  const best = new Map<number | string, Image>()
  frames.forEach((frame, index) => {
    // An unnumbered frame is its own candidate, never a rival of another.
    const key = frame.frame_number ?? `unnumbered-${index}`
    const current = best.get(key)
    if (!current) {
      best.set(key, frame)
      return
    }
    const mine = Boolean(current.positive)
    const theirs = Boolean(frame.positive)
    if (mine !== theirs ? theirs : theirs && frame.id > current.id) best.set(key, frame)
  })
  return [...best.values()].sort(
    (a, b) => (a.frame_number ?? Infinity) - (b.frame_number ?? Infinity) || a.id - b.id,
  )
}

export async function loadRolls(ids: number[]): Promise<RollBundle[]> {
  const bundles = await Promise.all(
    ids.map(async (id) => {
      try {
        const [detail, layout] = await Promise.all([getFilm(id), getRollLayout(id)])
        return { film: detail.film, frames: onePerFrame(detail.images), layout }
      } catch {
        return null
      }
    }),
  )
  return bundles.filter((b): b is RollBundle => b !== null)
}

export { getAllFilms, getLocations }
