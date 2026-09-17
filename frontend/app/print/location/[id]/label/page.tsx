import { notFound } from "next/navigation"

import { locationCodes, publicBase } from "@/components/print/data"
import { loadLocationBundle, rollsUnder } from "@/components/print/location-data"
import { PrintFrame } from "@/components/print/print-frame"

/** A generic location label (M4): 90 × 40 mm, for shelves, rows, boxes, envelopes. */
export default async function LocationLabelPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const [bundle, base] = await Promise.all([loadLocationBundle(Number(id)), publicBase()])
  if (!bundle) notFound()
  const node = bundle.detail.location
  const codes = locationCodes(base, node)
  const rolls = rollsUnder(node, bundle.all, bundle.films)
  return (
    <PrintFrame title={`Label ${node.label}`}>
      <section className="sheet" data-testid="location-label-sheet">
        <div className="label-sheet" style={{ gridTemplateColumns: "repeat(2, 90mm)", columnGap: "6mm", justifyContent: "start" }}>
          {[0, 1, 2, 3].map((copy) => (
            <div key={copy} className="label loc" data-testid="location-label" style={{ display: "flex", gap: "3mm" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={codes.qr} alt="" style={{ width: "30mm", height: "30mm", flexShrink: 0 }} />
              <div style={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column" }}>
                <div className="mono" style={{ fontSize: "18pt", fontWeight: 800 }}>
                  {node.code ?? node.name}
                </div>
                <div style={{ fontSize: "10pt", fontWeight: 600 }}>{node.name}</div>
                <div className="meta" style={{ fontSize: "7pt", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {bundle.detail.ancestors.map((a) => a.label).join(" / ") || node.kind}
                </div>
                <div className="meta" style={{ fontSize: "7pt" }}>
                  {rolls.length} roll{rolls.length === 1 ? "" : "s"}
                </div>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={codes.barcode} alt="" style={{ height: "9mm", marginTop: "auto", alignSelf: "flex-start" }} />
              </div>
            </div>
          ))}
        </div>
        <p className="meta" style={{ marginTop: "6mm" }}>
          Four copies for <b>{node.path}</b>.
        </p>
      </section>
    </PrintFrame>
  )
}
