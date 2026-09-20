"use client"

import { useCallback, useEffect, useState } from "react"
import { Check, HardDrive, Loader2, RefreshCw } from "lucide-react"

import { type ShareStatus, errorMessage, getShare, setupShare, sweepInbox } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { CopyLine } from "@/components/share-settings"
import { useToast } from "@/hooks/use-toast"

/**
 * The share (roadmap M6.2, M6.3).
 *
 * The stack serves one folder over SMB itself, and everything NegPy and the
 * archive exchange is on it: inbox/ (exports, taken and cleared), rolls/ (camera
 * scans, linked), negpy-user/ (gear and presets), handoff/. This card is the
 * whole setup — the address to paste into Finder, one button for the server
 * side, the Mac steps with the share's own paths — and what has landed since.
 * Nothing here is configured in the browser but the two addresses under "This
 * machine": the share's name, user and password live in the Compose file.
 */
export function ShareCard({ onChanged }: { onChanged?: () => void }) {
  const { toast } = useToast()
  const [status, setStatus] = useState<ShareStatus | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setStatus(await getShare())
    } catch {
      /* the card stays quiet; the rest of Settings works without it */
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const setUp = async () => {
    setBusy("setup")
    try {
      const body = await setupShare()
      toast({ title: body.report.summary })
      await load()
      onChanged?.()
    } catch (error) {
      toast({ title: "Could not set the share up", description: errorMessage(error), variant: "destructive" })
    } finally {
      setBusy(null)
    }
  }

  const importNow = async () => {
    setBusy("import")
    try {
      const body = await sweepInbox()
      toast({
        title: body.result.imported > 0 ? body.result.summary : "Nothing new in the inbox",
        description: body.result.rejected.length
          ? `Left there: ${body.result.rejected.map((r) => r.name).slice(0, 3).join(", ")}${
              body.result.rejected.length > 3 ? "…" : ""
            }`
          : undefined,
      })
      await load()
      if (body.result.imported > 0) onChanged?.()
    } catch (error) {
      toast({ title: "Could not import", description: errorMessage(error), variant: "destructive" })
    } finally {
      setBusy(null)
    }
  }

  if (!status) return null
  const { share, live, inbox } = status
  const steps = live.client
  const waiting = inbox.pending.count
  const stuck = inbox.pending.files.filter((file) => !file.accepted)
  const interval = inbox.interval_seconds

  return (
    <section className="space-y-3" data-testid="share-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 type-section">
          <HardDrive className="h-4 w-4 text-muted-foreground" aria-hidden />
          The share
        </h2>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="min-h-9" onClick={importNow} disabled={busy !== null}>
            {busy === "import" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            Import now
          </Button>
          <Button size="sm" className="min-h-9" onClick={setUp} disabled={busy !== null} data-testid="share-setup">
            {busy === "setup" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : live.ready ? <Check className="mr-2 h-4 w-4" /> : null}
            {live.ready ? "Set up · check again" : "Set up"}
          </Button>
        </div>
      </div>

      <div className="space-y-4 rounded-lg border border-border bg-card p-4">
        <p className="type-body">
          The archive serves one folder over the network, and everything NegPy and the archive exchange is on
          it. <strong>Set up</strong> once on this side (it watches <code className="type-numeric">rolls/</code>,
          points NegPy’s gear and presets at the share and syncs your gear); the steps below are the Mac’s.
          Safe to press again — it changes nothing that is already right.
        </p>

        <p className="type-meta" data-testid="live-readout">
          {live.ready
            ? "Live mode is set up: rolls/ is watched and NegPy’s folders point at the share."
            : "Not set up yet on this side — press “Set up”."}
          {live.watch_enabled ? " · background checks on" : " · background checks OFF"}
        </p>

        <ol className="space-y-3 type-body">
          <li className="space-y-1.5">
            <span className="font-medium">1 · Mount it on the Mac, once</span>
            <span className="block type-meta">
              Finder → Go → Connect to Server (⌘K), user <code className="type-numeric">{share.user}</code>,
              the password from <code className="type-numeric">SHARE_PASSWORD</code> in the archive’s{" "}
              <code className="type-numeric">.env</code> (<code className="type-numeric">negarchive</code> until
              you change it). Tick “Remember this password”.
              {share.host_override ? ` Address from your override (${share.host_override}).` : ""}
            </span>
            {share.urls.length > 0 ? (
              share.urls.map((url) => <CopyLine key={url} value={url} label="the share address" />)
            ) : (
              <span className="block type-meta">
                No address found for this host — set “Address for the share” under This machine.
              </span>
            )}
          </li>
          <li className="space-y-1.5">
            <span className="font-medium">2 · NegPy’s exports go to the inbox</span>
            <span className="block type-meta">
              NegPy → Export: the folder and the filename pattern below. Finished positives are taken onto
              their rolls{interval ? ` within ${interval} seconds` : " on “Import now”"} and cleared from the
              folder — it never fills up.
            </span>
            <CopyLine value={steps.inbox} label="the export folder" />
            <CopyLine value={steps.filename_pattern} label="the filename pattern" />
          </li>
          <li className="space-y-1.5">
            <span className="font-medium">3 · Camera scans go to rolls/</span>
            <span className="block type-meta">
              NegPy → Live View &amp; Scan: output folder below, roll name = the roll’s serial (every roll page
              shows both under “Scan with NegPy”). The raws are linked, never copied, and the roll is marked
              scanned as they land.
            </span>
            <CopyLine value={steps.rolls} label="the scan folder" />
          </li>
          <li className="space-y-1.5">
            <span className="font-medium">4 · Let NegPy write sidecars</span>
            <span className="block type-meta">
              NegPy → Settings → write <code className="type-numeric">.negpy</code> files next to the originals.
              That is how an edit made on the Mac shows up in the archive.
            </span>
          </li>
          <li className="space-y-1.5">
            <span className="font-medium">5 · Share NegPy’s gear and presets</span>
            <span className="block type-meta">
              Paste both lines into Terminal once. Your cameras, lenses and films then appear in NegPy, and
              every roll you prepare here shows up as a preset.
            </span>
            <CopyLine value={`ln -sfn "${steps.user_dir}/gear" ~/.negpy/gear`} label="the gear link command" />
            <CopyLine
              value={`mkdir -p ~/.negpy/presets && ln -sfn "${steps.user_dir}/presets/metadata" ~/.negpy/presets/metadata`}
              label="the presets link command"
            />
          </li>
        </ol>

        <p className="type-meta border-t border-border pt-3" data-testid="inbox-readout">
          Inbox: {waiting === 0 ? "nothing waiting." : `${waiting} file${waiting === 1 ? "" : "s"} waiting.`}
          {inbox.last_sweep_at ? ` Last checked ${formatDateTime(inbox.last_sweep_at)}.` : ""}
          {inbox.last_summary ? ` Last import: ${inbox.last_summary}.` : ""}
          {!interval ? " The background check is off (WATCH_INTERVAL_SECONDS), so use “Import now”." : ""}
        </p>
        {stuck.length > 0 ? (
          <p className="type-meta text-destructive">
            Left in the inbox because the archive cannot take them: {stuck.map((file) => file.name).join(", ")}
          </p>
        ) : null}
        <p className="type-meta">
          On the server all of this is <code className="type-numeric">{share.dir}</code>, part of every backup.
        </p>
      </div>
    </section>
  )
}
