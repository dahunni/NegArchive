"use client"

import { useRouter, useSearchParams } from "next/navigation"
import { useState } from "react"
import { Camera as CameraIcon, Package, Pencil, Plus, Trash2 } from "lucide-react"

import {
  type Camera,
  type Filmstock,
  type Lens,
  deleteCamera,
  deleteFilmstock,
  deleteLens,
  errorMessage,
  getCatalogImageUrl,
} from "@/lib/api"
import { formatDate } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { EmptyState } from "@/components/empty-state"
import { GearDialog, type GearItem, type GearKind } from "@/components/gear-dialog"
import { useToast } from "@/hooks/use-toast"

const TABS: { value: GearKind; label: string; plural: string }[] = [
  { value: "camera", label: "Cameras", plural: "cameras" },
  { value: "lens", label: "Lenses", plural: "lenses" },
  { value: "filmstock", label: "Film stocks", plural: "film stocks" },
]

function tabFromParam(value: string | null): GearKind {
  if (value === "lenses" || value === "lens") return "lens"
  if (value === "filmstocks" || value === "filmstock") return "filmstock"
  return "camera"
}

/**
 * Cameras, lenses and film stocks were three top-level pages. They are one section
 * with three tabs now: the catalog supports the roll, it is not the work.
 */
export function GearSection({
  cameras,
  lenses,
  filmstocks,
}: {
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
}) {
  const router = useRouter()
  const params = useSearchParams()
  const { toast } = useToast()

  const [tab, setTab] = useState<GearKind>(tabFromParam(params.get("tab")))
  const [dialog, setDialog] = useState<{ kind: GearKind; item: GearItem | null } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<{ kind: GearKind; item: GearItem } | null>(null)

  const remove = async () => {
    if (!pendingDelete) return
    const { kind, item } = pendingDelete
    try {
      if (kind === "camera") await deleteCamera(item.id)
      else if (kind === "lens") await deleteLens(item.id)
      else await deleteFilmstock(item.id)
      toast({ title: "Deleted", description: `“${item.name}” is no longer in the catalog.` })
      setPendingDelete(null)
      router.refresh()
    } catch (error) {
      toast({ title: "Could not delete", description: errorMessage(error), variant: "destructive" })
    }
  }

  const items: Record<GearKind, GearItem[]> = { camera: cameras, lens: lenses, filmstock: filmstocks }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="type-page">Gear</h1>
          <p className="mt-1 type-body text-muted-foreground">
            The cameras, lenses and film stocks your rolls refer to.
          </p>
        </div>
        <Button className="min-h-11" onClick={() => setDialog({ kind: tab, item: null })} data-testid="add-gear">
          <Plus className="mr-2 h-4 w-4" />
          Add {TABS.find((t) => t.value === tab)?.label.replace(/e?s$/, "").toLowerCase()}
        </Button>
      </div>

      <Tabs value={tab} onValueChange={(value) => setTab(value as GearKind)}>
        <TabsList>
          {TABS.map((entry) => (
            <TabsTrigger key={entry.value} value={entry.value} className="min-h-10">
              {entry.label}
              <Badge variant="secondary" className="ml-2 type-numeric">
                {items[entry.value].length}
              </Badge>
            </TabsTrigger>
          ))}
        </TabsList>

        {TABS.map((entry) => (
          <TabsContent key={entry.value} value={entry.value} className="mt-4">
            {items[entry.value].length === 0 ? (
              <EmptyState
                icon={entry.value === "filmstock" ? Package : CameraIcon}
                title={`No ${entry.plural} yet`}
                description={`Add the ${entry.plural} you shoot with so rolls can refer to them.`}
                action={
                  <Button onClick={() => setDialog({ kind: entry.value, item: null })}>
                    <Plus className="mr-2 h-4 w-4" />
                    Add
                  </Button>
                }
              />
            ) : (
              <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="gear-list">
                {items[entry.value].map((item) => (
                  <li key={item.id} className="overflow-hidden rounded-lg border border-border bg-card">
                    <GearThumb item={item} />
                    <div className="space-y-2 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="type-body font-semibold">{item.name}</h3>
                        {entry.value === "filmstock" && (item as Filmstock).expired ? (
                          <Badge variant="destructive" className="text-xs">
                            Expired
                          </Badge>
                        ) : null}
                      </div>
                      <GearMeta kind={entry.value} item={item} />
                      <div className="flex gap-2 pt-1">
                        <Button
                          variant="outline"
                          size="sm"
                          className="min-h-10 flex-1"
                          onClick={() => setDialog({ kind: entry.value, item })}
                        >
                          <Pencil className="mr-1 h-3 w-3" />
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="min-h-10"
                          aria-label={`Delete ${item.name}`}
                          onClick={() => setPendingDelete({ kind: entry.value, item })}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>
        ))}
      </Tabs>

      {dialog ? (
        <GearDialog
          kind={dialog.kind}
          item={dialog.item}
          open
          onOpenChange={(open) => !open && setDialog(null)}
        />
      ) : null}

      <DeleteConfirmationDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        onConfirm={remove}
        title="Remove from the catalog?"
        description={`“${pendingDelete?.item.name}” is deleted. Rolls that name it keep the name as plain text.`}
      />
    </div>
  )
}

function GearThumb({ item }: { item: GearItem }) {
  const src = getCatalogImageUrl(item)
  if (!src) return null
  return (
    <div className="frame-cell border-b border-border">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={item.name} loading="lazy" />
    </div>
  )
}

function GearMeta({ kind, item }: { kind: GearKind; item: GearItem }) {
  if (kind === "filmstock") {
    const stock = item as Filmstock
    return (
      <div className="flex flex-wrap gap-2">
        {stock.iso ? (
          <Badge variant="secondary" className="type-numeric">
            ISO {stock.iso}
          </Badge>
        ) : null}
        <Badge variant="outline" className="text-xs">
          {stock.kind?.replace(/_/g, " ")}
        </Badge>
        {stock.expiration_date ? <span className="type-meta">Exp {formatDate(stock.expiration_date)}</span> : null}
      </div>
    )
  }
  const gear = item as Camera | Lens
  return (
    <div className="space-y-1">
      {gear.mount ? <p className="type-meta">Mount: {gear.mount}</p> : null}
      {gear.notes ? <p className="line-clamp-2 type-body text-muted-foreground">{gear.notes}</p> : null}
    </div>
  )
}
