import { notFound } from "next/navigation"

import { locationCodes, publicBase } from "@/components/print/data"
import { loadLocationBundle, rollsUnder, serialRange, yearRange } from "@/components/print/location-data"
import { PrintFrame } from "@/components/print/print-frame"

/** Binder spine label (M4): 50 × 200 mm, four per A4 landscape strip, cut by hand. */
export default async function SpinePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const [bundle, base] = await Promise.all([loadLocationBundle(Number(id)), publicBase()])
  if (!bundle) notFound()
  const node = bundle.detail.location
  const rolls = rollsUnder(node, bundle.all, bundle.films)
  const codes = locationCodes(base, node)
  const ancestors = bundle.detail.ancestors.map((a) => a.label).join(" / ")
  return (
    <PrintFrame title={`Spine label ${node.label}`}>
      <section className="sheet" data-testid="spine-sheet">
        <div className="label-sheet" style={{ gridTemplateColumns: "repeat(4, 50mm)", columnGap: "0", justifyContent: "start" }}>
          {[0, 1].map((copy) => (
            <div key={copy} className="label spine" data-testid="spine-label" style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={codes.qr} alt="" style={{ width: "30mm", height: "30mm" }} />
              <div className="mono" style={{ fontSize: "26pt", fontWeight: 800, marginTop: "3mm" }}>
                {node.code ?? node.name}
              </div>
              <div style={{ fontSize: "11pt", fontWeight: 600, marginTop: "1mm" }}>{node.name}</div>
              <div className="meta" style={{ marginTop: "2mm", fontSize: "8pt" }}>{ancestors || " "}</div>
              <div style={{ marginTop: "6mm", fontSize: "14pt", fontWeight: 700 }}>{yearRange(rolls)}</div>
              <div className="meta" style={{ fontSize: "8pt" }}>
                {rolls.length} roll{rolls.length === 1 ? "" : "s"}
              </div>
              <div className="mono" style={{ marginTop: "4mm", fontSize: "8pt", lineHeight: 1.5 }}>
                {serialRange(rolls)}
              </div>
              <div style={{ marginTop: "auto" }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={codes.barcode} alt="" style={{ height: "12mm" }} />
                <div className="meta" style={{ fontSize: "6.5pt" }}>LOC-{node.id}</div>
              </div>
            </div>
          ))}
          <div className="meta" style={{ gridColumn: "3 / span 2", padding: "4mm", fontSize: "8pt" }}>
            Two copies of the spine label for <b>{node.path}</b>. Cut along the dashed line; 50 × 200 mm fits a standard
            ring binder spine. The QR opens the binder page; the barcode reads LOC-{node.id} for the scanner console.
          </div>
        </div>
      </section>
    </PrintFrame>
  )
}
