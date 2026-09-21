"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { AlertTriangle, ArrowLeft, ChevronRight, Loader2, MapPin, Pencil, Plus, Printer, QrCode } from "lucide-react"

import {
  type Location,
  type LocationDetail as Detail,
  type RollBrief,
  type SleeveLayout,
  addBinderPages,
  barcodeUrl,
  errorMessage,
  getLocationCodes,
  moveRoll,
  qrUrl,
} from "@/lib/api"
import { formatDateRange, pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { LocationDialog } from "@/components/location-dialog"
import { StatusBadge } from "@/components/status-stepper"
import { useToast } from "@/hooks/use-toast"

/**
 * One node of the storage tree (M4). A binder shows its pages in order with the
 * roll on each, an empty page as a dashed slot, and what is missing or doubled;
 * anything else lists the rolls and sub-locations it holds.
 */
export function LocationDetail({
  detail,
  locations,
  layouts,
}: {
  detail: Detail
  locations: Location[]
  layouts: SleeveLayout[]
}) {
  const router = useRouter()
  const { toast } = useToast()
  const node = detail.location
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState<{ parentId: number } | null>(null)
  const [pageCount, setPageCount] = useState("10")
  const [busy, setBusy] = useState(false)
  const [codes, setCodes] = useState<{ qr: string; barcode: string; qrText: string; barcodeText: string } | null>(
    null,
  )

  useEffect(() => {
    // Walking the tree fast enough and an older node's codes arrive last; they must
    // not end up labelled as this one's (R#80).
    let cancelled = false
    getLocationCodes(node.id)
      .then((info) => {
        if (cancelled) return
        setCodes({
          qr: qrUrl(info.qr_text, 3),
          barcode: barcodeUrl(info.barcode_text, 10),
          qrText: info.qr_text,
          barcodeText: info.barcode_text,
        })
      })
      .catch(() => {
        if (!cancelled) setCodes(null)
      })
    return () => {
      cancelled = true
    }
  }, [node.id])

  const addPages = async () => {
    setBusy(true)
    try {
      const pages = await addBinderPages(node.id, Number(pageCount) || 1)
      toast({ title: `${pluralize(pages.length, "page")} added` })
      router.refresh()
    } catch (error) {
      toast({ title: "Could not add pages", description: errorMessage(error), variant: "destructive" })
    } finally {
      setBusy(false)
    }
  }

  const unfile = async (roll: RollBrief) => {
    try {
      await moveRoll(roll.id, null, `Taken out of ${node.label}`)
      toast({ title: `${roll.archive_serial ?? roll.title} taken out` })
      router.refresh()
    } catch (error) {
      toast({ title: "Could not move", description: errorMessage(error), variant: "destructive" })
    }
  }

  const isBinder = node.kind === "binder"
  const pages = isBinder ? detail.children.filter((c) => c.kind === "sleeve") : []
  const others = detail.children.filter((c) => !(isBinder && c.kind === "sleeve"))

  return (
    <div className="space-y-6">
      <nav className="flex flex-wrap items-center gap-1 type-meta" aria-label="Breadcrumb">
        <Link href="/locations" className="flex items-center gap-1 hover:underline">
          <ArrowLeft className="h-3 w-3" />
          Locations
        </Link>
        {detail.ancestors.map((a) => (
          <span key={a.id} className="flex items-center gap-1">
            <ChevronRight className="h-3 w-3" />
            <Link href={`/locations/${a.id}`} className="hover:underline">
              {a.label}
            </Link>
          </span>
        ))}
      </nav>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="type-page">{node.name}</h1>
            {node.code ? (
              <Badge variant="outline" className="type-numeric text-sm">
                {node.code}
              </Badge>
            ) : null}
            <Badge variant="secondary" className="capitalize">
              {node.kind}
            </Badge>
          </div>
          <p className="mt-1 type-body text-muted-foreground" data-testid="location-path">
            {node.path}
          </p>
          <p className="type-meta mt-1">
            {pluralize(node.rolls_in_subtree, "roll")} in here
            {isBinder ? ` · ${pages.length} page${pages.length === 1 ? "" : "s"}${node.capacity ? ` of ${node.capacity}` : ""}` : ""}
            {detail.effective_layout ? ` · ${detail.effective_layout.name}` : ""}
            {` · scan code ${node.scan_code}`}
          </p>
          {node.notes ? <p className="mt-2 max-w-2xl type-body">{node.notes}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="min-h-11" onClick={() => setEditing(true)}>
            <Pencil className="mr-2 h-4 w-4" />
            Edit
          </Button>
          {node.kind !== "sleeve" ? (
            <Button variant="outline" className="min-h-11" onClick={() => setAdding({ parentId: node.id })}>
              <Plus className="mr-2 h-4 w-4" />
              Add inside
            </Button>
          ) : null}
          <Button variant="outline" className="min-h-11" asChild>
            <Link href={isBinder ? `/print/location/${node.id}/spine` : `/print/location/${node.id}/label`} target="_blank" rel="noopener">
              <Printer className="mr-2 h-4 w-4" />
              {isBinder ? "Spine label" : "Label"}
            </Link>
          </Button>
          {isBinder ? (
            <Button variant="outline" className="min-h-11" asChild>
              <Link href={`/print/location/${node.id}/index`} target="_blank" rel="noopener">
                <Printer className="mr-2 h-4 w-4" />
                Binder index
              </Link>
            </Button>
          ) : null}
        </div>
      </div>

      {detail.discrepancies.length > 0 ? (
        <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3" data-testid="discrepancies">
          <p className="type-body font-medium">
            <AlertTriangle className="mr-2 inline h-4 w-4" />
            {pluralize(detail.discrepancies.length, "thing")} to check
          </p>
          <ul className="mt-1 list-disc pl-6 type-body">
            {detail.discrepancies.map((d, index) => (
              <li key={index}>{d.message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {isBinder ? (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="type-section">Pages</h2>
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                void addPages()
              }}
            >
              <Input
                inputMode="numeric"
                value={pageCount}
                onChange={(e) => setPageCount(e.target.value)}
                className="h-10 w-20 type-numeric"
                aria-label="Pages to add"
              />
              <Button type="submit" variant="outline" className="min-h-10" disabled={busy} data-testid="add-pages">
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
                Add pages
              </Button>
            </form>
          </div>
          {pages.length === 0 ? (
            <p className="type-body text-muted-foreground">No pages yet. Add as many sleeve pages as the binder holds; rolls get filed on the next free one.</p>
          ) : (
            <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="binder-pages">
              {pages.map((page) => {
                const roll = page.rolls[0]
                return (
                  <li
                    key={page.id}
                    className={cn(
                      "flex min-h-24 gap-3 rounded-lg border p-3",
                      roll ? "border-border bg-card" : "border-dashed border-border",
                      page.rolls.length > 1 ? "border-amber-500" : "",
                    )}
                    data-testid="binder-page"
                    data-occupied={roll ? "1" : "0"}
                  >
                    <div className="w-12 shrink-0">
                      <p className="type-numeric text-muted-foreground">{page.code ?? `P${page.sort_order}`}</p>
                      <Link href={`/locations/${page.id}`} className="type-meta hover:underline">
                        page
                      </Link>
                    </div>
                    {roll ? (
                      <RollCard roll={roll} onUnfile={() => unfile(roll)} />
                    ) : (
                      <div className="flex flex-1 items-center">
                        <span className="type-meta">Empty · {detail.next_free_sleeve_id === page.id ? "next free page" : "free"}</span>
                      </div>
                    )}
                  </li>
                )
              })}
            </ol>
          )}
        </section>
      ) : null}

      {others.length > 0 ? (
        <section className="space-y-3">
          <h2 className="type-section">Inside</h2>
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {others.map((child) => (
              <li key={child.id}>
                <Link href={`/locations/${child.id}`} className="flex min-h-16 items-center gap-3 rounded-lg border border-border bg-card p-3 hover:border-muted-foreground/40">
                  <MapPin className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate type-body font-medium">{child.label}</span>
                    <span className="type-meta capitalize">
                      {child.kind} · {pluralize(child.rolls_in_subtree, "roll")}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {!isBinder || detail.rolls.length > 0 ? (
        <section className="space-y-3">
          <h2 className="type-section">Rolls filed here</h2>
          {detail.rolls.length === 0 ? (
            <p className="type-body text-muted-foreground">
              Nothing filed directly here. On a roll, use Move… or scan its code then this location&apos;s code.
            </p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="location-rolls">
              {detail.rolls.map((roll) => (
                <li key={roll.id} className="flex gap-3 rounded-lg border border-border bg-card p-3">
                  <RollCard roll={roll} onUnfile={() => unfile(roll)} />
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      <section className="rounded-lg border border-border bg-card p-4">
        <p className="type-body font-medium">
          <QrCode className="mr-2 inline h-4 w-4" />
          Codes for this location
        </p>
        <p className="type-meta mt-1">
          The QR opens this page from a phone; the barcode reads {node.scan_code} on a scanner, which the scanner
          console takes as a destination.
        </p>
        {codes ? (
          <div className="mt-3 flex flex-wrap items-end gap-6">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={codes.qr} alt={`QR ${codes.qrText}`} className="h-24 w-24" data-testid="location-qr" />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={codes.barcode} alt={`Barcode ${codes.barcodeText}`} className="h-16" data-testid="location-barcode" />
          </div>
        ) : null}
      </section>

      <LocationDialog
        open={editing}
        onOpenChange={setEditing}
        locations={locations}
        layouts={layouts}
        item={node}
        onSaved={() => router.refresh()}
      />
      <LocationDialog
        open={adding !== null}
        onOpenChange={(open) => !open && setAdding(null)}
        locations={locations}
        layouts={layouts}
        item={null}
        parentId={adding?.parentId ?? null}
        defaultKind={isBinder ? "sleeve" : node.kind === "shelf" || node.kind === "row" ? "binder" : "shelf"}
        onSaved={() => router.refresh()}
      />
    </div>
  )
}

function RollCard({ roll, onUnfile }: { roll: RollBrief; onUnfile: () => void }) {
  return (
    <div className="flex min-w-0 flex-1 gap-3">
      {roll.image_count > 0 ? (
        <Link href={`/films/${roll.id}`} className="frame-cell h-14 w-20 shrink-0 border border-border" aria-label={`Open ${roll.title}`}>
          {/* The cover is the roll's first frame; the API's brief has no id, so ask for the roll's preview via its first image later. */}
          <span className="type-meta flex h-full items-center justify-center">{roll.image_count} fr</span>
        </Link>
      ) : null}
      <div className="min-w-0 flex-1">
        <Link href={`/films/${roll.id}`} className="block truncate type-body font-medium hover:underline">
          {roll.title}
        </Link>
        <p className="type-numeric text-muted-foreground">{roll.archive_serial}</p>
        <p className="type-meta truncate">
          {[roll.film_type, roll.camera, formatDateRange(roll.start_date, roll.end_date)].filter((p) => p && p !== "—").join(" · ")}
        </p>
        <div className="mt-1 flex items-center gap-2">
          <StatusBadge status={roll.status} />
          <button type="button" className="type-meta underline" onClick={onUnfile}>
            take out
          </button>
        </div>
      </div>
    </div>
  )
}
