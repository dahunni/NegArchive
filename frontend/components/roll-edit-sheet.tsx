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
  errorMessage,
  fieldFor,
  updateFilm,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useToast } from "@/hooks/use-toast"
import {
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
}: {
  film: Film | null
  open: boolean
  onOpenChange: (open: boolean) => void
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
}) {
  const router = useRouter()
  const { toast } = useToast()
  const [values, setValues] = useState<RollFormValues>(() => (film ? fromFilm(film) : ({} as RollFormValues)))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open && film) {
      setValues(fromFilm(film))
      setErrors({})
    }
  }, [open, film])

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
            <StorageFields values={values} onChange={change} idPrefix="edit" />
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
