import { notFound } from "next/navigation"

import { locationCodes, publicBase } from "@/components/print/data"
import { loadLocationBundle } from "@/components/print/location-data"
import { PrintFrame } from "@/components/print/print-frame"
import { PrintedOn } from "@/app/print/printed-on"
import { formatDateRange } from "@/lib/format"

const ROWS_PER_PAGE = 34

/** Binder index (M4): a table of pages → roll, as many A4 sheets as needed. */
export default async function BinderIndexPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const [bundle, base] = await Promise.all([loadLocationBundle(Number(id)), publicBase()])
  if (!bundle) notFound()
  const node = bundle.detail.location
  const codes = locationCodes(base, node)
  const byId = new Map(bundle.films.map((f) => [f.id, f]))
  const rows =
    node.kind === "binder"
      ? bundle.detail.children
          .filter((c) => c.kind === "sleeve")
          .map((page) => ({ page, roll: page.rolls[0] ? byId.get(page.rolls[0].id) ?? null : null, brief: page.rolls[0] ?? null }))
      : bundle.detail.rolls.map((brief) => ({ page: null, roll: byId.get(brief.id) ?? null, brief }))
  const sheets: (typeof rows)[] = []
  for (let i = 0; i < Math.max(rows.length, 1); i += ROWS_PER_PAGE) sheets.push(rows.slice(i, i + ROWS_PER_PAGE))
  const missing = bundle.detail.discrepancies.filter((d) => d.kind === "missing_page")
  return (
    <PrintFrame title={`Index ${node.label}`}>
      {sheets.map((chunk, index) => (
        <section key={index} className="sheet" data-testid="index-sheet">
          <header style={{ display: "flex", justifyContent: "space-between", gap: "6mm" }}>
            <div>
              <div className="serial mono" style={{ fontSize: "18pt" }}>
                {node.code ?? node.name}
              </div>
              <div className="title">{node.name}</div>
              <div className="meta">{node.path}</div>
              <div className="meta">
                {rows.length} {node.kind === "binder" ? "pages" : "rolls"} · sheet {index + 1} of {sheets.length}
              </div>
            </div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={codes.qr} alt="" style={{ width: "22mm", height: "22mm" }} />
          </header>
          <hr className="hr" />
          <table className="index">
            <thead>
              <tr>
                {node.kind === "binder" ? <th>Page</th> : null}
                <th>Serial</th>
                <th>Title</th>
                <th>Shot</th>
                <th>Film</th>
                <th>Camera</th>
                <th>Status</th>
                <th>Frames</th>
              </tr>
            </thead>
            <tbody>
              {chunk.map(({ page, roll, brief }, rowIndex) => (
                <tr key={page?.id ?? brief?.id ?? rowIndex}>
                  {node.kind === "binder" ? <td className="num">{page?.code ?? page?.sort_order}</td> : null}
                  <td className="num">{brief?.archive_serial ?? (page ? "— empty —" : "")}</td>
                  <td>{brief?.title ?? ""}</td>
                  <td>{roll ? formatDateRange(roll.start_date, roll.end_date) : ""}</td>
                  <td>{roll?.film_type ?? brief?.film_type ?? ""}</td>
                  <td>{roll?.camera ?? brief?.camera ?? ""}</td>
                  <td>{roll?.status_label ?? brief?.status ?? ""}</td>
                  <td className="num">{brief?.image_count ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {index === sheets.length - 1 && missing.length > 0 ? (
            <p className="meta" style={{ marginTop: "3mm" }}>
              <b>Missing:</b> {missing.map((m) => m.message).join(" ")}
            </p>
          ) : null}
          <footer className="footer">
            <span>
              {base}/l/{node.id}
            </span>
            <span>
              <PrintedOn /> · NegArchive
            </span>
          </footer>
        </section>
      ))}
    </PrintFrame>
  )
}
