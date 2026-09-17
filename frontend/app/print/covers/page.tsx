import { CoverSheet } from "@/components/print/cover-sheet"
import { idsFromParam, loadRolls, publicBase, rollCodes } from "@/components/print/data"
import { PrintFrame } from "@/components/print/print-frame"

export default async function CoverSheetsPage({ searchParams }: { searchParams: Promise<{ ids?: string }> }) {
  const { ids } = await searchParams
  const [bundles, base] = await Promise.all([loadRolls(idsFromParam(ids)), publicBase()])
  const printedAt = new Date().toLocaleDateString()
  return (
    <PrintFrame title={`${bundles.length} cover sheets`} rollIds={bundles.map((b) => b.film.id)}>
      {bundles.map((bundle) => (
        <CoverSheet key={bundle.film.id} film={bundle.film} layout={bundle.layout} codes={rollCodes(base, bundle.film)} base={base} printedAt={printedAt} />
      ))}
    </PrintFrame>
  )
}
