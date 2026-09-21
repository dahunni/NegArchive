"use client"

import { type Camera, type Film, type Filmstock, type Lens, type Location, ROLL_STATUSES } from "@/lib/api"
import { LocationPicker } from "@/components/location-picker"
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
  /** M5: how the roll was developed. Free text, as it is written on the envelope. */
  developer: string
  development_dilution: string
  push_pull: string
  development_time: string
  /** M4: the sleeve/binder/box id as a string, "" for unfiled. */
  location_id: string
  /** M4: "6,6,6,6,6,6" or "" for the sleeve layout's default. */
  strips: string
  /** M4: one of the lifecycle steps. */
  status: string
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
  developer: "",
  development_dilution: "",
  push_pull: "",
  development_time: "",
  location_id: "",
  strips: "",
  status: "back",
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
    developer: text(values.developer),
    development_dilution: text(values.development_dilution),
    push_pull: text(values.push_pull),
    development_time: text(values.development_time),
    location_id: id(values.location_id),
    strips: text(values.strips)
      ? values.strips
          .split(/[,;\s]+/)
          .map((part) => part.trim())
          .filter(Boolean)
          .map((part) => Number(part))
      : null,
    status: (text(values.status) ?? "back") as Film["status"],
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
  developer?: string | null
  development_dilution?: string | null
  push_pull?: string | null
  development_time?: string | null
  location_id?: number | null
  strips?: number[] | null
  status?: string
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
    developer: film.developer ?? "",
    development_dilution: film.development_dilution ?? "",
    push_pull: film.push_pull ?? "",
    development_time: film.development_time ?? "",
    location_id: id(film.location_id ?? null),
    strips: film.strips?.length ? film.strips.join(",") : "",
    status: film.status ?? "back",
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
  // …but the lens already on the roll stays in the list whatever its mount says
  // (R#78), because a select whose value is missing from its items shows nothing.
  const usableLenses = selectedCamera?.mount
    ? lenses.filter(
        (lens) => !lens.mount || lens.mount === selectedCamera.mount || String(lens.id) === values.lens_id,
      )
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
  errors,
  onChange,
  idPrefix = "roll",
  locations = [],
  serialLocked = false,
}: {
  values: RollFormValues
  errors?: Record<string, string>
  onChange: (patch: Partial<RollFormValues>) => void
  idPrefix?: string
  /** M4: the storage tree for the location picker. */
  locations?: Location[]
  /** M4: a printed serial cannot be edited here (the API refuses with 409). */
  serialLocked?: boolean
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-location`}>Where the negatives are</Label>
        <LocationPicker
          id={`${idPrefix}-location`}
          locations={locations}
          value={values.location_id}
          onChange={(value) => onChange({ location_id: value })}
          placeholder="Not filed yet"
        />
        <p className="type-meta">A binder files the roll on its next free page. Manage the tree under Locations.</p>
        <FieldError message={errors?.location_id} />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-serial`}>Archive serial</Label>
          <Input
            id={`${idPrefix}-serial`}
            name="archive_serial"
            value={values.archive_serial}
            onChange={(e) => onChange({ archive_serial: e.target.value.toUpperCase() })}
            placeholder="Assigned automatically"
            className="type-numeric"
            disabled={serialLocked}
            aria-invalid={Boolean(errors?.archive_serial)}
          />
          <p className="type-meta">{serialLocked ? "Printed on a label; frozen." : "Leave empty for NEG-YYYY-NNNN."}</p>
          <FieldError message={errors?.archive_serial} />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-strips`}>Strips</Label>
          <Input
            id={`${idPrefix}-strips`}
            name="strips"
            value={values.strips}
            onChange={(e) => onChange({ strips: e.target.value })}
            placeholder="Sleeve default"
            className="type-numeric"
            aria-invalid={Boolean(errors?.strips)}
          />
          <p className="type-meta">Frames per strip, e.g. 5,5,5,5,5,5,6 for a doubled-up page.</p>
          <FieldError message={errors?.strips} />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-status`}>Status</Label>
          <Select value={values.status || "back"} onValueChange={(value) => onChange({ status: value })}>
            <SelectTrigger id={`${idPrefix}-status`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLL_STATUSES.map((step) => (
                <SelectItem key={step.value} value={step.value}>
                  {step.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* M5: what happened in the tank. Four free-text fields rather than a
          developer catalog: this is what is written on the envelope, and NegPy's
          XMP fills it in by itself for a scan that came from there. */}
      <fieldset className="space-y-2" data-testid="development-fields">
        <legend className="type-meta uppercase tracking-wide">Development</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-developer`}>Developer</Label>
            <Input
              id={`${idPrefix}-developer`}
              name="developer"
              value={values.developer}
              onChange={(e) => onChange({ developer: e.target.value })}
              placeholder="Rodinal, Xtol, the lab…"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-dilution`}>Dilution</Label>
            <Input
              id={`${idPrefix}-dilution`}
              name="development_dilution"
              value={values.development_dilution}
              onChange={(e) => onChange({ development_dilution: e.target.value })}
              placeholder="1+50, stock…"
              className="type-numeric"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-push`}>Push / pull</Label>
            <Input
              id={`${idPrefix}-push`}
              name="push_pull"
              value={values.push_pull}
              onChange={(e) => onChange({ push_pull: e.target.value })}
              placeholder="+1, −2, none"
              className="type-numeric"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-devtime`}>Time</Label>
            <Input
              id={`${idPrefix}-devtime`}
              name="development_time"
              value={values.development_time}
              onChange={(e) => onChange({ development_time: e.target.value })}
              placeholder="9:30 at 20 °C"
              className="type-numeric"
            />
          </div>
        </div>
        <p className="type-meta">
          Filled in automatically from a scan exported by NegPy, when it says so.
        </p>
      </fieldset>

      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-notes`}>Notes</Label>
        <Textarea
          id={`${idPrefix}-notes`}
          name="notes"
          value={values.notes}
          onChange={(e) => onChange({ notes: e.target.value })}
          placeholder="Anything else worth remembering about this roll…"
          rows={3}
        />
      </div>
    </div>
  )
}
