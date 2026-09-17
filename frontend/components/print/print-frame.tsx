"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { CheckCircle2, Printer } from "lucide-react"

import { errorMessage, markPrinted } from "@/lib/api"
import "@/app/print/print.css"

/**
 * The shell every printout sits in (M4): a toolbar that prints, marks the rolls'
 * labels as printed, and is hidden on paper. Sheets are children.
 */
export function PrintFrame({
  title,
  rollIds = [],
  autoPrint = false,
  children,
}: {
  title: string
  rollIds?: number[]
  autoPrint?: boolean
  children: React.ReactNode
}) {
  const [marked, setMarked] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    document.title = `${title} — NegArchive`
    if (autoPrint) {
      const handle = window.setTimeout(() => window.print(), 600)
      return () => window.clearTimeout(handle)
    }
  }, [title, autoPrint])

  const mark = async () => {
    try {
      await markPrinted(rollIds)
      setMarked(true)
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  return (
    <div className="print-root min-h-screen">
      <div className="print-toolbar" data-testid="print-toolbar">
        <strong>{title}</strong>
        <span className="spacer" />
        {rollIds.length > 0 ? (
          <button
            type="button"
            onClick={mark}
            disabled={marked}
            className="rounded border border-neutral-400 px-3 py-1.5 text-sm disabled:opacity-60"
            data-testid="mark-printed"
          >
            {marked ? (
              <>
                <CheckCircle2 className="mr-1 inline h-4 w-4" /> Marked printed
              </>
            ) : (
              `Mark ${rollIds.length === 1 ? "label" : `${rollIds.length} labels`} printed`
            )}
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => window.print()}
          className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white"
          data-testid="print-button"
        >
          <Printer className="mr-1 inline h-4 w-4" /> Print / Save as PDF
        </button>
        <Link href="/print/queue" className="text-sm underline">
          Queue
        </Link>
        {error ? <span className="text-sm text-red-700">{error}</span> : null}
      </div>
      {children}
    </div>
  )
}

/** QR + Code128 for a roll, from the backend's SVG endpoints. */
export function Codes({ qr, barcode, qrAlt, barcodeAlt, qrClass = "qr", barcodeClass = "barcode" }: { qr: string; barcode: string; qrAlt: string; barcodeAlt: string; qrClass?: string; barcodeClass?: string }) {
  return (
    <div className="codes">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={qr} alt={qrAlt} className={qrClass} />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={barcode} alt={barcodeAlt} className={barcodeClass} />
    </div>
  )
}
