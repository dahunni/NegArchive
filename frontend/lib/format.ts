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

/** "Archive A · 2024-Q2 · NEG-2024-001", skipping the parts that are empty. */
export function formatStorage(film: Pick<Film, "building" | "folder" | "archive_serial">): string {
  const parts = [film.building, film.folder, film.archive_serial].filter(Boolean) as string[]
  return parts.length ? parts.join(" · ") : "—"
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
