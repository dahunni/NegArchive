// One place decides which origin a URL points at (R#2, R#3).
//
// - Server side (SSR, inside Docker): `API_BASE` reaches the backend service directly
//   (`http://web:8000`). Locally it falls back to `NEXT_PUBLIC_API_BASE`.
// - Browser: `NEXT_PUBLIC_API_BASE` is the absolute backend origin in local dev
//   (`http://localhost:8010`) and empty in Docker, so URLs stay same-origin and the
//   Next.js rewrites for `/api/*` and `/static/*` proxy them to the backend.
//
// Nothing outside this module may build an API or asset URL by hand.
const SERVER_API_BASE = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8010"
const PUBLIC_API_BASE = process.env.NEXT_PUBLIC_API_BASE || ""

/** Base for a fetch issued from wherever this code currently runs. */
function apiBase(): string {
  return typeof window === "undefined" ? SERVER_API_BASE : PUBLIC_API_BASE
}

/**
 * Absolute-or-same-origin URL for something the browser loads itself
 * (`<img src>`, download links). Always resolve backend paths through this.
 */
export function backendUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`
  return `${PUBLIC_API_BASE}${normalized}`
}

/**
 * What an upload may be, matching the backend's allowlist (M2, R#18). Anything else
 * is refused with a 415, so the file picker does not offer it in the first place.
 */
export const ACCEPTED_IMAGE_TYPES = ".jpg,.jpeg,.png,.tif,.tiff,.webp,.dng"

/** Catalog image URL for a camera, lens or filmstock; null when it has no image. */
export function getCatalogImageUrl(item: {
  url?: string | null
  image_path?: string | null
}): string | null {
  const path = item.url || item.image_path
  return path ? backendUrl(path) : null
}

export interface Film {
  id: number
  title: string
  /** M2: gear is referenced by id (R#14); the names below mirror the catalog entry. */
  camera_id: number | null
  lens_id: number | null
  film_stock_id: number | null
  /** The catalog entry's current name. Write `camera_id`; this follows it. */
  camera: string | null
  lens: string | null
  film_type: string | null
  /** One of `35mm`, `120`, `4x5`, `8x10`, `other`. */
  format: string | null
  notes: string | null
  building: string | null
  folder: string | null
  archive_serial: string | null
  start_date: string | null
  end_date: string | null
  created_at: string
  /** Number of scans in this roll (M1: the roll list avoids an N+1). */
  image_count: number
  /** First frame in display order, used as the row thumbnail. */
  cover_image_id: number | null
  /** Up to four leading frames, for the thumbnail strip on a roll row. */
  cover_image_ids: number[]
}

export interface Image {
  id: number
  film_roll_id: number | null
  type: "scan" | "contact_sheet"
  path: string
  url: string
  /** The name the scanner gave the file, kept by every upload path (M2, R#7). */
  original_filename: string | null
  /** `managed`: NegArchive owns the file and deletes it with the record. */
  storage_mode: "managed" | "linked"
  frame_number: number | null
  notes: string | null
  capture_date: string | null
  created_at: string
}

export interface Camera {
  id: number
  name: string
  mount: string | null
  image_path: string | null
  url?: string | null
  notes: string | null
}

export interface Lens {
  id: number
  name: string
  mount: string | null
  image_path: string | null
  url?: string | null
  notes: string | null
}

export interface Filmstock {
  id: number
  name: string
  manufacturer: string | null
  /** One of `35mm`, `120`, `4x5`, `8x10`, `other`. */
  format: string | null
  iso: number
  kind: string
  expired: boolean
  expiration_date: string | null
  image_path: string | null
  url?: string | null
}

/**
 * A 4xx from the API with its structured body:
 * `{"error": {"code": "duplicate_name", "message": "…", "field": "name"}}`.
 * Forms show `message` next to the field the API named instead of "Failed to save".
 */
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  /** The input this failure belongs to, as the API reported it (M2). */
  readonly field: string | null

  constructor(code: string, message: string, status: number, field: string | null = null) {
    super(message)
    this.name = "ApiError"
    this.code = code
    this.status = status
    this.field = field
  }
}

/**
 * Which form field an error code belongs to.
 *
 * M2 sends `field` in the body, which is what `fieldFor` prefers; this map stays as
 * the fallback for codes an older backend sends without one.
 */
export const ERROR_FIELDS: Record<string, string> = {
  invalid_title: "title",
  invalid_name: "name",
  duplicate_name: "name",
  invalid_date: "start_date",
  invalid_date_range: "end_date",
  invalid_kind: "kind",
  invalid_number: "iso",
  invalid_type: "type",
  invalid_choice: "format",
  unknown_roll: "film_roll_id",
  unknown_camera: "camera_id",
  unknown_lens: "lens_id",
  unknown_film_stock: "film_stock_id",
}

/** The form field to attach an error to, or null when it belongs to no single input. */
export function fieldFor(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  return error.field ?? ERROR_FIELDS[error.code] ?? null
}

/** The message to show the user for any thrown error. */
export function errorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}

/** Throw an ApiError carrying the server's message, or `fallback` if it sent none. */
async function assertOk(res: Response, fallback: string): Promise<void> {
  if (res.ok) return
  let code = "request_failed"
  let message = fallback
  let field: string | null = null
  try {
    const body = await res.json()
    if (body?.error && typeof body.error === "object") {
      code = body.error.code ?? code
      message = body.error.message ?? message
      field = body.error.field ?? null
    } else if (typeof body?.error === "string") {
      code = body.error
    }
  } catch {
    // no JSON body; keep the fallback message
  }
  throw new ApiError(code, message, res.status, field)
}

/** Unwrap `{ok, <key>}`. M2 answers a failure with a 4xx, so `assertOk` sees it first. */
function unwrap<T>(json: any, key: string, fallback: string): T {
  if (json && typeof json.error === "string") {
    throw new ApiError(json.error, fallback, 404)
  }
  return (json?.[key] ?? json) as T
}

/** `?keep_files=true` when the user asked to leave the files on disk (M2, R#9). */
function keepFilesQuery(keepFiles: boolean): string {
  return keepFiles ? "?keep_files=true" : ""
}

// Films API
export async function getFilms(): Promise<Film[]> {
  const res = await fetch(`${apiBase()}/api/films`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch films")
  return res.json()
}

export async function getFilm(id: number): Promise<{ film: Film; images: Image[]; contact_sheets: Image[] }> {
  const res = await fetch(`${apiBase()}/api/films/${id}`, { cache: "no-store" })
  // M2: a missing roll is a real 404 with a structured body (R#17).
  await assertOk(res, "Could not load the roll.")
  const json = await res.json()
  return { film: json.film, images: json.images ?? [], contact_sheets: json.contact_sheets ?? [] }
}

export async function createFilm(data: Partial<Film>): Promise<Film> {
  const res = await fetch(`${apiBase()}/api/films`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the roll.")
  const json = await res.json()
  return unwrap<Film>(json, "film", "Roll not found.")
}

export async function updateFilm(id: number, data: Partial<Film>): Promise<Film> {
  const res = await fetch(`${apiBase()}/api/films/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not save the roll.")
  const json = await res.json()
  return unwrap<Film>(json, "film", "Roll not found.")
}

/**
 * Delete a roll and its frame records. The scan files go with them unless
 * `keepFiles` is set — the "keep files on disk" checkbox in the delete dialog (R#9).
 */
export async function deleteFilm(id: number, keepFiles = false): Promise<void> {
  const res = await fetch(`${apiBase()}/api/films/${id}${keepFilesQuery(keepFiles)}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the roll.")
}

// Images API
export async function getImages(filmId?: number): Promise<Image[]> {
  const url = filmId
    ? `${apiBase()}/api/images?film_id=${filmId}&type=scan`
    : `${apiBase()}/api/images?type=scan`
  const res = await fetch(url, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch images")
  return res.json()
}

export async function getImage(id: number): Promise<Image> {
  const res = await fetch(`${apiBase()}/api/images/${id}`, { cache: "no-store" })
  await assertOk(res, "Could not load the frame.")
  return (await res.json()) as Image
}

export async function uploadImage(formData: FormData): Promise<Image> {
  const res = await fetch(`${apiBase()}/api/images/upload`, {
    method: "POST",
    body: formData,
  })
  await assertOk(res, "Could not upload the file.")
  const json = await res.json()
  return unwrap<Image>(json, "image", "Frame not found.")
}

// Bulk operations for film roll images
export async function createContactSheet(
  filmId: number,
  options?: { columns?: number; thumb_size?: number }
): Promise<Image> {
  const params = new URLSearchParams()
  if (options?.columns) params.set("columns", String(options.columns))
  if (options?.thumb_size) params.set("thumb_size", String(options.thumb_size))
  const res = await fetch(`${apiBase()}/api/films/${filmId}/contact_sheet?${params.toString()}`, {
    method: "POST",
  })
  await assertOk(res, "Could not generate the contact sheet.")
  const json = await res.json()
  return unwrap<Image>(json, "image", "Roll not found.")
}

export async function updateImage(id: number, data: Partial<Image>): Promise<Image> {
  const res = await fetch(`${apiBase()}/api/images/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not save the frame.")
  const json = await res.json()
  return unwrap<Image>(json, "image", "Frame not found.")
}

/** Delete a frame; its file goes too unless `keepFiles` is set (M2, R#9). */
export async function deleteImage(id: number, keepFiles = false): Promise<void> {
  const res = await fetch(`${apiBase()}/api/images/${id}${keepFilesQuery(keepFiles)}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the frame.")
}

// Cameras API
export async function getCameras(): Promise<Camera[]> {
  const res = await fetch(`${apiBase()}/api/cameras`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch cameras")
  return res.json()
}

export async function getCamera(id: number): Promise<Camera> {
  const res = await fetch(`${apiBase()}/api/cameras/${id}`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch camera")
  return res.json()
}

export async function createCamera(data: Partial<Camera>): Promise<Camera> {
  const res = await fetch(`${apiBase()}/api/cameras`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the camera.")
  const json = await res.json()
  return unwrap<Camera>(json, "camera", "Camera not found.")
}

export async function updateCamera(id: number, data: Partial<Camera>): Promise<Camera> {
  const res = await fetch(`${apiBase()}/api/cameras/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not save the camera.")
  const json = await res.json()
  return unwrap<Camera>(json, "camera", "Camera not found.")
}

/**
 * Delete a camera. The API answers 409 `gear_in_use` while rolls still refer to it
 * (R#14); pass `force` to delete it anyway — those rolls keep the name as text.
 */
export async function deleteCamera(id: number, force = false): Promise<void> {
  const res = await fetch(`${apiBase()}/api/cameras/${id}${force ? "?force=true" : ""}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the camera.")
}

export async function uploadCameraImage(id: number, file: File): Promise<Camera> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await fetch(`${apiBase()}/api/cameras/${id}/image`, {
    method: "POST",
    body: formData,
  })
  await assertOk(res, "Could not upload the camera image.")
  const json = await res.json()
  return unwrap<Camera>(json, "camera", "Camera not found.")
}

// Lenses API
export async function getLenses(): Promise<Lens[]> {
  const res = await fetch(`${apiBase()}/api/lenses`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch lenses")
  return res.json()
}

export async function getLens(id: number): Promise<Lens> {
  const res = await fetch(`${apiBase()}/api/lenses/${id}`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch lens")
  return res.json()
}

export async function createLens(data: Partial<Lens>): Promise<Lens> {
  const res = await fetch(`${apiBase()}/api/lenses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the lens.")
  const json = await res.json()
  return unwrap<Lens>(json, "lens", "Lens not found.")
}

export async function updateLens(id: number, data: Partial<Lens>): Promise<Lens> {
  const res = await fetch(`${apiBase()}/api/lenses/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not save the lens.")
  const json = await res.json()
  return unwrap<Lens>(json, "lens", "Lens not found.")
}

/** Delete a lens; 409 `gear_in_use` unless `force` (see {@link deleteCamera}). */
export async function deleteLens(id: number, force = false): Promise<void> {
  const res = await fetch(`${apiBase()}/api/lenses/${id}${force ? "?force=true" : ""}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the lens.")
}

export async function uploadLensImage(id: number, file: File): Promise<Lens> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await fetch(`${apiBase()}/api/lenses/${id}/image`, {
    method: "POST",
    body: formData,
  })
  await assertOk(res, "Could not upload the lens image.")
  const json = await res.json()
  return unwrap<Lens>(json, "lens", "Lens not found.")
}

// Filmstocks API
export async function getFilmstocks(): Promise<Filmstock[]> {
  const res = await fetch(`${apiBase()}/api/filmstocks`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch filmstocks")
  return res.json()
}

export async function getFilmstock(id: number): Promise<Filmstock> {
  const res = await fetch(`${apiBase()}/api/filmstocks/${id}`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch filmstock")
  return res.json()
}

export async function createFilmstock(data: Partial<Filmstock>): Promise<Filmstock> {
  const res = await fetch(`${apiBase()}/api/filmstocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the film stock.")
  const json = await res.json()
  return unwrap<Filmstock>(json, "filmstock", "Filmstock not found.")
}

export async function updateFilmstock(id: number, data: Partial<Filmstock>): Promise<Filmstock> {
  const res = await fetch(`${apiBase()}/api/filmstocks/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not save the film stock.")
  const json = await res.json()
  return unwrap<Filmstock>(json, "filmstock", "Filmstock not found.")
}

/** Delete a film stock; 409 `gear_in_use` unless `force` (see {@link deleteCamera}). */
export async function deleteFilmstock(id: number, force = false): Promise<void> {
  const res = await fetch(`${apiBase()}/api/filmstocks/${id}${force ? "?force=true" : ""}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the film stock.")
}

export async function uploadFilmstockImage(id: number, file: File): Promise<Filmstock> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await fetch(`${apiBase()}/api/filmstocks/${id}/image`, {
    method: "POST",
    body: formData,
  })
  await assertOk(res, "Could not upload the film stock image.")
  const json = await res.json()
  return unwrap<Filmstock>(json, "filmstock", "Filmstock not found.")
}

/** Partial patch applied to many frames at once (multi-select in the roll workspace). */
export interface BulkImagePatch {
  film_roll_id?: number | null
  capture_date?: string | null
  frame_number?: number | null
}

export async function bulkUpdateImages(ids: number[], patch: BulkImagePatch): Promise<Image[]> {
  const res = await fetch(`${apiBase()}/api/images/bulk_update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, ...patch }),
  })
  await assertOk(res, "Could not update the selected frames.")
  const json = await res.json()
  return (json?.images ?? []) as Image[]
}

export async function bulkDeleteImages(ids: number[], keepFiles = false): Promise<number> {
  const res = await fetch(`${apiBase()}/api/images/bulk_delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, keep_files: keepFiles }),
  })
  await assertOk(res, "Could not delete the selected frames.")
  const json = await res.json()
  return Number(json?.deleted ?? 0)
}

/**
 * Preview URL at a given width. The backend caches each width on disk, so grids
 * ask for small thumbnails and the viewer for a large one.
 */
export function getPreviewUrl(imageId: number, width: number): string {
  return backendUrl(`/api/images/${imageId}/preview?width=${width}`)
}

export function getImageUrl(image: Image): string {
  // Always serve via preview to ensure browser-friendly format (handles TIFF/JPEG/PNG uniformly)
  return backendUrl(`/api/images/${image.id}/preview`)
}

export function getImageDownloadUrl(image: Image): string {
  // Download original asset via API to enforce Content-Disposition
  return backendUrl(`/api/images/${image.id}/download`)
}

/**
 * One upload with a progress callback. `fetch` cannot report upload progress, so the
 * drop zone uses XMLHttpRequest for this and this alone; the URL still comes from
 * `backendUrl`, so the `/api` rewrite is the only path to the backend.
 */
function uploadWithProgress(
  path: string,
  formData: FormData,
  onProgress: (fraction: number) => void,
): Promise<{ images: Image[] }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", backendUrl(path))
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    xhr.onerror = () => reject(new ApiError("network_error", "The upload could not reach the server.", 0))
    xhr.onabort = () => reject(new ApiError("aborted", "The upload was cancelled.", 0))
    xhr.onload = () => {
      let body: any = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        // fall through to the status check
      }
      if (xhr.status >= 400 || (body && typeof body.error === "string")) {
        const structured = body?.error && typeof body.error === "object" ? body.error : null
        reject(
          new ApiError(
            structured?.code ?? (typeof body?.error === "string" ? body.error : "upload_failed"),
            structured?.message ?? "The server rejected this file.",
            xhr.status,
          ),
        )
        return
      }
      onProgress(1)
      const images: Image[] = body?.images ?? (body?.image ? [body.image] : [])
      resolve({ images })
    }
    xhr.send(formData)
  })
}

/** Upload one scan into a roll, reporting progress. ZIPs go through the ZIP importer. */
export function uploadRollFile(
  filmId: number,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<{ images: Image[] }> {
  const isZip = file.name.toLowerCase().endsWith(".zip") || file.type === "application/zip"
  const formData = new FormData()
  if (isZip) {
    formData.append("file", file)
    return uploadWithProgress(`/api/films/${filmId}/images/bulk_zip`, formData, onProgress)
  }
  formData.append("files", file)
  return uploadWithProgress(`/api/films/${filmId}/images/bulk`, formData, onProgress)
}

/** Upload one scan that does not belong to a roll yet. */
export function uploadLooseFile(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<{ images: Image[] }> {
  const formData = new FormData()
  formData.append("file", file)
  formData.append("type", "scan")
  return uploadWithProgress("/api/images/upload", formData, onProgress)
}

/** Upload a scanned contact sheet (a single image) for a roll. */
export function uploadContactSheetFile(
  filmId: number,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<{ images: Image[] }> {
  const formData = new FormData()
  formData.append("file", file)
  formData.append("type", "contact_sheet")
  formData.append("film_roll_id", String(filmId))
  return uploadWithProgress("/api/images/upload", formData, onProgress)
}
