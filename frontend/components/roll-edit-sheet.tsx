"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Loader2 } from "lucide-react"

import {
  ApiError,
  type Camera,
  type Film,
  type Filmstock,
  type Lens,
  type Location,
  errorMessage,
  fieldFor,
  updateFilm,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useToast } from "@/hooks/use-toast"
import {
  EMPTY_ROLL,
  GearFields,
  type RollFormValues,
  StorageFields,
  TitleAndDates,
  fromFilm,
  toRollPayload,
} from "@/components/roll-fields"

/**
 * Editing a roll is a side panel, not a page: the list or the workspace stays visible
 * behind it and is still there after saving (router.refresh() brings the new values).
 */
export function RollEditSheet({
  film,
  open,
  onOpenChange,
  cameras,
  lenses,
  filmstocks,
  locations = [],
}: {
  film: Film | null
  open: boolean
  onOpenChange: (open: boolean) => void
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
  locations?: Location[]
}) {
  const router = useRouter()
  const { toast } = useToast()
  // Never `{}`: every input below is controlled, and an undefined value makes React
  // hand it an uncontrolled field it then complains about on the first keystroke (R#75).
  const [values, setValues] = useState<RollFormValues>(() => (film ? fromFilm(film) : EMPTY_ROLL))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  // Keyed on the roll's **id**, not the object: a background refresh hands down a new
  // Film with the same id, and resetting on that would throw away what is being typed.
  const filmId = film?.id ?? null
  useEffect(() => {
    if (!open || !film) return
    setValues(fromFilm(film))
    setErrors({})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, filmId])

  const change = (patch: Partial<RollFormValues>) => {
    setValues((current) => ({ ...current, ...patch }))
    setErrors((current) => {
      const next = { ...current }
      for (const key of Object.keys(patch)) delete next[key]
      return next
    })
  }

  const save = async () => {
    if (!film) return
    setSaving(true)
    setErrors({})
    try {
      await updateFilm(film.id, toRollPayload(values))
      toast({ title: "Roll saved" })
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
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg" data-testid="roll-edit-sheet">
        <SheetHeader>
          <SheetTitle>Edit roll</SheetTitle>
          <SheetDescription>Changes are saved to the archive when you press Save.</SheetDescription>
        </SheetHeader>

        {film ? (
          <div className="space-y-6 px-4">
            <TitleAndDates values={values} errors={errors} onChange={change} idPrefix="edit" />
            <GearFields
              values={values}
              errors={errors}
              onChange={change}
              cameras={cameras}
              lenses={lenses}
              filmstocks={filmstocks}
              idPrefix="edit"
            />
            <StorageFields
              values={values}
              errors={errors}
              onChange={change}
              idPrefix="edit"
              locations={locations}
              serialLocked={Boolean(film.label_printed_at)}
            />
          </div>
        ) : null}

        <SheetFooter>
          <Button onClick={save} disabled={saving}>
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Save
          </Button>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
