"use client"

import { useState } from "react"
import { Check, Loader2 } from "lucide-react"

import { type Film, ROLL_STATUSES, type RollStatus, errorMessage, setRollStatus } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useToast } from "@/hooks/use-toast"

const TIMESTAMP: Record<RollStatus, keyof Film> = {
  loaded: "loaded_at",
  shot: "shot_at",
  at_lab: "lab_sent_at",
  back: "lab_back_at",
  scanned: "scanned_at",
  sleeved: "sleeved_at",
}

/**
 * The roll lifecycle as six steps you can click (M4). The current step is
 * filled; the ones before it show when they happened. Clicking any step sets it —
 * forwards or backwards, because rolls do come back uncut sometimes.
 */
export function StatusStepper({
  film,
  onChanged,
  compact = false,
}: {
  film: Film
  onChanged?: (film: Film) => void
  compact?: boolean
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState<RollStatus | null>(null)
  const currentIndex = ROLL_STATUSES.findIndex((s) => s.value === film.status)

  const set = async (status: RollStatus) => {
    if (status === film.status) return
    setBusy(status)
    try {
      const updated = await setRollStatus(film.id, status)
      onChanged?.(updated)
      toast({ title: `${updated.archive_serial ?? updated.title}: ${updated.status_label}` })
    } catch (error) {
      toast({ title: "Could not change the status", description: errorMessage(error), variant: "destructive" })
    } finally {
      setBusy(null)
    }
  }

  return (
    <ol className={cn("flex flex-wrap gap-1", compact ? "" : "gap-2")} data-testid="status-stepper" aria-label="Roll status">
      {ROLL_STATUSES.map((step, index) => {
        const done = index <= currentIndex
        const current = index === currentIndex
        const when = film[TIMESTAMP[step.value]] as string | null
        return (
          // The timestamp is on the page, not only in a `title` a touch screen and a
          // screen reader both miss (R#100).
          <li key={step.value} className="flex flex-col items-center gap-0.5">
            <button
              type="button"
              onClick={() => set(step.value)}
              disabled={busy !== null}
              title={when ? `${step.label} · ${formatDateTime(when)}` : `Mark as ${step.label.toLowerCase()}`}
              aria-current={current ? "step" : undefined}
              data-testid={`status-${step.value}`}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors",
                compact ? "min-h-8" : "min-h-9",
                current
                  ? "border-primary bg-primary text-primary-foreground"
                  : done
                    ? "border-primary/40 bg-secondary text-secondary-foreground"
                    : "border-border text-muted-foreground hover:bg-secondary/60",
              )}
            >
              {busy === step.value ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : done && !current ? (
                <Check className="h-3 w-3" />
              ) : null}
              {compact ? step.short : step.label}
            </button>
            {when ? (
              <span className="type-meta px-1 text-center" data-testid={`status-when-${step.value}`}>
                {formatDateTime(when)}
              </span>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}

/** A small badge with the status label, for lists. */
export function StatusBadge({ status }: { status: RollStatus }) {
  const entry = ROLL_STATUSES.find((s) => s.value === status)
  const tone =
    status === "sleeved"
      ? "border-primary/40 bg-secondary text-secondary-foreground"
      : status === "loaded" || status === "shot"
        ? "border-amber-500/50 text-amber-700 dark:text-amber-400"
        : status === "at_lab"
          ? "border-sky-500/50 text-sky-700 dark:text-sky-400"
          : "border-border text-muted-foreground"
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", tone)} data-testid="status-badge">
      {entry?.label ?? status}
    </span>
  )
}
