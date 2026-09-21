"use client"

import { useEffect } from "react"
import { ExternalLink, RefreshCw, Sparkles } from "lucide-react"

import { type ChangelogEntry, FRONTEND_VERSION } from "@/lib/api"
import { formatDate } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useAppVersion } from "@/hooks/use-app-version"

/**
 * "What's new" (M7): opens on its own after an update, with the releases since
 * the one this browser last saw; opens on request from the footer and from
 * Settings → About, with the whole changelog.
 *
 * When the page was built for an older version than the archive now runs —
 * a tab that stayed open through `docker compose pull`, or a service worker
 * still holding yesterday's shell — it says so and offers the reload, because
 * a UI from one release talking to an API from the next is the kind of thing
 * that looks like a bug and is not.
 */
export function WhatsNewDialog({
  open,
  onOpenChange,
  mode,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** `update`: the entries since the last seen version; `all`: the whole changelog. */
  mode: "update" | "all"
}) {
  const version = useAppVersion()
  const info = version?.info ?? null

  // The "all" view may be opened long after the first fetch; ask again so a
  // changelog edited on a dev server shows up.
  useEffect(() => {
    if (open && mode === "all") version?.refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode])

  const entries: ChangelogEntry[] = mode === "update" ? (version?.updated?.entries ?? []) : (info?.changelog ?? [])
  const from = mode === "update" ? version?.updated?.from : null

  const close = () => {
    if (mode === "update") version?.acknowledge()
    onOpenChange(false)
  }

  const reload = () => {
    if (mode === "update") version?.acknowledge()
    // Nudge the service worker to look for a new sw.js, then get the new shell.
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker
        .getRegistration()
        .then((registration) => registration?.update())
        .catch(() => undefined)
        .finally(() => window.location.reload())
    } else {
      window.location.reload()
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close()
        else onOpenChange(true)
      }}
    >
      <DialogContent className="flex max-h-[85vh] flex-col gap-0 p-0 sm:max-w-xl" data-testid="whats-new">
        <DialogHeader className="border-b border-border px-6 py-4">
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" aria-hidden />
            {mode === "update" && info ? `NegArchive was updated to v${info.version}` : "What's new in NegArchive"}
          </DialogTitle>
          <DialogDescription>
            {mode === "update" && from
              ? `You last used v${from}. Here is what changed since then.`
              : info
                ? `Every release, newest first. You are on v${info.version}.`
                : "Every release, newest first."}
          </DialogDescription>
        </DialogHeader>

        {version?.staleFrontend && info ? (
          <div
            role="status"
            data-testid="stale-frontend"
            className="flex flex-wrap items-center gap-3 border-b border-border bg-secondary px-6 py-3 text-sm"
          >
            <span className="min-w-0 flex-1">
              The page you have open was built for v{FRONTEND_VERSION}; the archive now runs v{info.version}. Reload to get the
              matching interface.
            </span>
            <Button size="sm" variant="outline" className="min-h-9" onClick={reload} data-testid="reload-for-update">
              <RefreshCw className="mr-2 h-4 w-4" />
              Reload
            </Button>
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {entries.length === 0 ? (
            <p className="type-body text-muted-foreground">
              {info ? "The changelog is empty." : "Could not read the changelog from the archive."}
            </p>
          ) : (
            <ol className="space-y-6" data-testid="changelog">
              {entries.map((entry) => (
                <li key={entry.version} data-testid="changelog-entry">
                  <div className="flex items-baseline gap-3">
                    <h3 className="type-section">v{entry.version}</h3>
                    {entry.date ? <span className="type-meta">{formatDate(entry.date) ?? entry.date}</span> : null}
                  </div>
                  {entry.sections.map((section) => (
                    <div key={section.title} className="mt-2">
                      <h4 className="type-meta uppercase tracking-wide">{section.title}</h4>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                        {section.items.map((item, index) => (
                          <li key={index}>
                            <Inline text={item} />
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </li>
              ))}
            </ol>
          )}
        </div>

        <DialogFooter className="border-t border-border px-6 py-3 sm:items-center sm:justify-between">
          {info ? (
            <a
              href={info.release_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 type-meta hover:underline"
            >
              Release on GitHub
              <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          ) : (
            <span />
          )}
          <Button onClick={close} className="min-h-10" data-testid="whats-new-close">
            {mode === "update" ? "Got it" : "Close"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** The two bits of Markdown the changelog uses inline: `**bold**` and `` `code` ``. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>
        if (part.startsWith("`") && part.endsWith("`"))
          return (
            <code key={index} className="rounded bg-secondary px-1 text-[0.85em]">
              {part.slice(1, -1)}
            </code>
          )
        return <span key={index}>{part}</span>
      })}
    </>
  )
}
