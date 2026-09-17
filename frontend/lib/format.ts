import type { Film, Image } from "@/lib/api"

/** `2024-07-01` → a locale date, or `null` when there is nothing to show. */
export function formatDate(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString()
}

/** "1 Jul 2024 – 8 Jul 2024", a single date, or the em dash placeholder. */
export function formatDateRange(start: string | null, end: string | null): string {
  const from = formatDate(start)
  const to = formatDate(end)
  if (from && to) return from === to ? from : `${from} – ${to}`
  return from || to || "—"
}

/**
 * Where the roll is: the location path (M4), falling back to the pre-M4 free text
 * for an archive that has not filed its rolls yet. The serial is shown separately.
 */
export function formatStorage(
  film: Pick<Film, "building" | "folder" | "archive_serial"> & Partial<Pick<Film, "location_path">>,
): string {
  if (film.location_path) return film.location_path
  const parts = [film.building, film.folder].filter(Boolean) as string[]
  return parts.length ? parts.join(" · ") : "Not filed"
}

/** "Strip 3 · Pos 2" for a frame number given the strips, or null when it does not fit. */
export function stripPosition(frameNumber: number | null | undefined, strips: number[]): { strip: number; position: number } | null {
  if (frameNumber === null || frameNumber === undefined || frameNumber < 1) return null
  let remaining = frameNumber
  for (let index = 0; index < strips.length; index += 1) {
    if (remaining <= strips[index]) return { strip: index + 1, position: remaining }
    remaining -= strips[index]
  }
  return null
}

export function formatStripPosition(frameNumber: number | null | undefined, strips: number[]): string | null {
  const place = stripPosition(frameNumber, strips)
  return place ? `Strip ${place.strip} · Pos ${place.position}` : null
}

/** "1 Jul 2024 14:03" for a timestamp, or null. */
export function formatDateTime(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
}

/** What a frame is called in the UI: "Frame 12" or "Unnumbered". */
export function frameLabel(image: Pick<Image, "frame_number">): string {
  return image.frame_number === null || image.frame_number === undefined
    ? "Unnumbered"
    : `Frame ${image.frame_number}`
}

export function pluralize(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}
