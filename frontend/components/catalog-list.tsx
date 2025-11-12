"use client"

import type { Camera, Lens } from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { Pencil, Trash2 } from "lucide-react"
import { useState } from "react"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { deleteCamera, deleteLens } from "@/lib/api"
import { useRouter } from "next/navigation"
import { useToast } from "@/hooks/use-toast"
import Image from "next/image"

interface CatalogListProps {
  items: (Camera | Lens)[]
  type: "camera" | "lens"
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8010"

export function CatalogList({ items, type }: CatalogListProps) {
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [itemToDelete, setItemToDelete] = useState<Camera | Lens | null>(null)
  const router = useRouter()
  const { toast } = useToast()

  const handleDelete = async () => {
    if (!itemToDelete) return

    try {
      if (type === "camera") {
        await deleteCamera(itemToDelete.id)
      } else {
        await deleteLens(itemToDelete.id)
      }
      toast({
        title: `${type === "camera" ? "Camera" : "Lens"} deleted`,
        description: `The ${type} has been successfully deleted.`,
      })
      setDeleteDialogOpen(false)
      setItemToDelete(null)
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: `Failed to delete ${type}. Please try again.`,
        variant: "destructive",
      })
    }
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
        <p className="text-lg font-medium text-muted-foreground">No {type}s yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Get started by adding your first {type}.</p>
      </div>
    )
  }

  return (
    <>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {items.map((item) => (
          <Card key={item.id} className="overflow-hidden">
            {item.image_path && (
              <div className="relative aspect-[4/3] overflow-hidden bg-muted">
                <Image
                  src={`${API_BASE}${item.url ? item.url : (item.image_path.startsWith("/") ? item.image_path : "/" + item.image_path)}`}
                  alt={item.name}
                  fill
                  className="object-cover"
                  sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, (max-width: 1280px) 33vw, 25vw"
                />
              </div>
            )}
            <CardContent className="p-4">
              <h3 className="font-semibold">{item.name}</h3>
              {item.mount && <p className="mt-1 text-sm text-muted-foreground">Mount: {item.mount}</p>}
              {item.notes && <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{item.notes}</p>}
              <div className="mt-4 flex gap-2">
                <Button variant="outline" size="sm" asChild className="flex-1 bg-transparent">
                  <Link href={`/${type}s/${item.id}/edit`}>
                    <Pencil className="mr-1 h-3 w-3" />
                    Edit
                  </Link>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setItemToDelete(item)
                    setDeleteDialogOpen(true)
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <DeleteConfirmationDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onConfirm={handleDelete}
        title={`Delete ${type}?`}
        description={`Are you sure you want to delete "${itemToDelete?.name}"? This action cannot be undone.`}
      />
    </>
  )
}
