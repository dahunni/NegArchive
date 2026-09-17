import { getPreviewUrl } from "@/lib/api"
import { idsFromParam, loadRolls, publicBase, rollCodes } from "@/components/print/data"
import { Codes, PrintFrame } from "@/components/print/print-frame"
import { formatDateRange } from "@/lib/format"

/**
 * Roll index cards (M4): A6, four per A4. Metadata, location, status timeline,
 * both codes and a mini contact sheet.
 */
export default async function CardsPage({ searchParams }: { searchParams: Promise<{ ids?: string }> }) {
  const { ids } = await searchParams
  const [bundles, base] = await Promise.all([loadRolls(idsFromParam(ids)), publicBase()])
  const sheets: typeof bundles[] = []
  for (let i = 0; i < bundles.length; i += 4) sheets.push(bundles.slice(i, i + 4))
  return (
    <PrintFrame title={`${bundles.length} index cards`} rollIds={bundles.map((b) => b.film.id)}>
      {sheets.map((chunk, index) => (
        <section key={index} className="sheet" style={{ padding: 0 }} data-testid="card-sheet">
          <div className="label-sheet" style={{ gridTemplateColumns: "105mm 105mm" }}>
            {chunk.map(({ film, frames }) => {
              const codes = rollCodes(base, film)
              const steps = [
                ["Loaded", film.loaded_at],
                ["Shot", film.shot_at],
                ["Lab", film.lab_sent_at],
                ["Back", film.lab_back_at],
                ["Scanned", film.scanned_at],
                ["Sleeved", film.sleeved_at],
              ] as const
              return (
                <div key={film.id} className="label card" data-testid="index-card">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "4mm" }}>
                    <div style={{ minWidth: 0 }}>
                      <div className="serial mono" style={{ fontSize: "16pt" }}>
                        {codes.serial}
                      </div>
                      <div className="title" style={{ fontSize: "11pt" }}>
                        {film.title}
                      </div>
                    </div>
                    <Codes qr={codes.qr} barcode={codes.barcode} qrAlt="" barcodeAlt="" qrClass="qr" barcodeClass="barcode" />
                  </div>
                  <div className="meta" style={{ marginTop: "2mm", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.3mm 3mm" }}>
                    <span>
                      <b>Shot</b> {formatDateRange(film.start_date, film.end_date)}
                    </span>
                    <span>
                      <b>Film</b> {film.film_type ?? "—"}
                    </span>
                    <span>
                      <b>Camera</b> {film.camera ?? "—"}
                    </span>
                    <span>
                      <b>Lens</b> {film.lens ?? "—"}
                    </span>
                    <span style={{ gridColumn: "1 / -1" }}>
                      <b>Where</b> {film.location_path ?? "not filed"}
                    </span>
                  </div>
                  <div className="meta" style={{ marginTop: "2mm", display: "flex", gap: "2mm", flexWrap: "wrap" }}>
                    {steps.map(([label, at]) => (
                      <span key={label} style={{ border: "0.3pt solid #999", borderRadius: "1mm", padding: "0 1.2mm", background: at ? "#eee" : "#fff", color: at ? "#111" : "#999" }}>
                        {label}
                        {at ? ` ${new Date(at).toLocaleDateString()}` : ""}
                      </span>
                    ))}
                  </div>
                  <div style={{ marginTop: "3mm", display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "1mm" }}>
                    {frames.slice(0, 36).map((frame) => (
                      <div key={frame.id} className="frame-box" style={{ borderRadius: "0.5mm" }}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={getPreviewUrl(frame.id, 240)} alt="" />
                      </div>
                    ))}
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
