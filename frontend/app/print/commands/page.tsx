import { barcodeUrl, getScanCommands, qrUrl } from "@/lib/api"
import { PrintFrame } from "@/components/print/print-frame"

/**
 * The scanner command sheet (M4): one Code128 per command, so the scanner console
 * can be driven without touching the screen. Stick it next to the scanner.
 */
export default async function CommandsPage() {
  const commands = await getScanCommands()
  return (
    <PrintFrame title="Scanner command cards">
      <section className="sheet" data-testid="commands-sheet">
        <div className="title">Scanner command cards</div>
        <p className="meta">
          Scan a card to switch the scanner console&apos;s mode, then scan rolls and locations. MOVE: rolls, then the
          destination. STATUS-…: every roll scanned gets that status. DONE / CANCEL end a sequence.
        </p>
        <hr className="hr" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "4mm" }}>
          {commands.map((command) => (
            <div key={command.code} className="label" style={{ height: "36mm", display: "flex", gap: "3mm", alignItems: "center" }} data-testid="command-card">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={qrUrl(command.code, 2)} alt="" style={{ width: "22mm", height: "22mm", flexShrink: 0 }} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="mono" style={{ fontSize: "13pt", fontWeight: 700 }}>
                  {command.code}
                </div>
                <div className="meta" style={{ fontSize: "8pt" }}>{command.description}</div>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={barcodeUrl(command.code, 9, false)} alt="" style={{ height: "10mm", marginTop: "1.5mm", maxWidth: "100%" }} />
              </div>
            </div>
          ))}
        </div>
      </section>
    </PrintFrame>
  )
}
