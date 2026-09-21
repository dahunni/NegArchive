import { notFound } from "next/navigation"

import { CoverSheet } from "@/components/print/cover-sheet"
import { loadRolls, publicBase, rollCodes } from "@/components/print/data"
import { PrintFrame } from "@/components/print/print-frame"
import { PrintedOn } from "@/app/print/printed-on"

export default async function CoverSheetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const [bundles, base] = await Promise.all([loadRolls([Number(id)]), publicBase()])
  const bundle = bundles[0]
  if (!bundle) notFound()
  return (
    <PrintFrame title={`Cover sheet ${bundle.film.archive_serial ?? bundle.film.title}`} rollIds={[bundle.film.id]}>
      <CoverSheet film={bundle.film} layout={bundle.layout} codes={rollCodes(base, bundle.film)} base={base} printedAt={<PrintedOn />} />
    </PrintFrame>
  )
}
