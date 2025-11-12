"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { useToast } from "@/hooks/use-toast"
import { bulkUploadImages, bulkUploadZip, createContactSheet, uploadImage } from "@/lib/api"
import { Loader2, Upload, FileArchive, Images } from "lucide-react"

interface FilmDumpActionsProps {
  filmId: number
}

export function FilmDumpActions({ filmId }: FilmDumpActionsProps) {
  const router = useRouter()
  const { toast } = useToast()
  const [loadingContact, setLoadingContact] = useState(false)
  const [loadingContactUpload, setLoadingContactUpload] = useState(false)
  const [loadingBulk, setLoadingBulk] = useState(false)
  const [loadingZip, setLoadingZip] = useState(false)

  const handleCreateContactSheet = async () => {
    try {
      setLoadingContact(true)
      const res = await createContactSheet(filmId, { columns: 6, thumb_size: 300 })
      if ((res as any).error) {
        toast({ title: "Contact sheet failed", description: (res as any).error, variant: "destructive" })
        return
      }
      toast({ title: "Contact sheet created" })
      // Redirect to the film view page so the user sees the new contact sheet
      router.push(`/films/${filmId}`)
      router.refresh()
    } catch (e) {
      toast({ title: "Contact sheet failed", description: String(e), variant: "destructive" })
    } finally {
      setLoadingContact(false)
    }
  }

  const handleBulkFilesChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : []
    if (files.length === 0) return
    try {
      setLoadingBulk(true)
      const res = await bulkUploadImages(filmId, files)
      if ("error" in res) {
        toast({ title: "Bulk upload failed", description: res.error, variant: "destructive" })
        return
      }
      const count = res.images?.length ?? 0
      toast({ title: `Uploaded ${count} images` })
      router.refresh()
    } catch (e) {
      toast({ title: "Bulk upload failed", description: String(e), variant: "destructive" })
    } finally {
      setLoadingBulk(false)
      e.target.value = ""
    }
  }

  const handleZipChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      setLoadingZip(true)
      const res = await bulkUploadZip(filmId, file)
      if ("error" in res) {
        toast({ title: "ZIP upload failed", description: res.error, variant: "destructive" })
        return
      }
      const count = res.images?.length ?? 0
      toast({ title: `Imported ${count} images from ZIP` })
      router.refresh()
    } catch (e) {
      toast({ title: "ZIP upload failed", description: String(e), variant: "destructive" })
    } finally {
      setLoadingZip(false)
      e.target.value = ""
    }
  }

  const handleContactSheetChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      setLoadingContactUpload(true)
      const formData = new FormData()
      formData.append("file", file)
      formData.append("type", "contact_sheet")
      formData.append("film_roll_id", String(filmId))
      const image = await uploadImage(formData)
      if (!image || (image as any).error) {
        throw new Error((image as any)?.error || "Upload failed")
      }
      toast({ title: "Contact sheet uploaded" })
      router.push(`/films/${filmId}`)
      router.refresh()
    } catch (e) {
      toast({ title: "Contact sheet upload failed", description: String(e), variant: "destructive" })
    } finally {
      setLoadingContactUpload(false)
      e.target.value = ""
    }
  }

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={handleCreateContactSheet} disabled={loadingContact} variant="secondary">
            {loadingContact ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Images className="mr-2 h-4 w-4" />}
            Generate Contact Sheet
          </Button>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="contact-sheet-file">Upload contact sheet (single image)</Label>
            <div className="flex items-center gap-3">
              <Input id="contact-sheet-file" type="file" accept="image/*" onChange={handleContactSheetChange} disabled={loadingContactUpload} />
              <Button type="button" disabled={loadingContactUpload} variant="outline">
                {loadingContactUpload ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
                Upload
              </Button>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="bulk-files">Dump scans (multiple files)</Label>
            <div className="flex items-center gap-3">
              <Input id="bulk-files" type="file" multiple onChange={handleBulkFilesChange} disabled={loadingBulk} />
              <Button type="button" disabled={loadingBulk} variant="outline">
                {loadingBulk ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
                Upload Files
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="zip-file">Dump scans (ZIP)</Label>
            <div className="flex items-center gap-3">
              <Input id="zip-file" type="file" accept=".zip" onChange={handleZipChange} disabled={loadingZip} />
              <Button type="button" disabled={loadingZip} variant="outline">
                {loadingZip ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileArchive className="mr-2 h-4 w-4" />}
                Upload ZIP
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}