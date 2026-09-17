import { Suspense } from "react"

import { ScannerConsole } from "@/components/scanner-console"

export const metadata = { title: "Scan — NegArchive" }

/**
 * The scanner console (M4): a page that does nothing but listen. A barcode
 * scanner, the phone camera or the keyboard feed it codes; sequences like
 * "roll, roll, destination" become moves.
 */
export default function ScanPage() {
  return (
    <Suspense>
      <ScannerConsole />
    </Suspense>
  )
}
