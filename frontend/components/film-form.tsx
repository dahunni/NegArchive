"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import {
  type Film,
  createFilm,
  updateFilm,
  getCameras,
  getLenses,
  type Camera,
  type Lens,
  getFilmstocks,
  type Filmstock,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Card, CardContent } from "@/components/ui/card"
import { useToast } from "@/hooks/use-toast"
import { Loader2 } from "lucide-react"

interface FilmFormProps {
  film?: Film
}

export function FilmForm({ film }: FilmFormProps) {
  const router = useRouter()
  const { toast } = useToast()
  const [loading, setLoading] = useState(false)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [lenses, setLenses] = useState<Lens[]>([])
  const [filmstocks, setFilmstocks] = useState<Filmstock[]>([])
  const [selectedCamera, setSelectedCamera] = useState<Camera | null>(null)
  const [formData, setFormData] = useState({
    title: film?.title || "",
    camera: film?.camera || "None",
    lens: film?.lens || "None",
    film_type: film?.film_type || "None",
    notes: film?.notes || "",
    building: film?.building || "",
    folder: film?.folder || "",
    archive_serial: film?.archive_serial || "",
    start_date: film?.start_date || "",
    end_date: film?.end_date || "",
  })

  useEffect(() => {
    async function loadData() {
      try {
        const [camerasData, lensesData, filmstocksData] = await Promise.all([
          getCameras(),
          getLenses(),
          getFilmstocks(),
        ])
        setCameras(camerasData)
        setLenses(lensesData)
        setFilmstocks(filmstocksData)

        // Set selected camera if editing
        if (film?.camera) {
          const camera = camerasData.find((c) => c.name === film.camera)
          if (camera) setSelectedCamera(camera)
        }
      } catch (error) {
        toast({
          title: "Error",
          description: "Failed to load form data.",
          variant: "destructive",
        })
      }
    }
    loadData()
  }, [film, toast])

  const handleCameraChange = (cameraName: string) => {
    setFormData({ ...formData, camera: cameraName })
    const camera = cameras.find((c) => c.name === cameraName)
    setSelectedCamera(camera || null)
  }

  const filteredLenses = selectedCamera?.mount ? lenses.filter((lens) => lens.mount === selectedCamera.mount) : lenses

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      if (film) {
        await updateFilm(film.id, formData)
        toast({
          title: "Film updated",
          description: "The film has been successfully updated.",
        })
        router.push(`/films/${film.id}`)
      } else {
        const newFilm = await createFilm(formData)
        toast({
          title: "Film created",
          description: "The film has been successfully created.",
        })
        router.push(`/films/${newFilm.id}`)
      }
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to save film. Please try again.",
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
            <Label htmlFor="title">
              Title <span className="text-destructive">*</span>
            </Label>
            <Input
              id="title"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              placeholder="Summer 2024 - Japan"
              required
            />
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="camera">Camera</Label>
              <Select value={formData.camera} onValueChange={handleCameraChange}>
                <SelectTrigger id="camera">
                  <SelectValue placeholder="Select camera" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="None">None</SelectItem>
                  {cameras.map((camera) => (
                    <SelectItem key={camera.id} value={camera.name}>
                      {camera.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="lens">Lens</Label>
              <Select value={formData.lens} onValueChange={(value) => setFormData({ ...formData, lens: value })}>
                <SelectTrigger id="lens">
                  <SelectValue placeholder="Select lens" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="None">None</SelectItem>
                  {filteredLenses.map((lens) => (
                    <SelectItem key={lens.id} value={lens.name}>
                      {lens.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedCamera?.mount && (
                <p className="text-xs text-muted-foreground">Showing lenses with {selectedCamera.mount} mount</p>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="film_type">Film Type</Label>
            <Select
              value={formData.film_type}
              onValueChange={(value) => setFormData({ ...formData, film_type: value })}
            >
              <SelectTrigger id="film_type">
                <SelectValue placeholder="Select film type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="None">None</SelectItem>
                {filmstocks.map((filmstock) => (
                  <SelectItem key={filmstock.id} value={filmstock.name}>
                    {filmstock.name} ({filmstock.iso} ISO)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="start_date">Start Date</Label>
              <Input
                id="start_date"
                type="date"
                value={formData.start_date}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="end_date">End Date</Label>
              <Input
                id="end_date"
                type="date"
                value={formData.end_date}
                onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
              />
            </div>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="building">Building</Label>
              <Input
                id="building"
                value={formData.building}
                onChange={(e) => setFormData({ ...formData, building: e.target.value })}
                placeholder="e.g., Archive A"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="folder">Folder</Label>
              <Input
                id="folder"
                value={formData.folder}
                onChange={(e) => setFormData({ ...formData, folder: e.target.value })}
                placeholder="e.g., 2024-Q2"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="archive_serial">Archive Serial</Label>
              <Input
                id="archive_serial"
                value={formData.archive_serial}
                onChange={(e) => setFormData({ ...formData, archive_serial: e.target.value })}
                placeholder="e.g., NEG-2024-001"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">Notes</Label>
            <Textarea
              id="notes"
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              placeholder="Additional notes about this film roll..."
              rows={4}
            />
          </div>

          <div className="flex gap-3">
            <Button type="submit" disabled={loading}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {film ? "Update Film" : "Create Film"}
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
