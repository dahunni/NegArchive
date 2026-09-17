"use client"

import type { Camera, Filmstock, Lens } from "@/lib/api"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

/** What the wizard and the edit sheet both edit. Strings throughout; "" means unset. */
export interface RollFormValues {
  title: string
  camera: string
  lens: string
  film_type: string
  start_date: string
  end_date: string
  building: string
  folder: string
  archive_serial: string
  notes: string
}

export const EMPTY_ROLL: RollFormValues = {
  title: "",
  camera: "",
  lens: "",
  film_type: "",
  start_date: "",
  end_date: "",
  building: "",
  folder: "",
  archive_serial: "",
  notes: "",
}

/** The select's "nothing chosen" value; the API stores NULL for it (R#8). */
export const NONE = "__none__"

export function toRollPayload(values: RollFormValues) {
  const text = (value: string) => (value.trim() === "" ? null : value.trim())
  return {
    title: values.title.trim(),
    camera: text(values.camera),
    lens: text(values.lens),
    film_type: text(values.film_type),
    start_date: text(values.start_date),
    end_date: text(values.end_date),
    building: text(values.building),
    folder: text(values.folder),
    archive_serial: text(values.archive_serial),
    notes: text(values.notes),
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
  onChange,
  cameras,
  lenses,
  filmstocks,
  idPrefix = "roll",
}: {
  values: RollFormValues
  onChange: (patch: Partial<RollFormValues>) => void
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
  idPrefix?: string
}) {
  const selectedCamera = cameras.find((c) => c.name === values.camera) || null
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
            value={values.camera || NONE}
            onValueChange={(value) => onChange({ camera: value === NONE ? "" : value })}
          >
            <SelectTrigger id={`${idPrefix}-camera`}>
              <SelectValue placeholder="Select camera" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Not recorded</SelectItem>
              {cameras.map((camera) => (
                <SelectItem key={camera.id} value={camera.name}>
                  {camera.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-lens`}>Lens</Label>
          <Select
            value={values.lens || NONE}
            onValueChange={(value) => onChange({ lens: value === NONE ? "" : value })}
          >
            <SelectTrigger id={`${idPrefix}-lens`}>
              <SelectValue placeholder="Select lens" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Not recorded</SelectItem>
              {usableLenses.map((lens) => (
                <SelectItem key={lens.id} value={lens.name}>
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

      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-film`}>Film stock</Label>
        <Select
          value={values.film_type || NONE}
          onValueChange={(value) => onChange({ film_type: value === NONE ? "" : value })}
        >
          <SelectTrigger id={`${idPrefix}-film`}>
            <SelectValue placeholder="Select film stock" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>Not recorded</SelectItem>
            {filmstocks.map((stock) => (
              <SelectItem key={stock.id} value={stock.name}>
                {stock.name}
                {stock.iso ? ` · ISO ${stock.iso}` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
