"use client"

import { useEffect, useState } from "react"
import { QrCode } from "lucide-react"

import { type SystemInfo, getSystemInfo } from "@/lib/api"
import { Button } from "@/components/ui/button"

/**
 * "Type this on your phone", and the QR code that saves you from typing it.
 *
 * Roadmap M3, LAN discoverability. Half of self-hosting is remembering whether
 * the machine is at 192.168.1.37 or .38; the backend works it out and also logs
 * it at startup, and the QR is rendered server-side as an SVG so the page needs
 * no QR library and still works with no internet at all.
 *
 * Silent when the backend cannot say (no LAN address, or it is unreachable):
 * a footer that shows a broken address is worse than no footer.
 */
export function LanFooter() {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [showQr, setShowQr] = useState(false)

  useEffect(() => {
    let cancelled = false
    getSystemInfo()
      .then((value) => !cancelled && setInfo(value))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  if (!info?.ui_url) return null

  return (
    <footer className="border-t border-border" data-testid="lan-footer">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-4 sm:px-6 lg:px-8">
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

        {showQr ? (
          <div className="flex flex-col items-start gap-2">
            {/* The SVG carries `currentColor`, so it follows the light/dark theme.
                eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/api/system/qr.svg"
              alt={`QR code for ${info.ui_url}`}
              width={128}
              height={128}
              className="h-32 w-32"
              data-testid="lan-qr"
            />
            <p className="type-meta">Point a phone camera at this to open the archive.</p>
          </div>
        ) : null}

        {info.ui_urls.length > 1 ? (
          <p className="type-meta">
            Also reachable at {info.ui_urls.slice(1).join(", ")}.
          </p>
        ) : null}
      </div>
    </footer>
  )
}
