"use client"

import type React from "react"

import { useState } from "react"
import { useRouter } from "next/navigation"
import {
  type Camera,
  type Lens,
  createCamera,
  updateCamera,
  createLens,
  updateLens,
  uploadCameraImage,
  uploadLensImage,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent } from "@/components/ui/card"
import { useToast } from "@/hooks/use-toast"
import { Loader2, Upload } from "lucide-react"

interface CatalogFormProps {
  type: "camera" | "lens"
  item?: Camera | Lens
}

export function CatalogForm({ type, item }: CatalogFormProps) {
  const router = useRouter()
  const { toast } = useToast()
  const [loading, setLoading] = useState(false)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [formData, setFormData] = useState({
    name: item?.name || "",
    mount: item?.mount || "",
    notes: item?.notes || "",
  })

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setImageFile(e.target.files[0])
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      let savedItem: Camera | Lens

      if (item) {
        // Update existing item
        if (type === "camera") {
          savedItem = await updateCamera(item.id, formData)
        } else {
          savedItem = await updateLens(item.id, formData)
        }
      } else {
        // Create new item
        if (type === "camera") {
          savedItem = await createCamera(formData)
        } else {
          savedItem = await createLens(formData)
        }
      }

      // Upload image if provided
      if (imageFile) {
        if (type === "camera") {
          await uploadCameraImage(savedItem.id, imageFile)
        } else {
          await uploadLensImage(savedItem.id, imageFile)
        }
      }

      toast({
        title: `${type === "camera" ? "Camera" : "Lens"} ${item ? "updated" : "created"}`,
        description: `The ${type} has been successfully ${item ? "updated" : "created"}.`,
      })

      router.push(`/${type}s`)
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: `Failed to save ${type}. Please try again.`,
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
            <Label htmlFor="name">
              Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder={`e.g., ${type === "camera" ? "Nikon F3" : "Nikkor 50mm f/1.4"}`}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="mount">Mount</Label>
            <Input
              id="mount"
              value={formData.mount}
              onChange={(e) => setFormData({ ...formData, mount: e.target.value })}
              placeholder="e.g., Nikon F, Canon EF"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="image">Catalog Image</Label>
            <Input id="image" type="file" accept="image/*" onChange={handleImageChange} className="cursor-pointer" />
            {imageFile && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Upload className="h-4 w-4" />
                {imageFile.name}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">Notes</Label>
            <Textarea
              id="notes"
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              placeholder={`Additional notes about this ${type}...`}
              rows={4}
            />
          </div>

          <div className="flex gap-3">
            <Button type="submit" disabled={loading}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {item
                ? `Update ${type === "camera" ? "Camera" : "Lens"}`
                : `Create ${type === "camera" ? "Camera" : "Lens"}`}
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
