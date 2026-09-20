"use client"

import { useCallback, useEffect, useState } from "react"
import { Inbox, Loader2, RefreshCw } from "lucide-react"

import { type InboxStatus, errorMessage, getInbox, sweepInbox } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { CopyLine } from "@/components/share-settings"
import { useToast } from "@/hooks/use-toast"

/**
 * NegPy exports → this archive (roadmap M6.2).
 *
 * The stack serves one folder over SMB itself. This card is the whole setup:
 * the address to paste into Finder, the folder to give NegPy, and what has
 * landed since. Nothing here is configured in the browser — the share's name,
 * user and password live in the Compose file, where a secret belongs.
 */
export function InboxCard({ onChanged }: { onChanged?: () => void }) {
  const { toast } = useToast()
  const [status, setStatus] = useState<InboxStatus | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setStatus(await getInbox())
    } catch {
      /* the card stays quiet; the rest of Settings works without it */
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const importNow = async () => {
    setBusy(true)
    try {
      const body = await sweepInbox()
      setStatus(body)
      toast({
        title: body.result.imported > 0 ? body.result.summary : "Nothing new in the inbox",
        description: body.result.rejected.length
          ? `Left there: ${body.result.rejected.map((r) => r.name).slice(0, 3).join(", ")}${
              body.result.rejected.length > 3 ? "…" : ""
            }`
          : undefined,
      })
      if (body.result.imported > 0) onChanged?.()
    } catch (error) {
      toast({ title: "Could not import", description: errorMessage(error), variant: "destructive" })
    } finally {
      setBusy(false)
    }
  }

  if (!status) return null
  const share = status.share
  const waiting = status.pending.count
  const stuck = status.pending.files.filter((file) => !file.accepted)

  return (
    <section className="space-y-3" data-testid="inbox-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 type-section">
          <Inbox className="h-4 w-4 text-muted-foreground" aria-hidden />
          NegPy exports
        </h2>
        <Button variant="outline" size="sm" className="min-h-9" onClick={importNow} disabled={busy}>
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
          Import now
        </Button>
      </div>

      <div className="space-y-4 rounded-lg border border-border bg-card p-4">
        <p className="type-body">
          The archive serves a folder of its own over the network. Export from NegPy into it, and every
          {status.interval_seconds ? ` ${status.interval_seconds} seconds` : " sweep"} the archive files what
          landed there onto its rolls and clears the folder. Everything that arrives here is a finished
          positive and is shown as it is.
        </p>

        <ol className="space-y-3 type-body">
          <li className="space-y-1.5">
            <span className="font-medium">1 · Mount it on the Mac, once</span>
            <span className="block type-meta">
              Finder → Go → Connect to Server (⌘K), user <code className="type-numeric">{share.user}</code>,
              the password from <code className="type-numeric">SHARE_PASSWORD</code> in the archive’s{" "}
              <code className="type-numeric">.env</code> (<code className="type-numeric">negarchive</code> until
              you change it). Tick “Remember this password”.
            </span>
            {share.urls.length > 0 ? (
              share.urls.map((url) => <CopyLine key={url} value={url} label="the share address" />)
            ) : (
              <span className="block type-meta">
                No network address found for this host — set{" "}
                <code className="type-numeric">NEGARCHIVE_PUBLIC_HOST</code> in <code className="type-numeric">.env</code>.
              </span>
            )}
          </li>
          <li className="space-y-1.5">
            <span className="font-medium">2 · Point NegPy’s export at it</span>
            <span className="block type-meta">
              NegPy → Export: the output folder below, and the filename pattern so each frame finds its roll.
              (Or drop files into subfolders named after a roll’s serial.)
            </span>
            <CopyLine value={share.mac_path} label="the export folder" />
            <CopyLine value={status.filename_pattern} label="the filename pattern" />
          </li>
          <li className="space-y-1.5">
            <span className="font-medium">3 · That is all</span>
            <span className="block type-meta" data-testid="inbox-readout">
              {waiting === 0 ? "Nothing waiting." : `${waiting} file${waiting === 1 ? "" : "s"} waiting.`}
              {status.last_sweep_at ? ` Last checked ${formatDateTime(status.last_sweep_at)}.` : ""}
              {status.last_summary ? ` Last import: ${status.last_summary}.` : ""}
              {!status.interval_seconds ? " The background check is off (WATCH_INTERVAL_SECONDS), so use “Import now”." : ""}
            </span>
            {stuck.length > 0 ? (
              <span className="block type-meta text-destructive">
                Left in the inbox because the archive cannot take them:{" "}
                {stuck.map((file) => file.name).join(", ")}
              </span>
            ) : null}
          </li>
        </ol>
      </div>
    </section>
  )
}
