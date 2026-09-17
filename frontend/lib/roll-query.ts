import type { FilmQuery } from "@/lib/api"

/**
 * The roll list's filters, as they appear in the URL (roadmap M3, R#20).
 *
 * They live in the query string rather than in React state alone so a filtered
 * list is a link: `"/?q=harbour&camera=Nikon F5"` can be bookmarked, sent to
 * somebody, or — once M4 prints labels — encoded in a QR code on a binder.
 *
 * The names are the UI's (`film`, because the filter is labelled "Film"); the
 * API's are the column names (`film_type`). This is the one place they meet.
 */
export type RollSearchParams = {
  q?: string
  camera?: string
  film?: string
  from?: string
  to?: string
  new?: string
}

/** A numeric parameter is a catalog id; anything else is a legacy name (M2, R#14). */
function gear(raw: string | undefined): { id?: number; name?: string } {
  if (!raw) return {}
  return /^\d+$/.test(raw) ? { id: Number(raw) } : { name: raw }
}

export function queryFromSearchParams(params: RollSearchParams): FilmQuery {
  const camera = gear(params.camera)
  const film = gear(params.film)
  return {
    q: params.q || undefined,
    // The API takes either, so a bookmark from before M2 — which carried the
    // camera's *name* — still renders the right first page.
    camera_id: camera.id,
    camera: camera.name,
    film_stock_id: film.id,
    film_type: film.name,
    from: params.from || undefined,
    to: params.to || undefined,
  }
}
