"use client"

import { useEffect, useState } from "react"
import { QrCode, Sparkles } from "lucide-react"

import { type SystemInfo, backendUrl, getSystemInfo } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { useAppVersion } from "@/hooks/use-app-version"

/**
 * "Type this on your phone", and the QR code that saves you from typing it.
 *
 * Roadmap M3, LAN discoverability. Half of self-hosting is remembering whether
 * the machine is at 192.168.1.37 or .38; the backend works it out and also logs
 * it at startup, and the QR is rendered server-side as an SVG so the page needs
 * no QR library and still works with no internet at all.
 *
 * The LAN block is silent when the backend cannot say (no LAN address, or it is
 * unreachable): a footer that shows a broken address is worse than no footer.
 *
 * M7 adds the version line underneath — which NegArchive this is, the build it
 * came from, and "What's new" — so the answer to "is this the new one?" is on
 * every page rather than in a container label.
 */
export function LanFooter({ onWhatsNew }: { onWhatsNew?: () => void }) {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [showQr, setShowQr] = useState(false)
  const version = useAppVersion()

  useEffect(() => {
    let cancelled = false
    getSystemInfo()
      .then((value) => !cancelled && setInfo(value))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  const release = version?.info ?? null
  if (!info?.ui_url && !release) return null

  return (
    <footer className="border-t border-border" data-testid="lan-footer" data-print-hide>
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-4 sm:px-6 lg:px-8">
        {info?.ui_url ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="type-meta uppercase tracking-wide">On this network</span>
          <a
            href={info.ui_url}
            className="type-numeric text-sm hover:underline"
            data-testid="lan-url"
          >
            {info.ui_url}
          </a>
          <Button
            variant="ghost"
            size="sm"
            className="min-h-9"
            onClick={() => setShowQr((open) => !open)}
            aria-expanded={showQr}
            data-testid="lan-qr-toggle"
          >
            <QrCode className="mr-2 h-4 w-4" />
            {showQr ? "Hide QR" : "Show QR"}
          </Button>
        </div>
        ) : null}

        {info?.ui_url && showQr ? (
          <div className="flex flex-col items-start gap-2">
            {/* The SVG carries `currentColor`, so it follows the light/dark theme.
                The path is the backend's own (`qr_url`), resolved like every other
                thing the browser fetches from it.
                eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={backendUrl(info.qr_url)}
              alt={`QR code for ${info.ui_url}`}
              width={128}
              height={128}
              className="h-32 w-32"
              data-testid="lan-qr"
            />
            <p className="type-meta">Point a phone camera at this to open the archive.</p>
          </div>
        ) : null}

        {info && info.ui_urls.length > 1 ? (
          <p className="type-meta">
            Also reachable at {info.ui_urls.slice(1).join(", ")}.
          </p>
        ) : null}

        {release ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 type-meta" data-testid="version-line">
            <span>
              NegArchive{" "}
              <span className="type-numeric" data-testid="app-version">
                v{release.version}
              </span>
              {release.git_sha ? (
                <span className="type-numeric" title={release.built_at ? `built ${release.built_at}` : undefined}>
                  {" "}
                  · {release.git_sha.slice(0, 7)}
                </span>
              ) : null}
            </span>
            {version?.staleFrontend ? (
              <span className="rounded bg-secondary px-1.5 py-0.5 text-secondary-foreground" data-testid="version-mismatch">
                this page is v{process.env.NEXT_PUBLIC_APP_VERSION} — reload
              </span>
            ) : null}
            {onWhatsNew ? (
              <button
                type="button"
                onClick={onWhatsNew}
                className="inline-flex min-h-9 items-center gap-1 rounded-md px-1 hover:underline"
                data-testid="whats-new-open"
              >
                <Sparkles className="h-3.5 w-3.5" aria-hidden />
                What&apos;s new
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </footer>
  )
}
