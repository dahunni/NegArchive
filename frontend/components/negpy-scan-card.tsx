"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { Camera, Check, Copy, Loader2, RefreshCw } from "lucide-react"

import {
  type ScanPlan,
  type SmbStatus,
  errorMessage,
  getNegpyScanPlan,
  getSmbStatus,
  scanLibraryRoot,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
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
  status: string
  frameCount: number
  /** Called after a manual check found frames, so the page can reload them. */
  onScanned?: () => void
}) {
  const { toast } = useToast()
  const [plan, setPlan] = useState<ScanPlan | null>(null)
  const [smb, setSmb] = useState<SmbStatus | null>(null)
  const [checking, setChecking] = useState(false)
  // Shown by default while there is nothing to show yet; a scanned roll can still
  // open it to scan a second strip into the same folder.
  const [open, setOpen] = useState(frameCount === 0 || status === "back")

  useEffect(() => {
    let cancelled = false
    Promise.all([getNegpyScanPlan(rollId), getSmbStatus().catch(() => null)])
      .then(([p, s]) => {
        if (!cancelled) {
          setPlan(p)
          setSmb(s)
        }
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
      toast({
        title: found > 0 ? `${found} frame${found === 1 ? "" : "s"} arrived` : "Nothing new on the share yet",
        description:
          found > 0
            ? "Filed onto this roll."
            : plan.example_file
              ? `Looking for ${plan.folder} — the first file will be ${plan.example_file}.`
              : undefined,
      })
      if (found > 0) onScanned?.()
    } catch (error) {
      toast({ title: "Could not check the share", description: errorMessage(error), variant: "destructive" })
    } finally {
      setChecking(false)
    }
  }, [plan, toast, onScanned])

  if (!plan) return null

  // The path Finder mounts on the Mac, derived the same way the share settings do it:
  // /Volumes/<share>[/<folder>]/rolls. The container's path is useless on a laptop.
  const macBase = smb?.config.share
    ? `/Volumes/${smb.config.share}${smb.config.subpath ? `/${smb.config.subpath}` : ""}`
    : null
  const outputForMac = macBase ? `${macBase}/rolls` : plan.output_dir

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
          {!plan.mounted || !plan.root_id ? (
            <p className="type-body">
              The network share is not set up for live mode yet.{" "}
              <Link href="/settings" className="underline underline-offset-4">
                Mount it and press “Set up live mode” in Settings
              </Link>
              , then come back — the two lines below only work when NegPy and the archive see the same folder.
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
              <PathRow value={outputForMac} />
            </li>
            <li className="min-w-0">
              <span className="type-meta uppercase tracking-wide">2 · Name the roll after this one</span>
              {plan.roll_name ? (
                <PathRow value={plan.roll_name} />
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

/** A value with a copy button: it has to be pasted into another application. */
function PathRow({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="mt-1 flex min-w-0 items-center gap-2">
      <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 type-numeric text-sm" title={value}>
        {value}
      </code>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="min-h-9 shrink-0"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          } catch {
            /* clipboard blocked: the value is on screen and selectable */
          }
        }}
        aria-label={`Copy ${value}`}
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </Button>
    </div>
  )
}
