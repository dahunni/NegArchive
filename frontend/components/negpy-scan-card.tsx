"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { Camera, Loader2, RefreshCw } from "lucide-react"

import { type RollStatus, type ScanPlan, errorMessage, getNegpyScanPlan, scanLibraryRoot } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { CopyValue } from "@/components/copy-value"
import { useToast } from "@/hooks/use-toast"

/**
 * "Scan with NegPy" (roadmap M6.1).
 *
 * NegPy's Live View & Scan writes `<output>/<roll name>/<roll name>_Frame001.ARW`.
 * Give it the share's `rolls/` folder and this roll's serial as the roll name, and
 * the watcher files every frame onto this roll — film, camera and lifecycle already
 * on it — within one sweep. So the card does what the handoff dialog does: hands
 * over the two strings to paste, says what will happen, and offers to look now.
 */
export function NegpyScanCard({
  rollId,
  status,
  frameCount,
  onScanned,
}: {
  rollId: number
  status: RollStatus
  frameCount: number
  /** Called after a manual check found frames, so the page can reload them. */
  onScanned?: () => void
}) {
  const { toast } = useToast()
  const [plan, setPlan] = useState<ScanPlan | null>(null)
  const [checking, setChecking] = useState(false)
  // Shown by default while there is nothing to show yet; a scanned roll can still
  // open it to scan a second strip into the same folder.
  const [open, setOpen] = useState(frameCount === 0 || status === "back")

  useEffect(() => {
    let cancelled = false
    getNegpyScanPlan(rollId)
      .then((p) => {
        if (!cancelled) setPlan(p)
      })
      .catch(() => {
        /* the card simply does not render; the roll page works without it */
      })
    return () => {
      cancelled = true
    }
  }, [rollId])

  const checkNow = useCallback(async () => {
    if (!plan?.root_id) return
    setChecking(true)
    try {
      const result = await scanLibraryRoot(plan.root_id)
      const found = result.frames_added + result.frames_rehomed
      // "Check now" sweeps the whole root, not just this roll's folder: frames can
      // have landed on any roll, so only say "this roll" when the sweep says so.
      const onThisRoll = result.roll_ids.includes(rollId)
      toast({
        title:
          found === 0
            ? "Nothing new on the share yet"
            : onThisRoll
              ? `${found} frame${found === 1 ? "" : "s"} arrived`
              : `${found} frame${found === 1 ? "" : "s"} filed elsewhere`,
        description:
          found === 0
            ? plan.example_file
              ? `Looking for ${plan.folder} — the first file will be ${plan.example_file}.`
              : undefined
            : onThisRoll
              ? "Filed onto this roll."
              : result.summary,
      })
      if (onThisRoll) onScanned?.()
    } catch (error) {
      toast({ title: "Could not check the share", description: errorMessage(error), variant: "destructive" })
    } finally {
      setChecking(false)
    }
  }, [plan, rollId, toast, onScanned])

  if (!plan) return null

  // The path as the Mac sees it (/Volumes/<share>/rolls): the container's path is
  // useless on a laptop, and the backend knows the share's name.
  const outputForMac = plan.mac_output_dir || plan.output_dir

  return (
    <section
      className="rounded-lg border border-border bg-card p-3 sm:p-4"
      data-testid="negpy-scan-card"
      aria-labelledby="negpy-scan-heading"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="negpy-scan-heading" className="flex items-center gap-2 type-title">
          <Camera className="h-4 w-4 text-muted-foreground" aria-hidden />
          Scan with NegPy
        </h2>
        <div className="flex items-center gap-2">
          {plan.root_id ? (
            <Button variant="outline" size="sm" className="min-h-9" onClick={checkNow} disabled={checking}>
              {checking ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Check now
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" className="min-h-9" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? "Hide" : "Show"}
          </Button>
        </div>
      </div>

      {open ? (
        <div className="mt-3 space-y-3">
          {!plan.root_id ? (
            <p className="type-body">
              The share is not set up for live mode yet.{" "}
              <Link href="/settings" className="underline underline-offset-4">
                Press “Set up” under The share in Settings
              </Link>
              , then come back — the folder below is only watched once that has run.
            </p>
          ) : null}

          {plan.already_linked && plan.source_dir && plan.folder && plan.source_dir !== plan.folder ? (
            <p className="type-meta">
              This roll is already linked to <code className="type-numeric">{plan.source_dir}</code>; new scans
              belong in that folder. The lines below are for a roll that has none yet.
            </p>
          ) : null}

          <ol className="min-w-0 space-y-3 type-body">
            <li className="min-w-0">
              <span className="type-meta uppercase tracking-wide">1 · In NegPy → Live View &amp; Scan, set the output folder</span>
              <CopyValue value={outputForMac} label="the output folder" />
            </li>
            <li className="min-w-0">
              <span className="type-meta uppercase tracking-wide">2 · Name the roll after this one</span>
              {plan.roll_name ? (
                <CopyValue value={plan.roll_name} label="the roll name" />
              ) : (
                <p className="mt-1 type-meta">This roll has no serial yet — give it one above first.</p>
              )}
              {plan.example_file ? (
                <p className="mt-1 type-meta">
                  NegPy will then write <code className="type-numeric">{plan.example_file}</code>,{" "}
                  <code className="type-numeric">…Frame002.ARW</code> and so on into a folder of that name.
                </p>
              ) : null}
            </li>
            <li className="min-w-0">
              <span className="type-meta uppercase tracking-wide">3 · Shoot</span>
              <p className="mt-1 type-meta">
                {plan.watched && plan.interval_seconds
                  ? `The archive checks the share every ${plan.interval_seconds} s and files each frame onto this roll as it lands — the raw itself, never a copy. The roll is marked scanned with the first one.`
                  : "Turn the background checks on in Settings, or press “Check now” after shooting; the frames are filed onto this roll — the raw itself, never a copy."}
              </p>
            </li>
          </ol>
        </div>
      ) : null}
    </section>
  )
}
