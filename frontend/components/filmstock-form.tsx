"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { type Filmstock, createFilmstock, updateFilmstock, uploadFilmstockImage, getFilmstocks } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Card, CardContent } from "@/components/ui/card"
import { useToast } from "@/hooks/use-toast"
import { Loader2, Upload } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"

interface FilmstockFormProps {
  filmstock?: Filmstock
}

export function FilmstockForm({ filmstock }: FilmstockFormProps) {
  const router = useRouter()
  const { toast } = useToast()
  const [loading, setLoading] = useState(false)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [availableKinds, setAvailableKinds] = useState<string[]>([])
  const [formData, setFormData] = useState({
    name: filmstock?.name || "",
    iso: filmstock?.iso?.toString() || "",
    kind: filmstock?.kind || "",
    expired: filmstock?.expired || false,
    expiration_date: filmstock?.expiration_date || "",
  })

  useEffect(() => {
    async function loadKinds() {
      try {
        const filmstocks = await getFilmstocks()
        const kinds = [...new Set(filmstocks.map((f) => f.kind))]
        setAvailableKinds(kinds)
      } catch (error) {
        toast({
          title: "Error",
          description: "Failed to load filmstock kinds.",
          variant: "destructive",
        })
      }
    }
    loadKinds()
  }, [toast])

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setImageFile(e.target.files[0])
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      const submitData = {
        name: formData.name,
        iso: Number(formData.iso),
        kind: formData.kind,
        expired: formData.expired,
        expiration_date: formData.expiration_date || null,
      }

      let savedFilmstock: Filmstock

      if (filmstock) {
        savedFilmstock = await updateFilmstock(filmstock.id, submitData)
      } else {
        savedFilmstock = await createFilmstock(submitData)
      }

      if (imageFile) {
        await uploadFilmstockImage(savedFilmstock.id, imageFile)
      }

      toast({
        title: `Filmstock ${filmstock ? "updated" : "created"}`,
        description: `The filmstock has been successfully ${filmstock ? "updated" : "created"}.`,
      })

      router.push("/filmstocks")
      router.refresh()
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to save filmstock. Please try again.",
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
              placeholder="e.g., Kodak Portra 400"
              required
            />
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="iso">
                ISO <span className="text-destructive">*</span>
              </Label>
              <Input
                id="iso"
                type="number"
                value={formData.iso}
                onChange={(e) => setFormData({ ...formData, iso: e.target.value })}
                placeholder="e.g., 400"
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="kind">
                Kind <span className="text-destructive">*</span>
              </Label>
              {availableKinds.length > 0 ? (
                <Select value={formData.kind} onValueChange={(value) => setFormData({ ...formData, kind: value })}>
                  <SelectTrigger id="kind">
                    <SelectValue placeholder="Select or enter kind" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableKinds.map((kind) => (
                      <SelectItem key={kind} value={kind}>
                        {kind}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  id="kind"
                  value={formData.kind}
                  onChange={(e) => setFormData({ ...formData, kind: e.target.value })}
                  placeholder="e.g., Color Negative, B&W, Slide"
                  required
                />
              )}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="expiration_date">Expiration Date</Label>
            <Input
              id="expiration_date"
              type="date"
              value={formData.expiration_date}
              onChange={(e) => setFormData({ ...formData, expiration_date: e.target.value })}
            />
          </div>

          <div className="flex items-center space-x-2">
            <Checkbox
              id="expired"
              checked={formData.expired}
              onCheckedChange={(checked) => setFormData({ ...formData, expired: checked as boolean })}
            />
            <Label
              htmlFor="expired"
              className="cursor-pointer text-sm font-normal leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
            >
              Film is expired
            </Label>
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

          <div className="flex gap-3">
            <Button type="submit" disabled={loading}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {filmstock ? "Update Filmstock" : "Create Filmstock"}
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
