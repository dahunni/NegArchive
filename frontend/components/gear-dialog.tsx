"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Loader2, Upload } from "lucide-react"

import {
  ACCEPTED_IMAGE_TYPES,
  ApiError,
  type Camera,
  type Filmstock,
  type Lens,
  createCamera,
  createFilmstock,
  createLens,
  errorMessage,
  fieldFor,
  updateCamera,
  updateFilmstock,
  updateLens,
  uploadCameraImage,
  uploadFilmstockImage,
  uploadLensImage,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { FILM_FORMATS, FieldError, NONE } from "@/components/roll-fields"
import { useToast } from "@/hooks/use-toast"

export type GearKind = "camera" | "lens" | "filmstock"
export type GearItem = Camera | Lens | Filmstock

/** The film kinds the API accepts, not "the kinds already in use" (R#21). */
const FILM_KINDS = [
  { value: "black_and_white", label: "Black and white" },
  { value: "color", label: "Colour negative" },
  { value: "slide", label: "Slide / reversal" },
  { value: "motion_picture", label: "Motion picture" },
]

const LABELS: Record<GearKind, string> = { camera: "Camera", lens: "Lens", filmstock: "Film stock" }

interface Draft {
  name: string
  mount: string
  notes: string
  manufacturer: string
  format: string
  iso: string
  kind: string
  expired: boolean
  expiration_date: string
}

const EMPTY: Draft = {
  name: "",
  mount: "",
  notes: "",
  manufacturer: "",
  format: "",
  iso: "",
  kind: "black_and_white",
  expired: false,
  expiration_date: "",
}

function toDraft(kind: GearKind, item: GearItem | null): Draft {
  if (!item) return EMPTY
  if (kind === "filmstock") {
    const stock = item as Filmstock
    return {
      ...EMPTY,
      name: stock.name ?? "",
      manufacturer: stock.manufacturer ?? "",
      format: stock.format ?? "",
      iso: stock.iso ? String(stock.iso) : "",
      kind: stock.kind ?? "black_and_white",
      expired: Boolean(stock.expired),
      expiration_date: stock.expiration_date ?? "",
    }
  }
  const gear = item as Camera | Lens
  return { ...EMPTY, name: gear.name ?? "", mount: gear.mount ?? "", notes: gear.notes ?? "" }
}

/**
 * One dialog for the whole catalog. Errors come back from the API with a code, so a
 * duplicate name lands on the name field instead of in a generic "Failed to save".
 */
export function GearDialog({
  kind,
  item,
  open,
  onOpenChange,
}: {
  kind: GearKind
  item: GearItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const router = useRouter()
  const { toast } = useToast()
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setDraft(toDraft(kind, item))
    setFile(null)
    setErrors({})
  }, [open, kind, item])

  const save = async () => {
    setSaving(true)
    setErrors({})
    try {
      let savedId: number
      if (kind === "camera") {
        const payload = { name: draft.name, mount: draft.mount || null, notes: draft.notes || null }
        savedId = item ? (await updateCamera(item.id, payload)).id : (await createCamera(payload)).id
        if (file) await uploadCameraImage(savedId, file)
      } else if (kind === "lens") {
        const payload = { name: draft.name, mount: draft.mount || null, notes: draft.notes || null }
        savedId = item ? (await updateLens(item.id, payload)).id : (await createLens(payload)).id
        if (file) await uploadLensImage(savedId, file)
      } else {
        const payload = {
          name: draft.name,
          manufacturer: draft.manufacturer || null,
          format: draft.format || null,
          iso: draft.iso === "" ? null : Number(draft.iso),
          kind: draft.kind,
          expired: draft.expired,
          expiration_date: draft.expiration_date || null,
        } as Partial<Filmstock>
        savedId = item ? (await updateFilmstock(item.id, payload)).id : (await createFilmstock(payload)).id
        if (file) await uploadFilmstockImage(savedId, file)
      }
      toast({ title: `${LABELS[kind]} ${item ? "saved" : "added"}` })
      router.refresh()
      onOpenChange(false)
    } catch (error) {
      const field = error instanceof ApiError ? fieldFor(error) : null
      if (field) {
        setErrors({ [field]: (error as ApiError).message })
      } else {
        toast({ title: "Could not save", description: errorMessage(error), variant: "destructive" })
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto" data-testid="gear-dialog">
        <DialogHeader>
          <DialogTitle>
            {item ? `Edit ${LABELS[kind].toLowerCase()}` : `New ${LABELS[kind].toLowerCase()}`}
          </DialogTitle>
          <DialogDescription>Part of the gear catalog rolls can refer to.</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="gear-name">
              Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="gear-name"
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              placeholder={kind === "filmstock" ? "Kodak Portra 400" : "Nikon F3"}
              aria-invalid={Boolean(errors.name)}
            />
            <FieldError message={errors.name} />
          </div>

          {kind !== "filmstock" ? (
            <div className="space-y-2">
              <Label htmlFor="gear-mount">Mount</Label>
              <Input
                id="gear-mount"
                value={draft.mount}
                onChange={(event) => setDraft({ ...draft, mount: event.target.value })}
                placeholder="Nikon F"
              />
              <p className="type-meta">Lenses are matched to cameras by mount when you pick gear for a roll.</p>
            </div>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="gear-manufacturer">Manufacturer</Label>
                  <Input
                    id="gear-manufacturer"
                    value={draft.manufacturer}
                    onChange={(event) => setDraft({ ...draft, manufacturer: event.target.value })}
                    placeholder="Kodak"
                    aria-invalid={Boolean(errors.manufacturer)}
                  />
                  <FieldError message={errors.manufacturer} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="gear-format">Format</Label>
                  <Select
                    value={draft.format || NONE}
                    onValueChange={(value) =>
                      setDraft({ ...draft, format: value === NONE ? "" : value })
                    }
                  >
                    <SelectTrigger id="gear-format" className="w-full">
                      <SelectValue placeholder="Not recorded" />
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
                  <FieldError message={errors.format} />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="gear-iso">ISO</Label>
                  <Input
                    id="gear-iso"
                    inputMode="numeric"
                    value={draft.iso}
                    onChange={(event) => setDraft({ ...draft, iso: event.target.value })}
                    placeholder="400"
                    aria-invalid={Boolean(errors.iso)}
                  />
                  <FieldError message={errors.iso} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="gear-kind">Kind</Label>
                  <Select value={draft.kind} onValueChange={(value) => setDraft({ ...draft, kind: value })}>
                    <SelectTrigger id="gear-kind" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {FILM_KINDS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FieldError message={errors.kind} />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="gear-expiry">Expiry date</Label>
                <Input
                  id="gear-expiry"
                  type="date"
                  value={draft.expiration_date}
                  onChange={(event) => setDraft({ ...draft, expiration_date: event.target.value })}
                />
              </div>

              <div className="flex items-center gap-2">
                <Checkbox
                  id="gear-expired"
                  checked={draft.expired}
                  onCheckedChange={(checked) => setDraft({ ...draft, expired: checked === true })}
                />
                <Label htmlFor="gear-expired" className="font-normal">
                  This stock is expired
                </Label>
              </div>
            </>
          )}

          {kind !== "filmstock" ? (
            <div className="space-y-2">
              <Label htmlFor="gear-notes">Notes</Label>
              <Textarea
                id="gear-notes"
                value={draft.notes}
                onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
                rows={3}
              />
            </div>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="gear-image">Catalog photo</Label>
            <Input
              id="gear-image"
              type="file"
              // The API's allowlist, so the picker cannot offer a file it will reject (R#18).
              accept={ACCEPTED_IMAGE_TYPES}
              className="cursor-pointer"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            {file ? (
              <p className="flex items-center gap-2 type-meta">
                <Upload className="h-3 w-3" />
                {file.name}
              </p>
            ) : null}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={save} disabled={saving} data-testid="gear-save">
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
