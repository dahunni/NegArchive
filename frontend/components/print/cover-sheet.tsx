import type { CSSProperties, ReactNode } from "react"

import { type Film, type RollLayout, getPreviewUrl } from "@/lib/api"
import { formatDateRange } from "@/lib/format"
import { Codes } from "@/components/print/print-frame"

/**
 * How wide a preview has to be for a cell on this sheet to print sharp.
 *
 * The cell is the paper (210mm) less its margins, the strip label and the gaps,
 * split between the frames of a strip — so a 120 roll at three to a strip gets
 * cells twice as wide as a 35mm roll at six, and the 480 px that is plenty for
 * the one shows on the other. Asked for at 400 dpi and rounded up to a multiple
 * of 240, because the backend caches one file per width and a handful of buckets
 * is the point of rounding.
 */
function previewWidthFor(perRow: number): number {
  const cellMm = (210 - 2 * 10 - 6 - (perRow - 1) * 1.5) / Math.max(perRow, 1)
  const needed = (cellMm / 25.4) * 400
  return Math.min(1440, Math.max(480, Math.ceil(needed / 240) * 240))
}

/**
 * The sleeve cover sheet (M4): one A4 page that sits in front of the sleeve.
 * Header with everything needed to identify the roll without the app, codes for
 * both kinds of scanner, and a grid whose rows are the strips, so the paper lines
 * up with the negatives behind it.
 */
export function CoverSheet({
  film,
  layout,
  codes,
  base,
  printedAt,
}: {
  film: Film
  layout: RollLayout
  codes: { qr: string; barcode: string; serial: string }
  base: string
  /** "Printed 21 Sep 2026": rendered in the browser, so it is the reader's date. */
  printedAt: ReactNode
}) {
  const perRow = Math.max(...layout.strips, 1)
  const previewWidth = previewWidthFor(perRow)
  return (
    <section className="sheet sleeve" data-testid="cover-sheet">
      <header style={{ display: "flex", gap: "6mm", alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="serial mono">{codes.serial}</div>
          <div className="title">{film.title}</div>
          <div className="meta" style={{ marginTop: "2mm", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5mm 6mm" }}>
            <span>
              <b>Shot</b> {formatDateRange(film.start_date, film.end_date)}
            </span>
            <span>
              <b>Film</b> {film.film_type ?? "—"}
              {film.format ? ` · ${film.format}` : ""}
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
            <span>
              <b>Status</b> {film.status_label ?? film.status}
            </span>
            <span>
              {/* Everything the roll has, not only what fits the grid: an unplaced
                  frame was still scanned (R#85). */}
              <b>Frames</b> {layout.rows.flat().filter(Boolean).length + layout.unplaced.length} scanned ·{" "}
              {layout.capacity} on the sleeve · {layout.strips.join("+")}
            </span>
          </div>
          {film.notes ? (
            <p className="meta" style={{ marginTop: "2mm", maxHeight: "12mm", overflow: "hidden" }}>
              {film.notes}
            </p>
          ) : null}
        </div>
        <Codes qr={codes.qr} barcode={codes.barcode} qrAlt={`QR ${base}/s/${codes.serial}`} barcodeAlt={`Barcode ${codes.serial}`} />
      </header>
      <hr className="hr" />
      <div className="strip-grid" style={{ "--cols": perRow } as CSSProperties}>
        {layout.rows.map((row, rowIndex) => (
          <div
            key={rowIndex}
            className="strip-row"
            style={{ gridTemplateColumns: `var(--strip-label-w) repeat(${perRow}, 1fr)` }}
          >
            <div className="strip-label">Strip {rowIndex + 1}</div>
            {row.map((cell, cellIndex) => {
              const number = layout.strips.slice(0, rowIndex).reduce((a, b) => a + b, 0) + cellIndex + 1
              return cell ? (
                <div key={cell.id} className="frame-box">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={getPreviewUrl(cell.id, previewWidth, undefined, cell.preview_version)} alt={`Frame ${cell.frame_number}`} />
                  <span className="num">{cell.frame_number}</span>
                  {cell.notes ? <span className="note">{cell.notes}</span> : null}
                </div>
              ) : (
                <div key={`empty-${rowIndex}-${cellIndex}`} className="frame-box empty">
                  <span className="num" style={{ background: "transparent", color: "#999" }}>
                    {number}
                  </span>
                </div>
              )
            })}
            {Array.from({ length: perRow - row.length }).map((_, i) => (
              <div key={`pad-${i}`} />
            ))}
          </div>
        ))}
      </div>
      {layout.unplaced.length > 0 ? (
        <p className="meta" style={{ marginTop: "3mm" }}>
          <b>Not on the sleeve grid:</b>{" "}
          {layout.unplaced.map((f) => (f.frame_number === null ? "unnumbered" : `#${f.frame_number}`)).join(", ")}
        </p>
      ) : null}
      <footer className="footer">
        <span>
          {base}/s/{codes.serial}
        </span>
        <span>{printedAt} · NegArchive</span>
      </footer>
    </section>
  )
}
