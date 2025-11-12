"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { type Image as ImageType, updateImage, deleteImage, getFilms, type Film } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Card, CardContent } from "@/components/ui/card"
import { useToast } from "@/hooks/use-toast"
import { Loader2, Trash2 } from "lucide-react"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"

interface ImageEditFormProps {
  image: ImageType
}

export function ImageEditForm({ image }: ImageEditFormProps) {
  const router = useRouter()
  const { toast } = useToast()
  const [loading, setLoading] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [films, setFilms] = useState<Film[]>([])
  const [formData, setFormData] = useState({
    type: image.type,
    film_roll_id: image.film_roll_id?.toString() || "none",
    frame_number: image.frame_number?.toString() || "",
    notes: image.notes || "",
    capture_date: image.capture_date || "",
  })

  useEffect(() => {
    async function loadFilms() {
      try {
        const filmsData = await getFilms()
        setFilms(filmsData)
      } catch (error) {
        toast({
          title: "Error",
          description: "Failed to load films.",
          variant: "destructive",
        })
      }
    }
    loadFilms()
  }, [toast])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      const updateData: Partial<ImageType> = {
        type: formData.type,
        film_roll_id: formData.film_roll_id === "none" ? null : Number(formData.film_roll_id),
        frame_number: formData.frame_number ? Number(formData.frame_number) : null,
        notes: formData.notes || null,
        capture_date: formData.capture_date || null,
      }

      await updateImage(image.id, updateData)
      toast({
        title: "Image updated",
        description: "The image has been successfully updated.",
      })
      router.push(`/images/${image.id}`)
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to update image. Please try again.",
        variant: "destructive",
      })
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async () => {
    try {
      await deleteImage(image.id, false)
      toast({
        title: "Image deleted",
        description: "The image has been successfully deleted.",
      })
      router.push("/images")
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to delete image. Please try again.",
        variant: "destructive",
      })
    }
  }

  return (
    <>
      <form onSubmit={handleSubmit}>
        <Card>
          <CardContent className="space-y-6 pt-6">
            <div className="space-y-2">
              <Label htmlFor="type">
                Type <span className="text-destructive">*</span>
              </Label>
              <Select
                value={formData.type}
                onValueChange={(value: "scan" | "contact_sheet") => setFormData({ ...formData, type: value })}
              >
                <SelectTrigger id="type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="scan">Scan</SelectItem>
                  <SelectItem value="contact_sheet">Contact Sheet</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="film_roll_id">Film Roll</Label>
              <Select
                value={formData.film_roll_id}
                onValueChange={(value) => setFormData({ ...formData, film_roll_id: value })}
              >
                <SelectTrigger id="film_roll_id">
                  <SelectValue placeholder="Select film (optional)" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  {films.map((film) => (
                    <SelectItem key={film.id} value={film.id.toString()}>
                      {film.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="frame_number">Frame Number</Label>
                <Input
                  id="frame_number"
                  type="number"
                  value={formData.frame_number}
                  onChange={(e) => setFormData({ ...formData, frame_number: e.target.value })}
                  placeholder="e.g., 12"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="capture_date">Capture Date</Label>
                <Input
                  id="capture_date"
                  type="date"
                  value={formData.capture_date}
                  onChange={(e) => setFormData({ ...formData, capture_date: e.target.value })}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="notes">Notes</Label>
              <Textarea
                id="notes"
                value={formData.notes}
                onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                placeholder="Additional notes about this image..."
                rows={3}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="flex gap-3">
                <Button type="submit" disabled={loading}>
                  {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Update Image
                </Button>
                <Button type="button" variant="outline" onClick={() => router.back()} disabled={loading}>
                  Cancel
                </Button>
              </div>
              <Button type="button" variant="destructive" onClick={() => setDeleteDialogOpen(true)} disabled={loading}>
                <Trash2 className="mr-2 h-4 w-4" />
                Delete
              </Button>
            </div>
          </CardContent>
        </Card>
      </form>

      <DeleteConfirmationDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onConfirm={handleDelete}
        title="Delete image?"
        description="Are you sure you want to delete this image? This action cannot be undone."
      />
    </>
  )
}
