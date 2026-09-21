import type { Film, Image } from "@/lib/api"

/** `YYYY-MM-DD` exactly — a calendar date with no time and no zone. */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/**
 * `2024-07-01` → "1 Jul 2024", or `null` when there is nothing to show.
 *
 * A date-only value is a day in the archive's calendar, not an instant: parsing it
 * with `new Date` would read it as midnight UTC and show the day before anywhere
 * west of Greenwich. So the parts are handed to the local-time constructor instead.
 */
export function formatDate(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = DATE_ONLY.test(value)
    ? (() => {
        const [year, month, day] = value.split("-").map(Number)
        return new Date(year, month - 1, day)
      })()
    : new Date(withTimezone(value))
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString([], { dateStyle: "medium" })
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

/**
 * The backend writes naive UTC — `2024-07-01T14:03:11`, no `Z` and no offset — and
 * `new Date` reads an offset-less timestamp as *local* time. Marking it as UTC is
 * what makes the displayed time the reader's own.
 */
function withTimezone(value: string): string {
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`
}

/** "1 Jul 2024 14:03" for a timestamp, or null. */
export function formatDateTime(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = new Date(withTimezone(value))
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
}

/** What a frame is called in the UI: "Frame 12" or "Unnumbered". */
export function frameLabel(image: Pick<Image, "frame_number">): string {
  return image.frame_number === null || image.frame_number === undefined
    ? "Unnumbered"
    : `Frame ${image.frame_number}`
}

/**
 * "Rodinal 1+50 · +1 · 9:30" — how the roll was developed, in one line (M5).
 *
 * The dilution belongs to the developer, so those two are joined with a space;
 * the push and the time are separate facts. `null` when nothing is recorded, so
 * the caller can leave the line out entirely rather than print an empty label.
 */
export function developmentLine(
  film: Partial<Pick<Film, "developer" | "development_dilution" | "push_pull" | "development_time">>,
): string | null {
  const developer = [film.developer, film.development_dilution].filter(Boolean).join(" ")
  const parts = [developer, film.push_pull, film.development_time].filter(Boolean) as string[]
  return parts.length ? parts.join(" · ") : null
}

export function pluralize(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}
