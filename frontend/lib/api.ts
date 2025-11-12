const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8010"

export interface Film {
  id: number
  title: string
  camera: string | null
  lens: string | null
  film_type: string | null
  notes: string | null
  building: string | null
  folder: string | null
  archive_serial: string | null
  start_date: string | null
  end_date: string | null
  created_at: string
}

export interface Image {
  id: number
  film_roll_id: number | null
  type: "scan" | "contact_sheet"
  path: string
  url: string
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
  iso: number
  kind: string
  expired: boolean
  expiration_date: string | null
  image_path: string | null
  url?: string | null
}

// Films API
export async function getFilms(): Promise<Film[]> {
  const res = await fetch(`${API_BASE}/api/films`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch films")
  return res.json()
}

export async function getFilm(id: number): Promise<{ film: Film; images: Image[] }> {
  const res = await fetch(`${API_BASE}/api/films/${id}`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch film")
  return res.json()
}

export async function createFilm(data: Partial<Film>): Promise<Film> {
  const res = await fetch(`${API_BASE}/api/films`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to create film")
  return res.json()
}

export async function updateFilm(id: number, data: Partial<Film>): Promise<Film> {
  const res = await fetch(`${API_BASE}/api/films/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to update film")
  return res.json()
}

export async function deleteFilm(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/films/${id}`, { method: "DELETE" })
  if (!res.ok) throw new Error("Failed to delete film")
}

// Images API
export async function getImages(filmId?: number): Promise<Image[]> {
  const url = filmId ? `${API_BASE}/api/images?film_id=${filmId}` : `${API_BASE}/api/images`
  const res = await fetch(url, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch images")
  return res.json()
}

export async function getImage(id: number): Promise<Image> {
  const res = await fetch(`${API_BASE}/api/images/${id}`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch image")
  return res.json()
}

export async function uploadImage(formData: FormData): Promise<Image> {
  const res = await fetch(`${API_BASE}/api/images/upload`, {
    method: "POST",
    body: formData,
  })
  if (!res.ok) throw new Error("Failed to upload image")
  return res.json()
}

// Bulk operations for film roll images
export async function createContactSheet(
  filmId: number,
  options?: { columns?: number; thumb_size?: number }
): Promise<{ ok: boolean; image: Image } | { error: string }> {
  const params = new URLSearchParams()
  if (options?.columns) params.set("columns", String(options.columns))
  if (options?.thumb_size) params.set("thumb_size", String(options.thumb_size))
  const res = await fetch(`${API_BASE}/api/films/${filmId}/contact_sheet?${params.toString()}`, {
    method: "POST",
  })
  return res.json()
}

export async function bulkUploadImages(
  filmId: number,
  files: File[]
): Promise<{ ok: boolean; images: Image[] } | { error: string }> {
  const formData = new FormData()
  for (const f of files) {
    formData.append("files", f)
  }
  const res = await fetch(`${API_BASE}/api/films/${filmId}/images/bulk`, {
    method: "POST",
    body: formData,
  })
  return res.json()
}

export async function bulkUploadZip(
  filmId: number,
  zipFile: File
): Promise<{ ok: boolean; images: Image[] } | { error: string }> {
  const formData = new FormData()
  formData.append("file", zipFile)
  const res = await fetch(`${API_BASE}/api/films/${filmId}/images/bulk_zip`, {
    method: "POST",
    body: formData,
  })
  return res.json()
}

export async function updateImage(id: number, data: Partial<Image>): Promise<Image> {
  const res = await fetch(`${API_BASE}/api/images/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to update image")
  return res.json()
}

export async function deleteImage(id: number, deleteFile = false): Promise<void> {
  const res = await fetch(`${API_BASE}/api/images/${id}?delete_file=${deleteFile}`, {
    method: "DELETE",
  })
  if (!res.ok) throw new Error("Failed to delete image")
}

// Cameras API
export async function getCameras(): Promise<Camera[]> {
  const res = await fetch(`${API_BASE}/api/cameras`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch cameras")
  return res.json()
}

export async function getCamera(id: number): Promise<Camera> {
  const res = await fetch(`${API_BASE}/api/cameras/${id}`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch camera")
  return res.json()
}

export async function createCamera(data: Partial<Camera>): Promise<Camera> {
  const res = await fetch(`${API_BASE}/api/cameras`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to create camera")
  return res.json()
}

export async function updateCamera(id: number, data: Partial<Camera>): Promise<Camera> {
  const res = await fetch(`${API_BASE}/api/cameras/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to update camera")
  return res.json()
}

export async function deleteCamera(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/cameras/${id}`, { method: "DELETE" })
  if (!res.ok) throw new Error("Failed to delete camera")
}

export async function uploadCameraImage(id: number, file: File): Promise<Camera> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await fetch(`${API_BASE}/api/cameras/${id}/image`, {
    method: "POST",
    body: formData,
  })
  if (!res.ok) throw new Error("Failed to upload camera image")
  return res.json()
}

// Lenses API
export async function getLenses(): Promise<Lens[]> {
  const res = await fetch(`${API_BASE}/api/lenses`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch lenses")
  return res.json()
}

export async function getLens(id: number): Promise<Lens> {
  const res = await fetch(`${API_BASE}/api/lenses/${id}`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch lens")
  return res.json()
}

export async function createLens(data: Partial<Lens>): Promise<Lens> {
  const res = await fetch(`${API_BASE}/api/lenses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to create lens")
  return res.json()
}

export async function updateLens(id: number, data: Partial<Lens>): Promise<Lens> {
  const res = await fetch(`${API_BASE}/api/lenses/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to update lens")
  return res.json()
}

export async function deleteLens(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/lenses/${id}`, { method: "DELETE" })
  if (!res.ok) throw new Error("Failed to delete lens")
}

export async function uploadLensImage(id: number, file: File): Promise<Lens> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await fetch(`${API_BASE}/api/lenses/${id}/image`, {
    method: "POST",
    body: formData,
  })
  if (!res.ok) throw new Error("Failed to upload lens image")
  return res.json()
}

// Filmstocks API
export async function getFilmstocks(): Promise<Filmstock[]> {
  const res = await fetch(`${API_BASE}/api/filmstocks`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch filmstocks")
  return res.json()
}

export async function getFilmstock(id: number): Promise<Filmstock> {
  const res = await fetch(`${API_BASE}/api/filmstocks/${id}`, { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to fetch filmstock")
  return res.json()
}

export async function createFilmstock(data: Partial<Filmstock>): Promise<Filmstock> {
  const res = await fetch(`${API_BASE}/api/filmstocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to create filmstock")
  return res.json()
}

export async function updateFilmstock(id: number, data: Partial<Filmstock>): Promise<Filmstock> {
  const res = await fetch(`${API_BASE}/api/filmstocks/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to update filmstock")
  return res.json()
}

export async function deleteFilmstock(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/filmstocks/${id}`, { method: "DELETE" })
  if (!res.ok) throw new Error("Failed to delete filmstock")
}

export async function uploadFilmstockImage(id: number, file: File): Promise<Filmstock> {
  const formData = new FormData()
  formData.append("file", file)
  const res = await fetch(`${API_BASE}/api/filmstocks/${id}/image`, {
    method: "POST",
    body: formData,
  })
  if (!res.ok) throw new Error("Failed to upload filmstock image")
  return res.json()
}

export function getImageUrl(image: Image): string {
  // Always serve via preview to ensure browser-friendly format (handles TIFF/JPEG/PNG uniformly)
  return `${API_BASE}/api/images/${image.id}/preview`
}

export function getImageDownloadUrl(image: Image): string {
  // Download original asset via API to enforce Content-Disposition
  return `${API_BASE}/api/images/${image.id}/download`
}
