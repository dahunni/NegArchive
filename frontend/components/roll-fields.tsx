"use client"

import type { Camera, Filmstock, Lens } from "@/lib/api"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

/**
 * What the wizard and the edit sheet both edit. Strings throughout; "" means unset.
 *
 * M2: gear is chosen by **id** (R#14). The select values are the ids as strings, and
 * `toRollPayload` sends `camera_id`/`lens_id`/`film_stock_id`, so renaming a camera
 * in Gear no longer orphans the rolls that were shot with it.
 */
export interface RollFormValues {
  title: string
  camera_id: string
  lens_id: string
  film_stock_id: string
  format: string
  start_date: string
  end_date: string
  building: string
  folder: string
  archive_serial: string
  notes: string
}

export const EMPTY_ROLL: RollFormValues = {
  title: "",
  camera_id: "",
  lens_id: "",
  film_stock_id: "",
  format: "",
  start_date: "",
  end_date: "",
  building: "",
  folder: "",
  archive_serial: "",
  notes: "",
}

/** The select's "nothing chosen" value; the API stores NULL for it (R#8). */
export const NONE = "__none__"

/** The formats the API accepts for a roll or a film stock (R#21). */
export const FILM_FORMATS = [
  { value: "35mm", label: "35mm" },
  { value: "120", label: "120 (medium format)" },
  { value: "4x5", label: "4×5 sheet" },
  { value: "8x10", label: "8×10 sheet" },
  { value: "other", label: "Other" },
]

export function toRollPayload(values: RollFormValues) {
  const text = (value: string) => (value.trim() === "" ? null : value.trim())
  const id = (value: string) => (value.trim() === "" ? null : Number(value))
  return {
    title: values.title.trim(),
    camera_id: id(values.camera_id),
    lens_id: id(values.lens_id),
    film_stock_id: id(values.film_stock_id),
    format: text(values.format),
    start_date: text(values.start_date),
    end_date: text(values.end_date),
    building: text(values.building),
    folder: text(values.folder),
    archive_serial: text(values.archive_serial),
    notes: text(values.notes),
  }
}

/** The form values for an existing roll: ids, with "" for "not recorded". */
export function fromFilm(film: {
  title: string | null
  camera_id: number | null
  lens_id: number | null
  film_stock_id: number | null
  format: string | null
  start_date: string | null
  end_date: string | null
  building: string | null
  folder: string | null
  archive_serial: string | null
  notes: string | null
}): RollFormValues {
  const id = (value: number | null) => (value === null || value === undefined ? "" : String(value))
  return {
    title: film.title ?? "",
    camera_id: id(film.camera_id),
    lens_id: id(film.lens_id),
    film_stock_id: id(film.film_stock_id),
    format: film.format ?? "",
    start_date: film.start_date ?? "",
    end_date: film.end_date ?? "",
    building: film.building ?? "",
    folder: film.folder ?? "",
    archive_serial: film.archive_serial ?? "",
    notes: film.notes ?? "",
  }
}

export function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return (
    <p role="alert" className="text-xs font-medium text-destructive">
      {message}
    </p>
  )
}

export function TitleAndDates({
  values,
  errors,
  onChange,
  idPrefix = "roll",
}: {
  values: RollFormValues
  errors: Record<string, string>
  onChange: (patch: Partial<RollFormValues>) => void
  idPrefix?: string
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-title`}>
          Title <span className="text-destructive">*</span>
        </Label>
        <Input
          id={`${idPrefix}-title`}
          name="title"
          value={values.title}
          onChange={(e) => onChange({ title: e.target.value })}
          placeholder="Summer 2024 — Japan"
          aria-invalid={Boolean(errors.title)}
          autoComplete="off"
        />
        <FieldError message={errors.title} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-start`}>First frame shot</Label>
          <Input
            id={`${idPrefix}-start`}
            name="start_date"
            type="date"
            value={values.start_date}
            onChange={(e) => onChange({ start_date: e.target.value })}
            aria-invalid={Boolean(errors.start_date)}
          />
          <FieldError message={errors.start_date} />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-end`}>Last frame shot</Label>
          <Input
            id={`${idPrefix}-end`}
            name="end_date"
            type="date"
            value={values.end_date}
            onChange={(e) => onChange({ end_date: e.target.value })}
            aria-invalid={Boolean(errors.end_date)}
          />
          <FieldError message={errors.end_date} />
        </div>
      </div>
    </div>
  )
}

export function GearFields({
  values,
  errors,
  onChange,
  cameras,
  lenses,
  filmstocks,
  idPrefix = "roll",
}: {
  values: RollFormValues
  errors?: Record<string, string>
  onChange: (patch: Partial<RollFormValues>) => void
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
  idPrefix?: string
}) {
  const selectedCamera = cameras.find((c) => String(c.id) === values.camera_id) || null
  // Lenses that cannot go on the chosen camera are noise; show all when nothing is chosen.
  const usableLenses = selectedCamera?.mount
    ? lenses.filter((lens) => !lens.mount || lens.mount === selectedCamera.mount)
    : lenses

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-camera`}>Camera</Label>
          <Select
            value={values.camera_id || NONE}
            onValueChange={(value) => onChange({ camera_id: value === NONE ? "" : value })}
          >
            <SelectTrigger id={`${idPrefix}-camera`} aria-invalid={Boolean(errors?.camera_id)}>
              <SelectValue placeholder="Select camera" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Not recorded</SelectItem>
              {cameras.map((camera) => (
                <SelectItem key={camera.id} value={String(camera.id)}>
                  {camera.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldError message={errors?.camera_id} />
        </div>

        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-lens`}>Lens</Label>
          <Select
            value={values.lens_id || NONE}
            onValueChange={(value) => onChange({ lens_id: value === NONE ? "" : value })}
          >
            <SelectTrigger id={`${idPrefix}-lens`} aria-invalid={Boolean(errors?.lens_id)}>
              <SelectValue placeholder="Select lens" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Not recorded</SelectItem>
              {usableLenses.map((lens) => (
                <SelectItem key={lens.id} value={String(lens.id)}>
                  {lens.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedCamera?.mount ? (
            <p className="type-meta">Lenses with a {selectedCamera.mount} mount</p>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-film`}>Film stock</Label>
          <Select
            value={values.film_stock_id || NONE}
            onValueChange={(value) => onChange({ film_stock_id: value === NONE ? "" : value })}
          >
            <SelectTrigger id={`${idPrefix}-film`} aria-invalid={Boolean(errors?.film_stock_id)}>
              <SelectValue placeholder="Select film stock" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Not recorded</SelectItem>
              {filmstocks.map((stock) => (
                <SelectItem key={stock.id} value={String(stock.id)}>
                  {stock.name}
                  {stock.iso ? ` · ISO ${stock.iso}` : ""}
                  {stock.format ? ` · ${stock.format}` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-format`}>Format</Label>
          <Select
            value={values.format || NONE}
            onValueChange={(value) => onChange({ format: value === NONE ? "" : value })}
          >
            <SelectTrigger id={`${idPrefix}-format`} aria-invalid={Boolean(errors?.format)}>
              <SelectValue placeholder="Select format" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Not recorded</SelectItem>
              {FILM_FORMATS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldError message={errors?.format} />
        </div>
      </div>
    </div>
  )
}

export function StorageFields({
  values,
  onChange,
  idPrefix = "roll",
}: {
  values: RollFormValues
  onChange: (patch: Partial<RollFormValues>) => void
  idPrefix?: string
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-building`}>Building</Label>
          <Input
            id={`${idPrefix}-building`}
            name="building"
            value={values.building}
            onChange={(e) => onChange({ building: e.target.value })}
            placeholder="Archive A"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-folder`}>Folder / binder</Label>
          <Input
            id={`${idPrefix}-folder`}
            name="folder"
            value={values.folder}
            onChange={(e) => onChange({ folder: e.target.value })}
            placeholder="2024-Q2"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-serial`}>Archive serial</Label>
          <Input
            id={`${idPrefix}-serial`}
            name="archive_serial"
            value={values.archive_serial}
            onChange={(e) => onChange({ archive_serial: e.target.value })}
            placeholder="NEG-2024-001"
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-notes`}>Notes</Label>
        <Textarea
          id={`${idPrefix}-notes`}
          name="notes"
          value={values.notes}
          onChange={(e) => onChange({ notes: e.target.value })}
          placeholder="Developed at home, Rodinal 1+50…"
          rows={3}
        />
      </div>
    </div>
  )
}
