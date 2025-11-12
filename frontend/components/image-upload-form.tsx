"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { uploadImage, getFilms, type Film } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Card, CardContent } from "@/components/ui/card"
import { useToast } from "@/hooks/use-toast"
import { Loader2, Upload } from "lucide-react"

export function ImageUploadForm() {
  const router = useRouter()
  const { toast } = useToast()
  const [loading, setLoading] = useState(false)
  const [films, setFilms] = useState<Film[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [formData, setFormData] = useState({
    type: "scan" as "scan" | "contact_sheet",
    film_roll_id: "",
    frame_number: "",
    notes: "",
    capture_date: "",
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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0])
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      toast({
        title: "Error",
        description: "Please select a file to upload.",
        variant: "destructive",
      })
      return
    }

    setLoading(true)

    try {
      const uploadFormData = new FormData()
      uploadFormData.append("file", file)
      uploadFormData.append("type", formData.type)
      if (formData.film_roll_id) {
        uploadFormData.append("film_roll_id", formData.film_roll_id)
      }
      if (formData.frame_number) {
        uploadFormData.append("frame_number", formData.frame_number)
      }
      if (formData.notes) {
        uploadFormData.append("notes", formData.notes)
      }
      if (formData.capture_date) {
        uploadFormData.append("capture_date", formData.capture_date)
      }

      const image = await uploadImage(uploadFormData)
      toast({
        title: "Image uploaded",
        description: "The image has been successfully uploaded.",
      })
      router.push(`/images/${image.id}`)
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to upload image. Please try again.",
        variant: "destructive",
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <Card>
        <CardContent className="space-y-6 pt-6">
          <div className="space-y-2">
            <Label htmlFor="file">
              Image File <span className="text-destructive">*</span>
            </Label>
            <div className="flex items-center gap-3">
              <Input
                id="file"
                type="file"
                accept="image/*"
                onChange={handleFileChange}
                required
                className="cursor-pointer"
              />
              {file && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Upload className="h-4 w-4" />
                  {file.name}
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
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

          <div className="flex gap-3">
            <Button type="submit" disabled={loading}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Upload Image
            </Button>
            <Button type="button" variant="outline" onClick={() => router.back()} disabled={loading}>
              Cancel
            </Button>
          </div>
        </CardContent>
      </Card>
    </form>
  )
}
