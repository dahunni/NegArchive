"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { AlertTriangle, ArrowRight, FileText, ListOrdered, Loader2, MoveRight, Undo2 } from "lucide-react"

import { type RenumberMode, type RenumberResult, errorMessage, renumberFrames } from "@/lib/api"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useToast } from "@/hooks/use-toast"

const PREVIEW_DEBOUNCE_MS = 150

const MODES: { value: RenumberMode; label: string; hint: string; icon: typeof ListOrdered }[] = [
  {
    value: "sequential",
    label: "Number in order",
    hint: "1, 2, 3… in the current order. Closes gaps and resolves duplicates.",
    icon: ListOrdered,
  },
  {
    value: "reverse",
    label: "Reverse the order",
    hint: "The last frame becomes the first. For a roll scanned tail first.",
    icon: Undo2,
  },
  {
    value: "shift",
    label: "Shift every number",
    hint: "Add or subtract the same amount everywhere. For a scanner that counted from 0.",
    icon: MoveRight,
  },
  {
    value: "from_filenames",
    label: "Read the filenames again",
    hint: "The number the scanner put in each file's name. A file without one keeps its number.",
    icon: FileText,
  },
]

/**
 * Renumber a roll's frames in one go (M7).
 *
 * Every option change asks the backend for a dry run and shows the plan —
 * "7 → 3" for each frame, and which numbers would end up used twice — so the
 * button says exactly what it will do before it does it. `ids` scopes it to a
 * selection from the bulk bar; without it, the whole roll.
 */
export function RenumberDialog({
  open,
  onOpenChange,
  rollId,
  ids,
  onDone,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  rollId: number
  /** A selection; undefined or empty means every frame of the roll. */
  ids?: number[]
  onDone?: () => void
}) {
  const router = useRouter()
  const { toast } = useToast()
  const [mode, setMode] = useState<RenumberMode>("sequential")
  const [start, setStart] = useState("1")
  const [step, setStep] = useState("1")
  const [offset, setOffset] = useState("1")
  const [preview, setPreview] = useState<RenumberResult | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const request = useRef(0)

  const scoped = ids && ids.length > 0 ? ids : undefined
  const options = {
    mode,
    ids: scoped,
    start: mode === "sequential" || mode === "reverse" ? Number(start) : undefined,
    step: mode === "sequential" || mode === "reverse" ? Number(step) : undefined,
    offset: mode === "shift" ? Number(offset) : undefined,
  }
  const optionsKey = JSON.stringify(options)

  // The plan, refreshed after every change of the options.
  useEffect(() => {
    if (!open) return
    const ticket = (request.current += 1)
    const handle = window.setTimeout(async () => {
      try {
        const result = await renumberFrames(rollId, { ...JSON.parse(optionsKey), dryRun: true })
        if (ticket !== request.current) return
        setPreview(result)
        setPreviewError(null)
      } catch (error) {
        if (ticket !== request.current) return
        setPreview(null)
        setPreviewError(errorMessage(error, "Could not work out the new numbers."))
      }
    }, PREVIEW_DEBOUNCE_MS)
    return () => window.clearTimeout(handle)
  }, [open, rollId, optionsKey])

  const apply = async () => {
    setBusy(true)
    try {
      const result = await renumberFrames(rollId, { ...options, dryRun: false })
      toast({
        title: `${pluralize(result.updated, "frame")} renumbered`,
        description: result.conflicts.length
          ? `Numbers used more than once: ${result.conflicts.join(", ")}.`
          : undefined,
      })
      onOpenChange(false)
      onDone?.()
      router.refresh()
    } catch (error) {
      toast({ title: "Could not renumber", description: errorMessage(error), variant: "destructive" })
    } finally {
      setBusy(false)
    }
  }

  const changes = preview?.plan.filter((item) => item.from !== item.to) ?? []
  const needsStart = mode === "sequential" || mode === "reverse"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-0 p-0 sm:max-w-2xl" data-testid="renumber-dialog">
        <DialogHeader className="border-b border-border px-6 py-4">
          <DialogTitle>Renumber {scoped ? pluralize(scoped.length, "selected frame") : "the frames"}</DialogTitle>
          <DialogDescription>
            Nothing is written until you press Apply. The list below shows every change.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="How to renumber">
            {MODES.map((entry) => {
              const Icon = entry.icon
              const active = entry.value === mode
              return (
                <button
                  key={entry.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setMode(entry.value)}
                  data-testid={`renumber-mode-${entry.value}`}
                  className={cn(
                    "flex min-h-16 items-start gap-3 rounded-lg border p-3 text-left transition-colors",
                    active ? "border-primary bg-secondary" : "border-border hover:bg-secondary/50",
                  )}
                >
                  <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{entry.label}</span>
                    <span className="block type-meta">{entry.hint}</span>
                  </span>
                </button>
              )
            })}
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            {needsStart ? (
              <>
                <div className="w-28 space-y-1.5">
                  <Label htmlFor="renumber-start">First number</Label>
                  <Input
                    id="renumber-start"
                    type="number"
                    min={0}
                    inputMode="numeric"
                    value={start}
                    onChange={(event) => setStart(event.target.value)}
                    className="h-11"
                    data-testid="renumber-start"
                  />
                </div>
                <div className="w-28 space-y-1.5">
                  <Label htmlFor="renumber-step">Step</Label>
                  <Input
                    id="renumber-step"
                    type="number"
                    min={1}
                    inputMode="numeric"
                    value={step}
                    onChange={(event) => setStep(event.target.value)}
                    className="h-11"
                  />
                </div>
              </>
            ) : null}
            {mode === "shift" ? (
              <div className="w-36 space-y-1.5">
                <Label htmlFor="renumber-offset">Add to each number</Label>
                <Input
                  id="renumber-offset"
                  type="number"
                  inputMode="numeric"
                  value={offset}
                  onChange={(event) => setOffset(event.target.value)}
                  className="h-11"
                  data-testid="renumber-offset"
                />
              </div>
            ) : null}
          </div>

          <div className="mt-4">
            {previewError ? (
              <p className="type-body text-destructive" role="alert">
                {previewError}
              </p>
            ) : preview === null ? (
              <p className="type-meta">
                <Loader2 className="mr-1 inline h-3 w-3 animate-spin" aria-hidden />
                Working out the new numbers…
              </p>
            ) : (
              <>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="type-meta uppercase tracking-wide">
                    {changes.length === 0
                      ? "Nothing would change"
                      : `${pluralize(changes.length, "frame")} would change`}
                  </h3>
                  {preview.plan.length > changes.length ? (
                    <span className="type-meta">{preview.plan.length - changes.length} already right</span>
                  ) : null}
                </div>
                {preview.conflicts.length > 0 ? (
                  <p
                    role="status"
                    data-testid="renumber-conflicts"
                    className="mt-2 flex items-start gap-2 rounded-md border border-border bg-secondary p-2 text-sm"
                  >
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                    <span>
                      Afterwards {preview.conflicts.length === 1 ? "number" : "numbers"}{" "}
                      <span className="type-numeric font-medium">{preview.conflicts.join(", ")}</span>{" "}
                      {preview.conflicts.length === 1 ? "is" : "are"} used more than once. That is allowed, but check
                      it is what you mean.
                    </span>
                  </p>
                ) : null}
                {changes.length > 0 ? (
                  <ul className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2" data-testid="renumber-plan">
                    {changes.map((item) => (
                      <li key={item.id} className="flex items-center gap-2 text-sm">
                        <span className="type-numeric w-10 text-right text-muted-foreground">{item.from ?? "—"}</span>
                        <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
                        <span className="type-numeric w-10 font-medium">{item.to ?? "—"}</span>
                        <span className="truncate type-meta">{item.original_filename ?? `frame #${item.id}`}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            )}
          </div>
        </div>

        <DialogFooter className="border-t border-border px-6 py-3">
          <Button variant="ghost" className="min-h-11" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            className="min-h-11"
            onClick={apply}
            disabled={busy || !preview || changes.length === 0}
            data-testid="renumber-apply"
          >
            {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {changes.length > 0 ? `Renumber ${pluralize(changes.length, "frame")}` : "Renumber"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
