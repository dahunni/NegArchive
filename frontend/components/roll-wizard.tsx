"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft, ArrowRight, Loader2, Plus } from "lucide-react"

import {
  ApiError,
  ERROR_FIELDS,
  type Camera,
  type Film,
  type Filmstock,
  type Lens,
  createFilm,
  errorMessage,
  uploadRollFile,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useToast } from "@/hooks/use-toast"
import { UploadZone } from "@/components/upload-zone"
import {
  EMPTY_ROLL,
  GearFields,
  type RollFormValues,
  StorageFields,
  TitleAndDates,
  toRollPayload,
} from "@/components/roll-fields"

/** Last used gear, so the next roll off the same camera is two clicks. */
const REMEMBERED = "negarchive.lastGear"

function readRemembered(): Partial<RollFormValues> {
  if (typeof window === "undefined") return {}
  try {
    const raw = window.localStorage.getItem(REMEMBERED)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    return {
      camera: typeof parsed.camera === "string" ? parsed.camera : "",
      lens: typeof parsed.lens === "string" ? parsed.lens : "",
      film_type: typeof parsed.film_type === "string" ? parsed.film_type : "",
    }
  } catch {
    return {}
  }
}

function remember(values: RollFormValues) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(
      REMEMBERED,
      JSON.stringify({ camera: values.camera, lens: values.lens, film_type: values.film_type }),
    )
  } catch {
    // private mode or storage disabled: remembering gear is a convenience, not a feature
  }
}

const STEPS = ["Roll", "Gear & film", "Storage"] as const

export function RollWizard({
  open,
  onOpenChange,
  cameras,
  lenses,
  filmstocks,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
}) {
  const router = useRouter()
  const { toast } = useToast()
  const [step, setStep] = useState(0)
  const [values, setValues] = useState<RollFormValues>(EMPTY_ROLL)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [created, setCreated] = useState<Film | null>(null)
  const [uploadedCount, setUploadedCount] = useState(0)

  // A fresh dialog every time it opens, with the last used gear prefilled.
  useEffect(() => {
    if (!open) return
    setStep(0)
    setErrors({})
    setCreated(null)
    setUploadedCount(0)
    setValues({ ...EMPTY_ROLL, ...readRemembered() })
  }, [open])

  const change = (patch: Partial<RollFormValues>) => {
    setValues((current) => ({ ...current, ...patch }))
    setErrors((current) => {
      const next = { ...current }
      for (const key of Object.keys(patch)) delete next[key]
      return next
    })
  }

  const handleCreate = async () => {
    setSaving(true)
    setErrors({})
    try {
      const film = await createFilm(toRollPayload(values))
      remember(values)
      setCreated(film)
      setStep(STEPS.length) // the upload step
      router.refresh()
    } catch (error) {
      if (error instanceof ApiError) {
        const field = ERROR_FIELDS[error.code]
        if (field) {
          setErrors({ [field]: error.message })
          // send the user back to the step that owns the field
          setStep(field === "title" || field.endsWith("_date") ? 0 : 2)
          setSaving(false)
          return
        }
      }
      toast({
        title: "Could not create the roll",
        description: errorMessage(error),
        variant: "destructive",
      })
    } finally {
      setSaving(false)
    }
  }

  const finish = () => {
    onOpenChange(false)
    if (created) router.push(`/films/${created.id}`)
  }

  const onUploadStep = step === STEPS.length

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl" data-testid="roll-wizard">
        <DialogHeader>
          <DialogTitle>{onUploadStep ? `Add scans to “${created?.title}”` : "New roll"}</DialogTitle>
          <DialogDescription>
            {onUploadStep
              ? "Drop the scans in now, or open the roll and do it later."
              : `Step ${step + 1} of ${STEPS.length} · ${STEPS[step]}`}
          </DialogDescription>
        </DialogHeader>

        {!onUploadStep ? (
          <div className="space-y-6 py-2">
            {step === 0 ? <TitleAndDates values={values} errors={errors} onChange={change} idPrefix="wizard" /> : null}
            {step === 1 ? (
              <GearFields
                values={values}
                onChange={change}
                cameras={cameras}
                lenses={lenses}
                filmstocks={filmstocks}
                idPrefix="wizard"
              />
            ) : null}
            {step === 2 ? <StorageFields values={values} onChange={change} idPrefix="wizard" /> : null}
          </div>
        ) : (
          <div className="space-y-4 py-2">
            {created ? (
              <UploadZone
                upload={(file, onProgress) => uploadRollFile(created.id, file, onProgress)}
                onUploaded={(images) => {
                  setUploadedCount((count) => count + images.length)
                  router.refresh()
                }}
                hint="Drop this roll's scans here"
              />
            ) : null}
            {uploadedCount > 0 ? (
              <p className="type-body text-muted-foreground">
                {uploadedCount} frame{uploadedCount === 1 ? "" : "s"} added so far.
              </p>
            ) : null}
          </div>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          <div>
            {step > 0 && !onUploadStep ? (
              <Button type="button" variant="ghost" onClick={() => setStep(step - 1)} disabled={saving}>
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back
              </Button>
            ) : null}
          </div>
          <div className="flex gap-2">
            {onUploadStep ? (
              <Button type="button" onClick={finish}>
                Open roll
              </Button>
            ) : step < STEPS.length - 1 ? (
              <Button
                type="button"
                onClick={() => {
                  if (step === 0 && values.title.trim() === "") {
                    setErrors({ title: "Give the roll a title so you can find it again." })
                    return
                  }
                  setStep(step + 1)
                }}
              >
                Next
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            ) : (
              <Button type="button" onClick={handleCreate} disabled={saving}>
                {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
                Create roll
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
