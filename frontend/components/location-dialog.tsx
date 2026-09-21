"use client"

import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

import {
  ApiError,
  LOCATION_KINDS,
  type Location,
  type LocationKind,
  type LocationPatch,
  type SleeveLayout,
  createLocation,
  errorMessage,
  fieldFor,
  updateLocation,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { LocationPicker } from "@/components/location-picker"
import { FieldError } from "@/components/roll-fields"
import { useToast } from "@/hooks/use-toast"

/** Create or edit one node of the storage tree (M4). */
export function LocationDialog({
  open,
  onOpenChange,
  locations,
  layouts,
  item,
  parentId,
  defaultKind = "binder",
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  locations: Location[]
  layouts: SleeveLayout[]
  /** Editing this node; null creates a new one. */
  item: Location | null
  /** Preselected parent for a new node. */
  parentId?: number | null
  defaultKind?: LocationKind
  onSaved?: (node: Location) => void
}) {
  const { toast } = useToast()
  const [values, setValues] = useState({ kind: defaultKind as string, name: "", code: "", parent_id: "", capacity: "", sleeve_layout_id: "", notes: "" })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setErrors({})
    setValues({
      kind: item?.kind ?? defaultKind,
      name: item?.name ?? "",
      code: item?.code ?? "",
      parent_id: item ? (item.parent_id === null ? "" : String(item.parent_id)) : parentId ? String(parentId) : "",
      capacity: item?.capacity === null || item?.capacity === undefined ? "" : String(item.capacity),
      sleeve_layout_id: item?.sleeve_layout_id ? String(item.sleeve_layout_id) : "",
      notes: item?.notes ?? "",
    })
  }, [open, item, parentId, defaultKind])

  const save = async () => {
    const typedCapacity = values.capacity.trim()
    const capacity = typedCapacity === "" ? null : Number(typedCapacity)
    // `Number("12 pages")` is NaN, and sending it as null would quietly clear the
    // capacity the node already has (R#74). Say so on the field and do not submit.
    if (capacity !== null && (!Number.isFinite(capacity) || capacity <= 0)) {
      setErrors({ capacity: "How many it holds has to be a number." })
      return
    }
    setSaving(true)
    setErrors({})
    const payload: LocationPatch = {
      kind: values.kind as LocationKind,
      name: values.name.trim(),
      code: values.code.trim() || null,
      parent_id: values.parent_id ? Number(values.parent_id) : null,
      capacity: capacity === null ? null : Math.trunc(capacity),
      sleeve_layout_id: values.sleeve_layout_id ? Number(values.sleeve_layout_id) : null,
      notes: values.notes.trim() || null,
    }
    try {
      const node = item ? await updateLocation(item.id, payload) : await createLocation(payload)
      toast({ title: item ? "Location saved" : "Location created", description: node.path ?? node.label })
      onSaved?.(node)
      onOpenChange(false)
    } catch (error) {
      const field = error instanceof ApiError ? fieldFor(error) : null
      if (field) setErrors({ [field]: (error as ApiError).message })
      else toast({ title: "Could not save", description: errorMessage(error), variant: "destructive" })
    } finally {
      setSaving(false)
    }
  }

  const others = item ? locations.filter((n) => n.id !== item.id && !n.path_ids.includes(item.id)) : locations
  const isContainerOfPages = values.kind === "binder" || values.kind === "sleeve"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="location-dialog">
        <DialogHeader>
          <DialogTitle>{item ? `Edit ${item.label}` : "New location"}</DialogTitle>
          <DialogDescription>
            Buildings, shelves and rows organise; binders hold sleeve pages; sleeves hold one roll each; boxes and
            envelopes hold rolls loosely.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="loc-kind">Kind</Label>
              <Select value={values.kind} onValueChange={(kind) => setValues({ ...values, kind })}>
                <SelectTrigger id="loc-kind" className="h-11">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LOCATION_KINDS.map((kind) => (
                    <SelectItem key={kind.value} value={kind.value}>
                      {kind.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="loc-code">Code</Label>
              <Input
                id="loc-code"
                value={values.code}
                onChange={(e) => setValues({ ...values, code: e.target.value })}
                placeholder="B03"
                className="h-11 type-numeric"
              />
              <p className="type-meta">Short, printed on labels.</p>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-name">Name</Label>
            <Input
              id="loc-name"
              value={values.name}
              onChange={(e) => setValues({ ...values, name: e.target.value })}
              placeholder="Binder 3 — 2024"
              className="h-11"
              aria-invalid={Boolean(errors.name)}
              data-testid="location-name"
            />
            <FieldError message={errors.name} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-parent">Inside</Label>
            <LocationPicker
              id="loc-parent"
              locations={others}
              value={values.parent_id}
              onChange={(parent_id) => setValues({ ...values, parent_id })}
              placeholder="Top level"
            />
            <FieldError message={errors.parent_id} />
          </div>
          {isContainerOfPages ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {values.kind === "binder" ? (
                <div className="space-y-1.5">
                  <Label htmlFor="loc-capacity">Pages it holds</Label>
                  <Input
                    id="loc-capacity"
                    inputMode="numeric"
                    value={values.capacity}
                    onChange={(e) => setValues({ ...values, capacity: e.target.value })}
                    placeholder="unlimited"
                    className="h-11"
                    aria-invalid={Boolean(errors.capacity)}
                  />
                  <FieldError message={errors.capacity} />
                </div>
              ) : null}
              <div className="space-y-1.5">
                <Label htmlFor="loc-layout">Sleeve layout</Label>
                <Select
                  value={values.sleeve_layout_id || "__inherit__"}
                  onValueChange={(v) => setValues({ ...values, sleeve_layout_id: v === "__inherit__" ? "" : v })}
                >
                  <SelectTrigger id="loc-layout" className="h-11">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__inherit__">Inherit (default PrintFile 7 × 6)</SelectItem>
                    {layouts.map((layout) => (
                      <SelectItem key={layout.id} value={String(layout.id)}>
                        {layout.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : values.kind === "box" || values.kind === "envelope" ? (
            <div className="space-y-1.5">
              <Label htmlFor="loc-capacity">Rolls it holds</Label>
              <Input
                id="loc-capacity"
                inputMode="numeric"
                value={values.capacity}
                onChange={(e) => setValues({ ...values, capacity: e.target.value })}
                placeholder="unlimited"
                className="h-11"
                aria-invalid={Boolean(errors.capacity)}
              />
              <FieldError message={errors.capacity} />
            </div>
          ) : null}
          <div className="space-y-1.5">
            <Label htmlFor="loc-notes">Notes</Label>
            <Textarea id="loc-notes" rows={2} value={values.notes} onChange={(e) => setValues({ ...values, notes: e.target.value })} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={save} disabled={saving || !values.name.trim()} data-testid="location-save">
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {item ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
