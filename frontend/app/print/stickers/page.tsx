import { idsFromParam, loadRolls, publicBase, rollCodes } from "@/components/print/data"
import { PrintFrame } from "@/components/print/print-frame"
import { formatDateRange } from "@/lib/format"

const PER_SHEET = 20 // 2 columns × 10 rows of 50 × 25 mm on A4 with 10 mm margins

/**
 * Small roll stickers (M4): 50 × 25 mm, twenty per A4, for lab envelopes and loose
 * sleeves. Serial, title, dates, film, and both codes.
 */
export default async function StickersPage({ searchParams }: { searchParams: Promise<{ ids?: string }> }) {
  const { ids } = await searchParams
  const [bundles, base] = await Promise.all([loadRolls(idsFromParam(ids)), publicBase()])
  const sheets: typeof bundles[] = []
  for (let i = 0; i < bundles.length; i += PER_SHEET) sheets.push(bundles.slice(i, i + PER_SHEET))
  return (
    <PrintFrame title={`${bundles.length} stickers`} rollIds={bundles.map((b) => b.film.id)}>
      {sheets.map((chunk, index) => (
        <section key={index} className="sheet" data-testid="sticker-sheet">
          <div className="label-sheet" style={{ gridTemplateColumns: "repeat(2, 50mm)", justifyContent: "start", columnGap: "6mm" }}>
            {chunk.map(({ film }) => {
              const codes = rollCodes(base, film)
              return (
                <div key={film.id} className="label sticker" data-testid="sticker">
                  <div style={{ display: "flex", gap: "2mm", height: "100%" }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={codes.qr} alt="" style={{ width: "18mm", height: "18mm", flexShrink: 0 }} />
                    <div style={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column" }}>
                      <div className="mono" style={{ fontSize: "10pt", fontWeight: 700 }}>
                        {codes.serial}
                      </div>
                      <div style={{ fontSize: "7.5pt", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{film.title}</div>
                      <div className="meta" style={{ fontSize: "6.5pt", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {[formatDateRange(film.start_date, film.end_date), film.film_type].filter((p) => p && p !== "—").join(" · ")}
                      </div>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={codes.barcode} alt="" style={{ height: "7mm", marginTop: "auto", alignSelf: "flex-start", maxWidth: "100%" }} />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      ))}
    </PrintFrame>
  )
}
