"use client"

import type { Film } from "@/lib/api"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { Eye, Pencil, Trash2 } from "lucide-react"
import { useState } from "react"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { deleteFilm } from "@/lib/api"
import { useRouter } from "next/navigation"
import { useToast } from "@/hooks/use-toast"

interface FilmsListProps {
  films: Film[]
}

export function FilmsList({ films }: FilmsListProps) {
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [filmToDelete, setFilmToDelete] = useState<Film | null>(null)
  const router = useRouter()
  const { toast } = useToast()

  const handleDelete = async () => {
    if (!filmToDelete) return

    try {
      await deleteFilm(filmToDelete.id)
      toast({
        title: "Film deleted",
        description: "The film has been successfully deleted.",
      })
      setDeleteDialogOpen(false)
      setFilmToDelete(null)
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to delete film. Please try again.",
        variant: "destructive",
      })
    }
  }

  const formatDateRange = (film: Film) => {
    if (film.start_date && film.end_date) {
      return `${new Date(film.start_date).toLocaleDateString()} – ${new Date(film.end_date).toLocaleDateString()}`
    }
    if (film.start_date) {
      return new Date(film.start_date).toLocaleDateString()
    }
    return "—"
  }

  if (films.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
        <p className="text-lg font-medium text-muted-foreground">No films yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Get started by creating your first film roll.</p>
      </div>
    )
  }

  return (
    <>
      <div className="rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Camera</TableHead>
              <TableHead>Lens</TableHead>
              <TableHead>Film Type</TableHead>
              <TableHead>Date Range</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {films.map((film) => (
              <TableRow key={film.id}>
                <TableCell className="font-medium">{film.title}</TableCell>
                <TableCell>{film.camera || "—"}</TableCell>
                <TableCell>{film.lens || "—"}</TableCell>
                <TableCell>{film.film_type || "—"}</TableCell>
                <TableCell>{formatDateRange(film)}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button variant="ghost" size="sm" asChild>
                      <Link href={`/films/${film.id}`}>
                        <Eye className="h-4 w-4" />
                      </Link>
                    </Button>
                    <Button variant="ghost" size="sm" asChild>
                      <Link href={`/films/${film.id}/edit`}>
                        <Pencil className="h-4 w-4" />
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setFilmToDelete(film)
                        setDeleteDialogOpen(true)
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <DeleteConfirmationDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onConfirm={handleDelete}
        title="Delete film?"
        description={`Are you sure you want to delete "${filmToDelete?.title}"? This action cannot be undone. All associated image records will also be deleted.`}
      />
    </>
  )
}
