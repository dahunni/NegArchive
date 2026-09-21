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
 * Name of the cookie the optional shared password (M3, R#26) sets. It is not
 * `httpOnly`, because the upload XHR and the service worker need to read it.
 */
export const TOKEN_COOKIE = "negarchive_token"

/** The session token this browser holds, or null. */
export function readTokenCookie(): string | null {
  if (typeof document === "undefined") return null
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${TOKEN_COOKIE}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * The token for whichever side is calling.
 *
 * In the browser it comes from the cookie. **Server-side it comes from the
 * request's own cookies**: the page is same-origin with the API proxy, so the
 * browser sends the cookie with the page request and the server component can
 * forward it. Without this, a signed-in visitor would still get a 401 for every
 * server-rendered page.
 */
async function sessionToken(): Promise<string | null> {
  if (typeof window !== "undefined") return readTokenCookie()
  try {
    const { cookies } = await import("next/headers")
    const store = await cookies()
    return store.get(TOKEN_COOKIE)?.value ?? null
  } catch {
    // No request context (a build-time prerender, say) — nothing to forward.
    return null
  }
}

/**
 * Every request to the backend goes through here: it picks the right base for
 * this side of the wire and attaches the session token when there is one.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = await sessionToken()
  if (token) headers.set("Authorization", `Bearer ${token}`)
  return fetch(`${apiBase()}${path}`, { cache: "no-store", ...init, headers })
}

/** A page of results: what the API returns when `limit` is given (M3, R#20). */
export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
  has_more: boolean
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
 * The second line is the camera raws NegPy's scan mode produces (M6.1); keep it in
 * step with `RAW_EXTENSIONS` in app/services/rawdecode.py.
 */
export const ACCEPTED_IMAGE_TYPES =
  ".jpg,.jpeg,.png,.tif,.tiff,.webp,.dng," +
  ".arw,.sr2,.srf,.nef,.nrw,.cr2,.cr3,.crw,.raf,.orf,.rw2,.rwl,.raw,.pef,.srw," +
  ".3fr,.fff,.iiq,.mef,.mos,.mrw,.dcr,.kdc,.erf,.x3f"

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
  /** M5: how the roll was developed — free text, filled from NegPy's XMP when it says so. */
  developer: string | null
  development_dilution: string | null
  push_pull: string | null
  development_time: string | null
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
  /** One `preview_version` per cover id (thumbnails are served immutable). */
  cover_versions?: string[]
  // --- M4: where the negatives are, and where the roll is in its life ---
  location_id: number | null
  /** "Archive A / Shelf 2 / B03 · Binder 3 / P12 · Page 12", derived by the API. */
  location_path: string | null
  location_kind: string | null
  /** The roll's own strip lengths, or null to use the sleeve layout. */
  strips: number[] | null
  /** The strips actually in effect (own, layout, or PrintFile 7 × 6). */
  effective_strips: number[]
  status: RollStatus
  status_label: string | null
  loaded_at: string | null
  shot_at: string | null
  lab_sent_at: string | null
  lab_back_at: string | null
  scanned_at: string | null
  sleeved_at: string | null
  loaded_camera_id: number | null
  label_printed_at: string | null
  needs_label: boolean
}

export type RollStatus = "loaded" | "shot" | "at_lab" | "back" | "scanned" | "sleeved"

export interface Image {
  id: number
  film_roll_id: number | null
  type: "scan" | "contact_sheet"
  path: string
  url: string
  /** The name the scanner gave the file, kept by every upload path (M2, R#7). */
  original_filename: string | null
  /**
   * `managed`: NegArchive owns the file and deletes it with the record.
   * `linked`: the file lives in a folder you manage and is never written to or
   * removed (M3, import by reference).
   */
  storage_mode: "managed" | "linked"
  /** M3: absolute path of a linked original; null for managed files. */
  source_path?: string | null
  /** M3: sampled SHA-256, used to spot a file that moved or is already imported. */
  content_hash?: string | null
  frame_number: number | null
  notes: string | null
  capture_date: string | null
  /**
   * M5: what the file itself said when it was ingested — EXIF, the `negpy:` XMP
   * namespace, the filename preset. Evidence, not authority: ingest only ever
   * fills a field that was empty.
   */
  capture_metadata?: CaptureMetadata | null
  /** The `.negpy` sidecar beside this file, when NegPy has edited it. */
  sidecar_path?: string | null
  negpy_edited_at?: string | null
  negpy_recipe?: NegpyRecipe | null
  /** One line describing the recipe, e.g. "12 settings · inverted · cropped". */
  negpy_summary?: string | null
  /** M5: how much of that recipe the positive preview can render, and what it cannot. */
  negpy_render?: {
    applied: string[]
    ignored: string[]
    applied_count: number
    ignored_count: number
    total: number
    summary: string
  } | null
  /**
   * M6.1: `true` — already a positive (a NegPy export, a scan of a print), shown as
   * it is and never printed; `false` — a negative even if the film is unknown;
   * `null` — decide from the roll's film stock, as before.
   */
  positive?: boolean | null
  /**
   * M6.1: a short token the backend changes whenever the file, its `.negpy`
   * sidecar or `positive` changes. Previews are served immutable, so this is what
   * busts their URL.
   */
  preview_version?: string | null
  created_at: string
}

export interface CaptureMetadata {
  roll: string | null
  frame_number: number | null
  capture_date: string | null
  camera: string | null
  lens: string | null
  film_stock: string | null
  film_manufacturer: string | null
  film_iso: number | null
  developer: string | null
  development: string | null
  notes: string | null
  /** Which of `xmp`, `exif`, `filename` contributed. */
  sources: string[]
  raw?: Record<string, unknown>
}

export interface NegpyRecipe {
  path: string
  edited_at: string | null
  summary: string
  setting_count: number
  /** Where the recipe was read from: a `.negpy` file, or NegPy's edits.db. */
  source?: "sidecar" | "edits.db"
  file_hash?: string | null
  version?: unknown
  settings?: Record<string, unknown>
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

/**
 * Unwrap `{ok, <key>}`. M2 answers a failure with a 4xx, so `assertOk` sees it first.
 *
 * The parameter is `unknown` rather than `any` because it is whatever the server
 * sent; the two shapes it may have are narrowed here, once, instead of being
 * assumed at every call site.
 */
function unwrap<T>(json: unknown, key: string, fallback: string): T {
  const body = (json ?? {}) as Record<string, unknown>
  if (typeof body.error === "string") {
    throw new ApiError(body.error, fallback, 404)
  }
  // A 2xx whose body does not carry the key is a broken contract, not a value:
  // handing the envelope back would let `undefined` fields travel into the UI.
  if (!(key in body)) {
    throw new ApiError("malformed_response", fallback, 500)
  }
  return body[key] as T
}

/** `?keep_files=true` when the user asked to leave the files on disk (M2, R#9). */
function keepFilesQuery(keepFiles: boolean): string {
  return keepFiles ? "?keep_files=true" : ""
}

// Films API
export async function getFilms(): Promise<Film[]> {
  const res = await apiFetch(`/api/films`, { cache: "no-store" })
  await assertOk(res, "Could not load the rolls.")
  return res.json()
}

export async function getFilm(id: number): Promise<{ film: Film; images: Image[]; contact_sheets: Image[] }> {
  const res = await apiFetch(`/api/films/${id}`, { cache: "no-store" })
  // M2: a missing roll is a real 404 with a structured body (R#17).
  await assertOk(res, "Could not load the roll.")
  const json = await res.json()
  return { film: json.film, images: json.images ?? [], contact_sheets: json.contact_sheets ?? [] }
}

export async function createFilm(data: Partial<Film>): Promise<Film> {
  const res = await apiFetch(`/api/films`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the roll.")
  const json = await res.json()
  return unwrap<Film>(json, "film", "Roll not found.")
}

export async function updateFilm(id: number, data: Partial<Film>): Promise<Film> {
  const res = await apiFetch(`/api/films/${id}`, {
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
  const res = await apiFetch(`/api/films/${id}${keepFilesQuery(keepFiles)}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the roll.")
}

// Images API
export async function getImages(filmId?: number): Promise<Image[]> {
  const path = filmId ? `/api/images?film_id=${filmId}&type=scan` : `/api/images?type=scan`
  const res = await apiFetch(path)
  await assertOk(res, "Could not load the frames.")
  return res.json()
}

export async function getImage(id: number): Promise<Image> {
  const res = await apiFetch(`/api/images/${id}`, { cache: "no-store" })
  await assertOk(res, "Could not load the frame.")
  return (await res.json()) as Image
}

// Bulk operations for film roll images
export async function createContactSheet(
  filmId: number,
  options?: { columns?: number; thumb_size?: number }
): Promise<Image> {
  const params = new URLSearchParams()
  if (options?.columns) params.set("columns", String(options.columns))
  if (options?.thumb_size) params.set("thumb_size", String(options.thumb_size))
  const res = await apiFetch(`/api/films/${filmId}/contact_sheet?${params.toString()}`, {
    method: "POST",
  })
  await assertOk(res, "Could not generate the contact sheet.")
  const json = await res.json()
  return unwrap<Image>(json, "image", "Roll not found.")
}

export async function updateImage(id: number, data: Partial<Image>): Promise<Image> {
  const res = await apiFetch(`/api/images/${id}`, {
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
  const res = await apiFetch(`/api/images/${id}${keepFilesQuery(keepFiles)}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the frame.")
}

// Cameras API
export async function getCameras(): Promise<Camera[]> {
  const res = await apiFetch(`/api/cameras`, { cache: "no-store" })
  await assertOk(res, "Could not load the cameras.")
  return res.json()
}

export async function createCamera(data: Partial<Camera>): Promise<Camera> {
  const res = await apiFetch(`/api/cameras`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the camera.")
  const json = await res.json()
  return unwrap<Camera>(json, "camera", "Camera not found.")
}

export async function updateCamera(id: number, data: Partial<Camera>): Promise<Camera> {
  const res = await apiFetch(`/api/cameras/${id}`, {
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
  const res = await apiFetch(`/api/cameras/${id}${force ? "?force=true" : ""}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the camera.")
}

export async function uploadCameraImage(id: number, file: File): Promise<Camera> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await apiFetch(`/api/cameras/${id}/image`, {
    method: "POST",
    body: formData,
  })
  await assertOk(res, "Could not upload the camera image.")
  const json = await res.json()
  return unwrap<Camera>(json, "camera", "Camera not found.")
}

// Lenses API
export async function getLenses(): Promise<Lens[]> {
  const res = await apiFetch(`/api/lenses`, { cache: "no-store" })
  await assertOk(res, "Could not load the lenses.")
  return res.json()
}

export async function createLens(data: Partial<Lens>): Promise<Lens> {
  const res = await apiFetch(`/api/lenses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the lens.")
  const json = await res.json()
  return unwrap<Lens>(json, "lens", "Lens not found.")
}

export async function updateLens(id: number, data: Partial<Lens>): Promise<Lens> {
  const res = await apiFetch(`/api/lenses/${id}`, {
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
  const res = await apiFetch(`/api/lenses/${id}${force ? "?force=true" : ""}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the lens.")
}

export async function uploadLensImage(id: number, file: File): Promise<Lens> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await apiFetch(`/api/lenses/${id}/image`, {
    method: "POST",
    body: formData,
  })
  await assertOk(res, "Could not upload the lens image.")
  const json = await res.json()
  return unwrap<Lens>(json, "lens", "Lens not found.")
}

// Filmstocks API
export async function getFilmstocks(): Promise<Filmstock[]> {
  const res = await apiFetch(`/api/filmstocks`, { cache: "no-store" })
  await assertOk(res, "Could not load the film stocks.")
  return res.json()
}

export async function createFilmstock(data: Partial<Filmstock>): Promise<Filmstock> {
  const res = await apiFetch(`/api/filmstocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the film stock.")
  const json = await res.json()
  return unwrap<Filmstock>(json, "filmstock", "Filmstock not found.")
}

export async function updateFilmstock(id: number, data: Partial<Filmstock>): Promise<Filmstock> {
  const res = await apiFetch(`/api/filmstocks/${id}`, {
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
  const res = await apiFetch(`/api/filmstocks/${id}${force ? "?force=true" : ""}`, {
    method: "DELETE",
  })
  await assertOk(res, "Could not delete the film stock.")
}

export async function uploadFilmstockImage(id: number, file: File): Promise<Filmstock> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await apiFetch(`/api/filmstocks/${id}/image`, {
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
  const res = await apiFetch(`/api/images/bulk_update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, ...patch }),
  })
  await assertOk(res, "Could not update the selected frames.")
  const json = await res.json()
  return (json?.images ?? []) as Image[]
}

// M7: renumber a roll's frames in one go (app/services/renumber.py).
export type RenumberMode = "sequential" | "reverse" | "shift" | "from_filenames"

export interface RenumberPlanItem {
  id: number
  from: number | null
  to: number | null
  original_filename: string | null
}

export interface RenumberResult {
  ok: boolean
  dry_run: boolean
  plan: RenumberPlanItem[]
  /** How many frames change number (or would, on a dry run). */
  updated: number
  /** Frame numbers used more than once afterwards. Allowed, but worth a look. */
  conflicts: number[]
  images?: Image[]
}

/** `dryRun` answers with the plan and writes nothing. `ids` scopes it to a selection. */
export async function renumberFrames(
  rollId: number,
  {
    mode,
    ids,
    start,
    step,
    offset,
    dryRun = false,
  }: { mode: RenumberMode; ids?: number[]; start?: number; step?: number; offset?: number; dryRun?: boolean },
): Promise<RenumberResult> {
  const body: Record<string, unknown> = { mode, dry_run: dryRun }
  if (ids && ids.length) body.ids = ids
  if (start !== undefined && Number.isFinite(start)) body.start = start
  if (step !== undefined && Number.isFinite(step)) body.step = step
  if (offset !== undefined && Number.isFinite(offset)) body.offset = offset
  const res = await apiFetch(`/api/films/${rollId}/frames/renumber`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  await assertOk(res, "Could not renumber the frames.")
  return res.json()
}

export async function bulkDeleteImages(ids: number[], keepFiles = false): Promise<number> {
  const res = await apiFetch(`/api/images/bulk_delete`, {
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
/** How a preview is rendered (M5). See `PreviewRender` in Settings. */
export type PreviewRender = "auto" | "raw" | "positive"

/**
 * A rendered preview of a frame.
 *
 * `render` chooses what comes back: `auto` (the default) follows the archive's
 * setting — print a frame it knows is a negative, leave everything else alone —
 * while `raw` always shows the scan as stored and `positive` always prints it.
 * Either way the file on disk is untouched: a rendering lives in the disposable
 * preview cache.
 */
export function getPreviewUrl(
  imageId: number,
  width: number,
  render?: PreviewRender,
  version?: string | null,
): string {
  const suffix = render && render !== "auto" ? `&render=${render}` : ""
  // Previews are served immutable, so anything that changes what "auto" means for
  // a frame has to change the URL too. The backend ignores the parameter.
  const bust = version ? `&v=${encodeURIComponent(version)}` : ""
  return backendUrl(`/api/images/${imageId}/preview?width=${width}${suffix}${bust}`)
}

/**
 * The part of a frame that changes its preview without changing its file (M6.1).
 *
 * The backend sends `preview_version`, which moves whenever the file, its `.negpy`
 * sidecar or `positive` changes; the positive-derived token is the fallback for an
 * archive whose backend does not send one yet.
 */
export function previewVersion(image: Pick<Image, "positive" | "preview_version">): string | undefined {
  if (image.preview_version) return image.preview_version
  if (image.positive == null) return undefined
  return image.positive ? "pos" : "neg"
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
    // `fetch` cannot report progress, so this path does not go through
    // `apiFetch` and has to attach the session token itself (M3, R#26).
    const token = readTokenCookie()
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    xhr.onerror = () => reject(new ApiError("network_error", "The upload could not reach the server.", 0))
    xhr.onload = () => {
      let body: Record<string, unknown> | null = null
      try {
        body = JSON.parse(xhr.responseText) as Record<string, unknown>
      } catch {
        // fall through to the status check
      }
      const failure = body?.error
      if (xhr.status >= 400 || typeof failure === "string") {
        // The same body `assertOk` reads, so an upload failure names its field too.
        const structured =
          failure && typeof failure === "object"
            ? (failure as { code?: string; message?: string; field?: string | null })
            : null
        reject(
          new ApiError(
            structured?.code ?? (typeof failure === "string" ? failure : "upload_failed"),
            structured?.message ?? "The server rejected this file.",
            xhr.status,
            structured?.field ?? null,
          ),
        )
        return
      }
      onProgress(1)
      const images: Image[] = (body?.images as Image[]) ?? (body?.image ? [body.image as Image] : [])
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
  options: { positive?: boolean } = {},
): Promise<{ images: Image[] }> {
  const isZip = file.name.toLowerCase().endsWith(".zip") || file.type === "application/zip"
  const formData = new FormData()
  // M6.1: finished positives (NegPy exports) are shown as they are, never printed.
  // Both importers take the flag, so a ZIP of exports arrives marked as well.
  if (options.positive) formData.append("positive", "true")
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

// ---------------------------------------------------------------------------
// M3: paginated, server-side filtered lists (R#20)
//
// The archive used to send every roll and every frame to the browser and filter
// them in React. These call the same endpoints with `limit`, so the API answers
// with a page and a total instead.
// ---------------------------------------------------------------------------

/** How many rolls or frames one "page" holds before "Load more" appears. */
export const PAGE_SIZE = 24

export interface FilmQuery {
  q?: string
  camera?: string
  film_type?: string
  camera_id?: number
  film_stock_id?: number
  from?: string
  to?: string
  /** M4 */
  status?: string
  bucket?: string
  location_id?: number
  limit?: number
  offset?: number
}

export interface ImageQuery {
  film_id?: number
  type?: "scan" | "contact_sheet"
  q?: string
  unassigned?: boolean
  storage_mode?: "managed" | "linked"
  limit?: number
  offset?: number
}

function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue
    search.set(key, String(value))
  }
  const rendered = search.toString()
  return rendered ? `?${rendered}` : ""
}

/** One page of rolls, filtered in Postgres. */
export async function getFilmsPage(query: FilmQuery = {}): Promise<Page<Film>> {
  const res = await apiFetch(`/api/films${queryString({ limit: PAGE_SIZE, ...query })}`)
  await assertOk(res, "Could not load the rolls.")
  return res.json()
}

/** One page of frames, filtered in Postgres. */
export async function getImagesPage(query: ImageQuery = {}): Promise<Page<Image>> {
  const res = await apiFetch(`/api/images${queryString({ limit: PAGE_SIZE, ...query })}`)
  await assertOk(res, "Could not load the frames.")
  return res.json()
}

// ---------------------------------------------------------------------------
// M3: system info, settings, library roots and the optional password
// ---------------------------------------------------------------------------

export interface WatchState {
  enabled: boolean
  interval_seconds: number | null
  roots_total?: number
  roots_watched?: number
  last_scan_at?: string | null
}

export interface SystemInfo {
  app: string
  lan_ips: string[]
  ui_url: string | null
  ui_urls: string[]
  ui_port: number
  qr_url: string
  data_dir: string
  auth_required: boolean
  counts: { rolls: number; frames: number }
  watch: WatchState
  server_time: string
}

export async function getSystemInfo(): Promise<SystemInfo> {
  const res = await apiFetch("/api/system/info")
  await assertOk(res, "Could not reach the archive.")
  return res.json()
}

// ---------------------------------------------------------------------------
// M7: the version on screen, and what changed
// ---------------------------------------------------------------------------

/** One release in CHANGELOG.md, as the backend parses it. */
export interface ChangelogEntry {
  version: string
  date: string | null
  sections: { title: string; items: string[] }[]
}

export interface AppVersion {
  app: string
  /** `app/version.py`: what the backend is. */
  version: string
  /** The commit the published image was built from; null for a source checkout. */
  git_sha: string | null
  built_at: string | null
  changelog: ChangelogEntry[]
  changelog_total: number
  release_url: string
}

/**
 * The version this *frontend* was built as (`frontend/package.json`, baked in by
 * next.config.mjs). Normally equal to the backend's; differs when a tab was open
 * across an update and still runs the old bundle, or when the two images were
 * pulled at different tags.
 */
export const FRONTEND_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || ""

/** `since` trims the changelog to the releases newer than that version. */
export async function getAppVersion(since?: string | null): Promise<AppVersion> {
  const res = await apiFetch(`/api/system/version${since ? `?since=${encodeURIComponent(since)}` : ""}`)
  await assertOk(res, "Could not read the archive's version.")
  return res.json()
}

// ---------------------------------------------------------------------------
// M7: search everything
// ---------------------------------------------------------------------------

export type SearchKind = "roll" | "frame" | "camera" | "lens" | "film_stock" | "location"

export interface SearchRollHit {
  kind: "roll"
  id: number
  title: string
  url: string
  serial: string | null
  status: RollStatus
  status_label: string | null
  film_type: string | null
  camera: string | null
  start_date: string | null
  end_date: string | null
  location_path: string | null
  image_count: number
  cover_image_id: number | null
  cover_version: string | null
}

export interface SearchFrameHit {
  kind: "frame"
  id: number
  title: string
  url: string
  frame_number: number | null
  roll_id: number | null
  roll_title: string | null
  roll_serial: string | null
  notes: string | null
  original_filename: string | null
  capture_date: string | null
  preview_version: string | null
}

export interface SearchGearHit {
  kind: "camera" | "lens" | "film_stock"
  id: number
  title: string
  url: string
  subtitle: string | null
  image_url: string | null
}

export interface SearchLocationHit {
  kind: "location"
  id: number
  title: string
  url: string
  location_kind: string
  kind_label: string
  path: string | null
  code: string | null
  roll_count: number
}

export type SearchHit = SearchRollHit | SearchFrameHit | SearchGearHit | SearchLocationHit

export interface SearchGroup {
  kind: SearchKind
  label: string
  /** How many match in the database — more than `items` when the page is short. */
  total: number
  items: SearchHit[]
}

export interface SearchResult {
  query: string
  parsed: { terms: string[]; phrases: string[]; qualifiers: Record<string, string[]> }
  total: number
  groups: SearchGroup[]
  /** Whether pg_trgm is there, i.e. whether a typo can still find something. */
  fuzzy: boolean
}

/**
 * Everything that matches, grouped by kind (`GET /api/search`). The grammar is
 * the one the roll list's filter bar uses: words that must all match, quoted
 * phrases, and `camera:` / `film:` / `year:` / `status:` / `location:` / `serial:`.
 */
export async function searchArchive(
  q: string,
  { kinds, limit, signal }: { kinds?: SearchKind[]; limit?: number; signal?: AbortSignal } = {},
): Promise<SearchResult> {
  const res = await apiFetch(
    `/api/search${queryString({ q, kinds: kinds?.join(","), limit })}`,
    { signal },
  )
  await assertOk(res, "Could not search the archive.")
  return res.json()
}

export interface Settings {
  watch_enabled: boolean
  /** M4: the serial prefix (NEG) and where printed QR codes point. */
  serial_prefix?: string
  public_base_url?: string
  label_spine_mm?: string
  label_sticker_mm?: string
  /** M5: the NegPy integration. Folders are validated by the backend. */
  negpy_ingest?: boolean
  negpy_create_gear?: boolean
  negpy_user_dir?: string
  negpy_handoff_dir?: string
  negpy_handoff_mode?: string
  negpy_gear_synced_at?: string
  /** M6.3: the address Finder connects to for the archive's own share (IP or hostname). */
  share_host?: string
  /** M5: "auto" | "raw" | "positive" — how previews are rendered. */
  preview_render?: PreviewRender
  /** M6: the NAS share the archive mounts. Mirrors `app/services/settings_store.py`. */
  smb_enabled?: boolean
  smb_host?: string
  smb_share?: string
  smb_subpath?: string
  smb_username?: string
  smb_domain?: string
  smb_version?: string
  smb_readonly?: boolean
  smb_automount?: boolean
  /** M6.2: the last inbox sweep, as the settings store remembers it. */
  inbox_last_sweep_at?: string
  inbox_last_summary?: string
}

export async function getSettings(): Promise<{ settings: Settings; watch: WatchState }> {
  const res = await apiFetch("/api/system/settings")
  await assertOk(res, "Could not load the settings.")
  return res.json()
}

export async function updateSettings(patch: Partial<Settings>): Promise<{ settings: Settings; watch: WatchState }> {
  const res = await apiFetch("/api/system/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  })
  await assertOk(res, "Could not save the settings.")
  return res.json()
}

export interface LibraryRoot {
  id: number
  path: string
  label: string | null
  watch: boolean
  last_scan_at: string | null
  last_scan_summary: string | null
  created_at: string | null
  frame_count: number | null
}

export interface LibraryRoots {
  roots: LibraryRoot[]
  allowed_bases: string[]
  /** False when LIBRARY_ROOTS_ALLOW is unset: the whole feature is switched off. */
  enabled: boolean
}

export async function getLibraryRoots(): Promise<LibraryRoots> {
  const res = await apiFetch("/api/library/roots")
  await assertOk(res, "Could not load the library folders.")
  return res.json()
}

export async function createLibraryRoot(data: {
  path: string
  label?: string
  watch?: boolean
}): Promise<LibraryRoot> {
  const res = await apiFetch("/api/library/roots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not register that folder.")
  return unwrap<LibraryRoot>(await res.json(), "root", "Folder not found.")
}

/** Only the label and the watch flag are editable; the path is what the root is. */
export async function updateLibraryRoot(
  id: number,
  data: { label?: string | null; watch?: boolean },
): Promise<LibraryRoot> {
  const res = await apiFetch(`/api/library/roots/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not save that folder.")
  return unwrap<LibraryRoot>(await res.json(), "root", "Folder not found.")
}

export async function deleteLibraryRoot(id: number, forgetFrames = false): Promise<void> {
  const res = await apiFetch(`/api/library/roots/${id}?forget_frames=${forgetFrames}`, { method: "DELETE" })
  await assertOk(res, "Could not remove that folder.")
}

export interface ScanResult {
  rolls_created: number
  /** Rolls that already existed and were taken over by this root. */
  rolls_adopted: number
  /** `.negpy` sidecars found beside the files. */
  sidecars_seen: number
  frames_added: number
  frames_rehomed: number
  frames_updated: number
  frames_unchanged: number
  files_skipped: number
  roll_ids: number[]
  summary: string
}

export async function scanLibraryRoot(id: number): Promise<ScanResult> {
  const res = await apiFetch(`/api/library/roots/${id}/scan`, { method: "POST" })
  await assertOk(res, "Could not scan that folder.")
  return (await res.json()).result as ScanResult
}

/** Sign in with the shared password. The API also sets the cookie. */
export async function login(password: string): Promise<{ auth_required: boolean; token: string | null }> {
  const res = await apiFetch("/api/system/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  })
  await assertOk(res, "Could not sign in.")
  return res.json()
}

export async function logout(): Promise<void> {
  await apiFetch("/api/system/logout", { method: "POST" })
}

/** Upload an export ZIP. `dryRun` reports what it would do and writes nothing. */
export async function importArchive(file: File, dryRun: boolean): Promise<Record<string, unknown>> {
  const form = new FormData()
  form.append("file", file)
  const res = await apiFetch(`/api/import?dry_run=${dryRun}`, { method: "POST", body: form })
  await assertOk(res, "Could not read that export.")
  return (await res.json()).report as Record<string, unknown>
}

/** Download links; the browser navigates to these, so they are plain URLs. */
export const EXPORT_URL = "/api/export"
export const EXPORT_CSV_URL = "/api/export/rolls.csv"

// ---------------------------------------------------------------------------
// M4: the physical archive — locations, serials, lifecycle, scanning, printing
// ---------------------------------------------------------------------------

export type LocationKind =
  | "building"
  | "room"
  | "shelf"
  | "row"
  | "box"
  | "binder"
  | "envelope"
  | "sleeve"
  | "other"

export const LOCATION_KINDS: { value: LocationKind; label: string }[] = [
  { value: "building", label: "Building" },
  { value: "room", label: "Room" },
  { value: "shelf", label: "Shelf" },
  { value: "row", label: "Row" },
  { value: "binder", label: "Binder" },
  { value: "sleeve", label: "Sleeve page" },
  { value: "box", label: "Box" },
  { value: "envelope", label: "Envelope" },
  { value: "other", label: "Other" },
]

export interface SleeveLayout {
  id: number
  name: string
  rows: number
  frames_per_row: number
  film_format: string | null
  is_default: boolean
  capacity: number
}

export interface Location {
  id: number
  parent_id: number | null
  kind: LocationKind
  name: string
  code: string | null
  /** "B03 · Binder 3" or just the name. */
  label: string
  /** The full path, root first. */
  path: string | null
  path_ids: number[]
  sort_order: number
  notes: string | null
  capacity: number | null
  sleeve_layout_id: number | null
  sleeve_layout: { id: number; name: string; rows: number; frames_per_row: number } | null
  /** Rolls filed directly here. */
  roll_count: number
  /** Rolls anywhere under this node. */
  rolls_in_subtree: number
  /** What a Code128 label for this node carries: `LOC-<id>`. */
  scan_code: string
  created_at: string | null
}

export interface RollBrief {
  id: number
  title: string
  archive_serial: string | null
  status: RollStatus
  film_type: string | null
  camera: string | null
  start_date: string | null
  end_date: string | null
  location_id: number | null
  image_count: number
  label_printed_at: string | null
}

export interface LocationDetail {
  location: Location
  ancestors: Location[]
  children: (Location & { rolls: RollBrief[] })[]
  rolls: RollBrief[]
  effective_layout: { id: number; name: string; rows: number; frames_per_row: number } | null
  next_free_sleeve_id: number | null
  discrepancies: { kind: string; message: string; location_id?: number; roll_id?: number }[]
}

export async function getLocations(): Promise<Location[]> {
  const res = await apiFetch("/api/locations")
  await assertOk(res, "Could not load the locations.")
  return (await res.json()).locations as Location[]
}

export async function getLocation(id: number): Promise<LocationDetail> {
  const res = await apiFetch(`/api/locations/${id}`)
  await assertOk(res, "Could not load that location.")
  return res.json()
}

export interface LocationPatch {
  parent_id?: number | null
  kind?: LocationKind
  name?: string
  code?: string | null
  sort_order?: number
  notes?: string | null
  capacity?: number | null
  sleeve_layout_id?: number | null
}

export async function createLocation(data: LocationPatch): Promise<Location> {
  const res = await apiFetch("/api/locations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not create the location.")
  return unwrap<Location>(await res.json(), "location", "Location not found.")
}

export async function updateLocation(id: number, data: LocationPatch): Promise<Location> {
  const res = await apiFetch(`/api/locations/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not save the location.")
  return unwrap<Location>(await res.json(), "location", "Location not found.")
}

/** 409 `location_in_use` unless `force`; forcing unfiles the rolls inside. */
export async function deleteLocation(id: number, force = false): Promise<void> {
  const res = await apiFetch(`/api/locations/${id}${force ? "?force=true" : ""}`, { method: "DELETE" })
  await assertOk(res, "Could not delete the location.")
}

export async function addBinderPages(id: number, count: number, sleeveLayoutId?: number | null): Promise<Location[]> {
  const res = await apiFetch(`/api/locations/${id}/pages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count, sleeve_layout_id: sleeveLayoutId ?? null }),
  })
  await assertOk(res, "Could not add pages.")
  return (await res.json()).pages as Location[]
}

export async function getSleeveLayouts(): Promise<SleeveLayout[]> {
  const res = await apiFetch("/api/sleeve_layouts")
  await assertOk(res, "Could not load the sleeve layouts.")
  return res.json()
}

export interface MoveResult {
  roll: RollBrief
  location: Location | null
  path: string | null
}

/** File a roll. A binder target resolves to its next free page; `null` unfiles it. */
export async function moveRoll(rollId: number, locationId: number | null, note?: string): Promise<MoveResult> {
  const res = await apiFetch(`/api/films/${rollId}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ location_id: locationId, note: note ?? null }),
  })
  await assertOk(res, "Could not move the roll.")
  return res.json()
}

export async function bulkMoveRolls(ids: number[], locationId: number | null, note?: string): Promise<MoveResult[]> {
  const res = await apiFetch("/api/films/bulk_move", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, location_id: locationId, note: note ?? null }),
  })
  await assertOk(res, "Could not move the rolls.")
  return (await res.json()).moved as MoveResult[]
}

export interface RollMove {
  id: number
  moved_at: string
  from: string | null
  to: string | null
  note: string | null
}

export async function getRollMoves(rollId: number): Promise<RollMove[]> {
  const res = await apiFetch(`/api/films/${rollId}/moves`)
  await assertOk(res, "Could not load the move history.")
  return (await res.json()).moves as RollMove[]
}

export interface LayoutCell {
  id: number
  frame_number: number | null
  notes: string | null
  capture_date: string | null
  /** See `Image.preview_version`. */
  preview_version?: string | null
}

export interface RollLayout {
  strips: number[]
  layout: { id: number; name: string } | null
  capacity: number
  rows: (LayoutCell | null)[][]
  unplaced: LayoutCell[]
}

export async function getRollLayout(rollId: number): Promise<RollLayout> {
  const res = await apiFetch(`/api/films/${rollId}/layout`)
  await assertOk(res, "Could not load the sleeve layout.")
  return res.json()
}

export const ROLL_STATUSES: { value: RollStatus; label: string; short: string }[] = [
  { value: "loaded", label: "In camera", short: "Loaded" },
  { value: "shot", label: "Shot", short: "Shot" },
  { value: "at_lab", label: "At the lab", short: "At lab" },
  { value: "back", label: "Back from the lab", short: "Back" },
  { value: "scanned", label: "Scanned", short: "Scanned" },
  { value: "sleeved", label: "Sleeved", short: "Sleeved" },
]

export async function setRollStatus(rollId: number, status: RollStatus, at?: string): Promise<Film> {
  const res = await apiFetch(`/api/films/${rollId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, at: at ?? null }),
  })
  await assertOk(res, "Could not change the status.")
  return unwrap<Film>(await res.json(), "film", "Roll not found.")
}

/** Create a roll in status "loaded" for a camera; 409 `camera_occupied` unless `force`. */
export async function loadFilm(
  cameraId: number,
  data: { title?: string; film_stock_id?: number | null; lens_id?: number | null; notes?: string; force?: boolean },
): Promise<Film> {
  const res = await apiFetch(`/api/cameras/${cameraId}/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not load the film.")
  return unwrap<Film>(await res.json(), "film", "Roll not found.")
}

export interface WorkLists {
  in_cameras: { total: number; items: Film[] }
  at_lab: { total: number; items: Film[] }
  to_scan: { total: number; items: Film[] }
  to_sleeve: { total: number; items: Film[] }
  unfiled: number
  needs_label: number
}

export async function getWork(): Promise<WorkLists> {
  const res = await apiFetch("/api/work")
  await assertOk(res, "Could not load the work lists.")
  return res.json()
}

export type WorkBucket = "in_cameras" | "at_lab" | "to_scan" | "to_sleeve"

export const WORK_BUCKETS: { value: WorkBucket; label: string }[] = [
  { value: "in_cameras", label: "In cameras" },
  { value: "at_lab", label: "At the lab" },
  { value: "to_scan", label: "To scan" },
  { value: "to_sleeve", label: "To sleeve" },
]

export type ScanResolution =
  | { kind: "roll"; roll: Film; url: string; input: string }
  | { kind: "location"; location: Location; url: string; input: string }
  | { kind: "command"; command: string; known: boolean; description: string | null; input: string }

/** The one grammar for QR contents, Code128 tokens and typed serials. */
export async function resolveScan(code: string): Promise<ScanResolution> {
  const res = await apiFetch("/api/scan/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  })
  await assertOk(res, "That code is not something the archive knows.")
  return res.json()
}

export async function getRollBySerial(serial: string): Promise<Film | null> {
  const res = await apiFetch(`/api/rolls/by-serial/${encodeURIComponent(serial)}`)
  if (res.status === 404) return null
  await assertOk(res, "Could not look up that serial.")
  return (await res.json()).roll as Film
}

export interface ScanCommand {
  code: string
  verb: string
  description: string
}

export async function getScanCommands(): Promise<ScanCommand[]> {
  const res = await apiFetch("/api/scan/commands")
  await assertOk(res, "Could not load the command list.")
  return (await res.json()).commands as ScanCommand[]
}

export interface CodeInfo {
  qr_text: string
  barcode_text: string
  qr_svg_url: string
  barcode_svg_url: string
  public_base: string
  serial?: string
  code?: string
}

export async function getLocationCodes(locationId: number): Promise<CodeInfo> {
  const res = await apiFetch(`/api/codes/for_location/${locationId}`)
  await assertOk(res, "Could not build the codes.")
  return res.json()
}

/** `<img src>` for a QR code of any text, rendered by the backend. */
export function qrUrl(text: string, scale = 4): string {
  return backendUrl(`/api/codes/qr.svg?text=${encodeURIComponent(text)}&scale=${scale}`)
}

/** `<img src>` for a Code128 barcode of any text (ASCII, up to 60 characters). */
export function barcodeUrl(text: string, height = 12, label = true): string {
  return backendUrl(`/api/codes/code128.svg?text=${encodeURIComponent(text)}&height=${height}&label=${label}`)
}

export interface PrintQueue {
  items: (Film & { reason: "never_printed" | "moved_since_print" })[]
  total: number
  limit?: number
  offset?: number
  has_more?: boolean
}

/**
 * A page of the print queue. An archive that has never printed a label has its
 * whole catalogue in here, so this is paged like every other list.
 */
export async function getPrintQueue(
  query: { limit?: number; offset?: number; reason?: "never_printed" | "moved_since_print" } = {},
): Promise<PrintQueue> {
  const params = new URLSearchParams()
  params.set("limit", String(query.limit ?? PRINT_QUEUE_PAGE))
  if (query.offset) params.set("offset", String(query.offset))
  if (query.reason) params.set("reason", query.reason)
  const res = await apiFetch(`/api/print/queue?${params.toString()}`)
  await assertOk(res, "Could not load the print queue.")
  return res.json()
}

/** How many rolls the queue asks for at a time. */
export const PRINT_QUEUE_PAGE = 50

export async function markPrinted(rollIds: number[]): Promise<number> {
  const res = await apiFetch("/api/print/mark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ roll_ids: rollIds }),
  })
  await assertOk(res, "Could not mark the labels as printed.")
  return Number((await res.json()).marked ?? 0)
}

/** Every roll, for pickers and printouts that need the whole archive. */
export async function getAllFilms(): Promise<Film[]> {
  const res = await apiFetch("/api/films")
  await assertOk(res, "Could not load the rolls.")
  return res.json()
}


// ---------------------------------------------------------------------------
// NegPy (M5)
//
// File-based, both ways: NegArchive reads what NegPy wrote into a scan and writes
// what NegPy needs to open a roll. Nothing here talks to a running NegPy — there
// is nothing to talk to (docs/NEGPY_INTEGRATION.md).
// ---------------------------------------------------------------------------

export interface NegpyStatus {
  ingest_enabled: boolean
  create_gear: boolean
  handoff_mode: string
  gear_synced_at: string | null
  paths: {
    user_dir: string | null
    gear_dir: string | null
    presets_dir: string | null
    handoff_dir: string | null
    error: string | null
  }
  /** NegPy's own edits database, read-only. Absent is normal, not an error. */
  edits_db: {
    path: string | null
    exists: boolean
    readable: boolean
    table: string | null
    rows: number | null
  }
  allowed_bases: string[]
  /** The NegPy export pattern to set, and the one NegArchive parses back. */
  filename_pattern: string
  frames_with_metadata: number
  frames_edited_in_negpy: number
  xmp_namespace: string
}

export async function getNegpyStatus(): Promise<NegpyStatus> {
  const res = await apiFetch("/api/negpy/status")
  await assertOk(res, "Could not read the NegPy settings.")
  return res.json()
}

export interface GearSyncResult {
  directory: string
  dry_run: boolean
  files: Record<string, { path: string; ours: number; kept: number; removed: number; total: number }>
  synced_at: string | null
  total: number
}

export async function syncNegpyGear(dryRun = false): Promise<GearSyncResult> {
  const res = await apiFetch(`/api/negpy/gear/sync${dryRun ? "?dry_run=true" : ""}`, { method: "POST" })
  await assertOk(res, "Could not write the gear files.")
  return (await res.json()).result
}

export interface HandoffResult {
  roll_id: number
  serial: string | null
  folder: string
  preset_path: string | null
  mode: string
  linked: number
  copied: number
  sidecars: number
  skipped: string[]
  frames: number
  prepared_at: string | null
  filename_pattern: string
}

export async function prepareNegpyHandoff(rollId: number, mode?: "link" | "copy"): Promise<HandoffResult> {
  const res = await apiFetch(`/api/negpy/rolls/${rollId}/handoff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mode ? { mode } : {}),
  })
  await assertOk(res, "Could not prepare the roll for NegPy.")
  return (await res.json()).handoff
}

/** What to type into NegPy's Live View & Scan so the frames land on one roll (M6.1). */
export interface ScanPlan {
  roll_id: number
  /** The share's rolls/ folder, as the container sees it. */
  output_dir: string
  /** The same folder as the Mac sees it — what gets typed into NegPy. */
  mac_output_dir: string
  served: boolean
  /** The archive's serial — NegPy's "roll name" field. Null until the roll has one. */
  roll_name: string | null
  folder: string | null
  example_file: string | null
  root_id: number | null
  mounted: boolean
  watched: boolean
  /** Seconds between watcher sweeps; null when the watcher is off. */
  interval_seconds: number | null
  ready: boolean
  source_dir: string | null
  already_linked: boolean
}

export async function getNegpyScanPlan(rollId: number): Promise<ScanPlan> {
  const res = await apiFetch(`/api/negpy/rolls/${rollId}/scan`)
  await assertOk(res, "Could not work out the scan folder for this roll.")
  return (await res.json()).scan
}

export interface IngestReport {
  examined: number
  changed: number
  sidecars: number
  edits_matched?: number
}

export interface EditsMatchReport {
  database: string
  examined: number
  matched: number
  rows: number | null
}

/**
 * Match frames against NegPy's `edits.db` by content hash (M5).
 *
 * For an archive whose owner never turned sidecars on. The database is opened
 * read-only and immutable by the backend; nothing in it is written or locked.
 */
export async function matchNegpyEdits(body: { film_id?: number; all?: boolean } = {}): Promise<EditsMatchReport> {
  const res = await apiFetch("/api/negpy/edits/match", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  await assertOk(res, "Could not read NegPy's edits database.")
  return res.json()
}

export async function ingestNegpyMetadata(body: { film_id?: number; all?: boolean } = {}): Promise<IngestReport> {
  const res = await apiFetch("/api/negpy/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  await assertOk(res, "Could not read the files.")
  return res.json()
}

// ---------------------------------------------------------------------------
// M6: the network share, and the live mode built on it (docs/NEGPY_LIVE.md)
// ---------------------------------------------------------------------------

export interface SmbConfig {
  enabled: boolean
  host: string
  share: string
  /** An optional folder inside the share. */
  subpath: string
  username: string
  domain: string
  version: string
  readonly: boolean
  automount: boolean
  /** `//nas.local/photo`, empty until a host and share are set. */
  unc: string
  /** `//nas.local/photo/film` — the share plus the folder inside it. */
  display: string
}

export interface SmbCapabilities {
  /** Is `mount.cifs` in the image? */
  cifs_utils: boolean
  cifs_utils_path: string | null
  /** Does the container have CAP_SYS_ADMIN? Without it, mount() is EPERM. */
  sys_admin: boolean
  /** CAP_DAC_READ_SEARCH, which `mount.cifs` asks for before it starts. Missing
   *  it looks like "Unable to apply new capability set." and nothing else. */
  dac_read_search: boolean
  mount_base: string
}

export interface SmbStatus {
  config: SmbConfig
  mountpoint: string
  mounted: boolean
  /** Whether a password is stored. Never the password itself. */
  has_credentials: boolean
  capabilities: SmbCapabilities
  /** A sentence naming the fix, when the container cannot mount at all. */
  unavailable_reason: string | null
  space: { total: number; used: number; free: number } | null
  versions: string[]
}

/** How the archive's own share is reached and laid out (M6.2, M6.3). */
export interface ShareInfo {
  name: string
  user: string
  port: number
  /** The `share_host` setting / SHARE_HOST, or the links' hostname; null = LAN addresses. */
  host_override: string | null
  /** smb:// addresses for Finder, best first; empty when no LAN address is known. */
  urls: string[]
  url: string | null
  /** What Finder mounts it as. */
  mac_root: string
  /** The inbox as the Mac sees it — NegPy's export folder. */
  mac_path: string
  dir: string
  folders: Record<string, string>
  mac_folders: Record<string, string>
  filename_pattern: string
}

/** The inbox: what is waiting in it, and the last sweep (M6.2). */
export interface InboxStatus {
  dir: string
  exists: boolean
  share: ShareInfo
  pending: { count: number; files: { name: string; size: number; age_seconds: number; accepted: boolean }[] }
  last_sweep_at: string | null
  last_summary: string | null
  /** Seconds between sweeps; null when the watcher is off. */
  interval_seconds: number | null
  filename_pattern: string
}

export interface InboxSweep {
  imported: number
  filed: number
  unassigned: number
  duplicates: number
  settling: number
  rejected: { name: string; reason: string }[]
  folders_removed: number
  roll_ids: number[]
  image_ids: number[]
  summary: string
}

/** Everything the share card draws: the address, live mode, the inbox (M6.3). */
export interface ShareStatus {
  share: ShareInfo
  live: LiveState
  inbox: InboxStatus
}

export async function getShare(): Promise<ShareStatus> {
  const res = await apiFetch("/api/share")
  await assertOk(res, "Could not read the share.")
  return res.json()
}

/** Live mode on the archive's own share: the watched folder, NegPy's folders, gear. */
export async function setupShare(): Promise<{ report: LiveReport; live: LiveState; share: ShareInfo }> {
  const res = await apiFetch("/api/share/setup", { method: "POST" })
  await assertOk(res, "Could not set the share up.")
  return res.json()
}

export async function sweepInbox(): Promise<InboxStatus & { result: InboxSweep }> {
  const res = await apiFetch("/api/inbox/sweep", { method: "POST" })
  await assertOk(res, "Could not import from the inbox.")
  return res.json()
}

/** The half of live mode that happens on the laptop. Comes from the backend so
 *  the folder names in the instructions are the ones it actually made. */
export interface LiveClientSteps {
  /** smb:// addresses for Finder, best first. */
  urls: string[]
  url: string | null
  user: string
  mac_root: string
  rolls: string
  inbox: string
  /** The old name of the inbox step. */
  exports: string
  user_dir: string
  handoff: string
  filename_pattern: string
}

export interface LiveState {
  /** The served folder exists (M6.3); `mounted` is its old name. */
  served: boolean
  mounted: boolean
  base: string
  mountpoint: string
  layout: Record<string, boolean>
  folders: { path: string; exists: boolean; registered: boolean; watched: boolean }[]
  negpy_user_dir_on_share: boolean
  watch_enabled: boolean
  /** Every part checked against the world, not remembered. */
  ready: boolean
  client: LiveClientSteps
}

export interface LiveReport {
  base: string
  mountpoint: string
  folders_created: string[]
  folders_existing: string[]
  roots_added: string[]
  roots_existing: string[]
  settings_changed: Record<string, string>
  gear: Record<string, unknown>
  watch_enabled: boolean
  changed: boolean
  summary: string
  client: LiveClientSteps
}

export async function getSmbStatus(): Promise<SmbStatus> {
  const res = await apiFetch("/api/smb/status")
  await assertOk(res, "Could not read the share settings.")
  return res.json()
}

/** Save the share. Omit `password` to keep the stored one; pass "" to clear it. */
export async function saveSmbConfig(data: {
  host: string
  share: string
  subpath?: string
  username?: string
  password?: string
  domain?: string
  version?: string
  readonly?: boolean
  automount?: boolean
  enabled?: boolean
}): Promise<SmbStatus> {
  const res = await apiFetch("/api/smb/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not save the share.")
  return res.json()
}

/** A TCP connect to the NAS, before anything privileged is attempted. */
export async function testSmb(data: { host?: string; share?: string } = {}): Promise<{
  ok: boolean
  reachable: boolean
  error?: string
  capabilities: SmbCapabilities
  unavailable_reason: string | null
}> {
  const res = await apiFetch("/api/smb/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  await assertOk(res, "Could not reach the NAS.")
  return res.json()
}

export async function mountSmb(): Promise<SmbStatus> {
  const res = await apiFetch("/api/smb/mount", { method: "POST" })
  await assertOk(res, "Could not mount the share.")
  return res.json()
}

export async function unmountSmb(lazy = false): Promise<SmbStatus> {
  const res = await apiFetch(`/api/smb/unmount?lazy=${lazy}`, { method: "POST" })
  await assertOk(res, "Could not unmount the share.")
  return res.json()
}

export async function forgetSmbPassword(): Promise<SmbStatus> {
  const res = await apiFetch("/api/smb/credentials", { method: "DELETE" })
  await assertOk(res, "Could not forget the password.")
  return res.json()
}

