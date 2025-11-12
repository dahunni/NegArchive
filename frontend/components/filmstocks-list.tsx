"use client"

import type { Filmstock } from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import Link from "next/link"
import { Pencil, Trash2 } from "lucide-react"
import { useState } from "react"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { deleteFilmstock } from "@/lib/api"
import { useRouter } from "next/navigation"
import { useToast } from "@/hooks/use-toast"
import Image from "next/image"

interface FilmstocksListProps {
  filmstocks: Filmstock[]
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8010"

export function FilmstocksList({ filmstocks }: FilmstocksListProps) {
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [filmstockToDelete, setFilmstockToDelete] = useState<Filmstock | null>(null)
  const router = useRouter()
  const { toast } = useToast()

  const handleDelete = async () => {
    if (!filmstockToDelete) return

    try {
      await deleteFilmstock(filmstockToDelete.id)
      toast({
        title: "Filmstock deleted",
        description: "The filmstock has been successfully deleted.",
      })
      setDeleteDialogOpen(false)
      setFilmstockToDelete(null)
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to delete filmstock. Please try again.",
        variant: "destructive",
      })
    }
  }

  if (filmstocks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
        <p className="text-lg font-medium text-muted-foreground">No filmstocks yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Get started by adding your first filmstock.</p>
      </div>
    )
  }

  return (
    <>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filmstocks.map((filmstock) => (
          <Card key={filmstock.id} className="overflow-hidden">
            {(() => {
              const src = filmstock.url
                ? `${API_BASE}${filmstock.url}`
                : filmstock.image_path
                  ? `${API_BASE}${filmstock.image_path.startsWith("/") ? filmstock.image_path : "/" + filmstock.image_path}`
                  : null
              return src ? (
                <div className="relative aspect-[4/3] overflow-hidden bg-muted">
                  <Image
                    src={src}
                    alt={filmstock.name}
                    fill
                    className="object-cover"
                    sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, (max-width: 1280px) 33vw, 25vw"
                  />
                </div>
              ) : null
            })()}
            <CardContent className="p-4">
              <div className="flex items-start justify-between">
                <h3 className="font-semibold">{filmstock.name}</h3>
                {filmstock.expired && (
                  <Badge variant="destructive" className="text-xs">
                    Expired
                  </Badge>
                )}
              </div>
              <div className="mt-2 flex gap-2 text-sm text-muted-foreground">
                <Badge variant="secondary" className="text-xs">
                  ISO {filmstock.iso}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  {filmstock.kind}
                </Badge>
              </div>
              {filmstock.expiration_date && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Exp: {new Date(filmstock.expiration_date).toLocaleDateString()}
                </p>
              )}
              <div className="mt-4 flex gap-2">
                <Button variant="outline" size="sm" asChild className="flex-1 bg-transparent">
                  <Link href={`/filmstocks/${filmstock.id}/edit`}>
                    <Pencil className="mr-1 h-3 w-3" />
                    Edit
                  </Link>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setFilmstockToDelete(filmstock)
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
        title="Delete filmstock?"
        description={`Are you sure you want to delete "${filmstockToDelete?.name}"? This action cannot be undone.`}
      />
    </>
  )
}
