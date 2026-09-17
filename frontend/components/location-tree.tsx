"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useMemo, useState } from "react"
import { ChevronDown, ChevronRight, MapPin, Pencil, Plus, Printer, QrCode, Trash2 } from "lucide-react"

import {
  ApiError,
  type Location,
  type SleeveLayout,
  deleteLocation,
  errorMessage,
  qrUrl,
} from "@/lib/api"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { EmptyState } from "@/components/empty-state"
import { LocationDialog } from "@/components/location-dialog"
import { useToast } from "@/hooks/use-toast"

const KIND_LABEL: Record<string, string> = {
  building: "Building",
  room: "Room",
  shelf: "Shelf",
  row: "Row",
  box: "Box",
  binder: "Binder",
  envelope: "Envelope",
  sleeve: "Sleeve",
  other: "Location",
}

/**
 * The storage tree (M4): building → shelf → row → binder → sleeve, any depth.
 * Every node shows how many rolls it holds directly and underneath, and has its
 * own QR (`/l/{id}`) and Code128 (`LOC-{id}`) for a label.
 */
export function LocationTree({
  locations: initial,
  layouts,
  publicBase,
}: {
  locations: Location[]
  layouts: SleeveLayout[]
  publicBase: string
}) {
  const router = useRouter()
  const { toast } = useToast()
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set(initial.filter((n) => n.kind !== "binder").map((n) => n.id)))
  const [dialog, setDialog] = useState<{ item: Location | null; parentId: number | null } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Location | null>(null)
  const [inUse, setInUse] = useState<string | null>(null)

  const children = useMemo(() => {
    const map = new Map<number | null, Location[]>()
    for (const node of initial) {
      const list = map.get(node.parent_id) ?? []
      list.push(node)
      map.set(node.parent_id, list)
    }
    for (const list of map.values()) list.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
    return map
  }, [initial])

  const toggle = (id: number) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const remove = async (force = false) => {
    if (!pendingDelete) return
    try {
      await deleteLocation(pendingDelete.id, force)
      toast({ title: "Location deleted", description: pendingDelete.path ?? pendingDelete.label })
      setPendingDelete(null)
      setInUse(null)
      router.refresh()
    } catch (error) {
      if (error instanceof ApiError && error.code === "location_in_use") {
        setInUse(error.message)
        return
      }
      toast({ title: "Could not delete", description: errorMessage(error), variant: "destructive" })
    }
  }

  const render = (parent: number | null, depth: number): React.ReactNode => {
    const list = children.get(parent) ?? []
    if (list.length === 0) return null
    return (
      <ul className={cn("space-y-1", depth > 0 ? "ml-4 border-l border-border pl-3" : "")}>
        {list.map((node) => {
          const kids = children.get(node.id) ?? []
          const isOpen = expanded.has(node.id)
          const pages = node.kind === "binder" ? kids.filter((k) => k.kind === "sleeve").length : 0
          return (
            <li key={node.id} data-testid="location-node" data-kind={node.kind}>
              <div className="group flex min-h-11 items-center gap-2 rounded-md px-2 hover:bg-secondary/50">
                {kids.length > 0 ? (
                  <button type="button" onClick={() => toggle(node.id)} className="h-8 w-8 shrink-0 rounded hover:bg-secondary" aria-label={isOpen ? "Collapse" : "Expand"}>
                    {isOpen ? <ChevronDown className="mx-auto h-4 w-4" /> : <ChevronRight className="mx-auto h-4 w-4" />}
                  </button>
                ) : (
                  <span className="h-8 w-8 shrink-0" />
                )}
                <Link href={`/locations/${node.id}`} className="min-w-0 flex-1 truncate type-body font-medium hover:underline">
                  {node.code ? <span className="type-numeric mr-2 text-muted-foreground">{node.code}</span> : null}
                  {node.name}
                </Link>
                <Badge variant="outline" className="hidden text-xs sm:inline-flex">
                  {KIND_LABEL[node.kind] ?? node.kind}
                </Badge>
                {node.kind === "binder" ? (
                  <span className="type-meta hidden sm:inline">
                    {pages} page{pages === 1 ? "" : "s"}
                    {node.capacity ? ` / ${node.capacity}` : ""}
                  </span>
                ) : null}
                <span className="type-numeric text-muted-foreground" title="rolls here / underneath">
                  {node.kind === "sleeve" ? (node.roll_count > 0 ? "●" : "○") : `${node.roll_count} / ${node.rolls_in_subtree}`}
                </span>
                <div className="flex opacity-60 group-hover:opacity-100">
                  {node.kind !== "sleeve" ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-9 w-9"
                      aria-label={`Add inside ${node.name}`}
                      onClick={() => setDialog({ item: null, parentId: node.id })}
                    >
                      <Plus className="h-4 w-4" />
                    </Button>
                  ) : null}
                  <Button variant="ghost" size="icon" className="h-9 w-9" aria-label={`Edit ${node.name}`} onClick={() => setDialog({ item: node, parentId: null })}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-9 w-9" aria-label={`Delete ${node.name}`} onClick={() => setPendingDelete(node)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              {isOpen ? render(node.id, depth + 1) : null}
            </li>
          )
        })}
      </ul>
    )
  }

  const total = initial.reduce((sum, n) => (n.parent_id === null ? sum + n.rolls_in_subtree : sum), 0)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="type-page">Locations</h1>
          <p className="mt-1 type-body text-muted-foreground">
            Where the negatives physically are. {pluralize(initial.length, "location")}, {pluralize(total, "roll")} filed.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="min-h-11" asChild>
            <Link href="/print/locations" target="_blank" rel="noopener">
              <Printer className="mr-2 h-4 w-4" />
              Print tree
            </Link>
          </Button>
          <Button className="min-h-11" onClick={() => setDialog({ item: null, parentId: null })} data-testid="new-location">
            <Plus className="mr-2 h-4 w-4" />
            New location
          </Button>
        </div>
      </div>

      {initial.length === 0 ? (
        <EmptyState
          icon={MapPin}
          title="No locations yet"
          description="Start with a building or a shelf, add a binder inside it, then give the binder its sleeve pages."
          action={
            <Button onClick={() => setDialog({ item: null, parentId: null })}>
              <Plus className="mr-2 h-4 w-4" />
              New location
            </Button>
          }
        />
      ) : (
        <div className="rounded-lg border border-border bg-card p-2 sm:p-3" data-testid="location-tree">
          <p className="type-meta mb-2 px-2">
            Numbers are rolls here / rolls underneath. ● a sleeve with a roll, ○ an empty one. Click a name for pages, moves and labels.
          </p>
          {render(null, 0)}
        </div>
      )}

      <div className="rounded-lg border border-dashed border-border p-4">
        <p className="type-body font-medium">
          <QrCode className="mr-2 inline h-4 w-4" />
          QR codes on binders and shelves
        </p>
        <p className="type-meta mt-1">
          Every location has a QR code that opens it ({publicBase || "the LAN address"}/l/…) and a Code128 barcode
          reading LOC-id, so the scanner console can take “move this roll here” as two scans.
        </p>
        {initial.slice(0, 1).map((node) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={node.id} src={qrUrl(`${publicBase}/l/${node.id}`, 2)} alt="" className="mt-2 h-16 w-16 opacity-60" />
        ))}
      </div>

      <LocationDialog
        open={dialog !== null}
        onOpenChange={(open) => !open && setDialog(null)}
        locations={initial}
        layouts={layouts}
        item={dialog?.item ?? null}
        parentId={dialog?.parentId ?? null}
        defaultKind={dialog?.parentId ? (initial.find((n) => n.id === dialog.parentId)?.kind === "binder" ? "sleeve" : "binder") : "building"}
        onSaved={() => router.refresh()}
      />

      <DeleteConfirmationDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null)
            setInUse(null)
          }
        }}
        onConfirm={() => void remove(inUse !== null)}
        confirmLabel={inUse ? "Delete anyway" : "Delete"}
        title="Delete this location?"
        description={inUse ?? `“${pendingDelete?.path ?? pendingDelete?.label}” and everything inside it is removed. Rolls filed there become unfiled; nothing else is touched.`}
      />
    </div>
  )
}
