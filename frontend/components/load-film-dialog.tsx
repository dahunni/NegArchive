"use client"

import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

import { ApiError, type Camera, type Filmstock, type Lens, errorMessage, loadFilm } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useToast } from "@/hooks/use-toast"

const NONE = "__none__"

/**
 * "Load film" on a camera (M4 lifecycle): creates the roll the moment the film goes
 * in, so unshot rolls exist in the archive. The API refuses while another roll is
 * still in the camera; the dialog then offers to load anyway.
 */
export function LoadFilmDialog({
  camera,
  open,
  onOpenChange,
  filmstocks,
  lenses,
}: {
  camera: Camera | null
  open: boolean
  onOpenChange: (open: boolean) => void
  filmstocks: Filmstock[]
  lenses: Lens[]
}) {
  const router = useRouter()
  const { toast } = useToast()
  const [title, setTitle] = useState("")
  const [stock, setStock] = useState(NONE)
  const [lens, setLens] = useState(NONE)
  const [busy, setBusy] = useState(false)
  const [occupied, setOccupied] = useState<string | null>(null)

  // The mount narrows the list, but never hides what is already chosen (R#78):
  // a select whose value is not among its items shows nothing at all.
  const usableLenses = camera?.mount
    ? lenses.filter((l) => !l.mount || l.mount === camera.mount || String(l.id) === lens)
    : lenses

  // Every camera gets an empty form (R#69); nothing is carried over from the last one.
  useEffect(() => {
    if (!open) return
    setTitle("")
    setStock(NONE)
    setLens(NONE)
    setOccupied(null)
  }, [open, camera])

  const submit = async (force = false) => {
    if (!camera) return
    setBusy(true)
    try {
      const film = await loadFilm(camera.id, {
        title: title.trim() || undefined,
        film_stock_id: stock === NONE ? null : Number(stock),
        lens_id: lens === NONE ? null : Number(lens),
        force,
      })
      toast({ title: `${film.archive_serial} loaded in ${camera.name}` })
      onOpenChange(false)
      setTitle("")
      setStock(NONE)
      setLens(NONE)
      setOccupied(null)
      router.push(`/films/${film.id}`)
      router.refresh()
    } catch (error) {
      if (error instanceof ApiError && error.code === "camera_occupied") {
        setOccupied(error.message)
        return
      }
      toast({ title: "Could not load the film", description: errorMessage(error), variant: "destructive" })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="load-film-dialog">
        <DialogHeader>
          <DialogTitle>Load film into {camera?.name}</DialogTitle>
          <DialogDescription>Creates the roll now, with a serial, so it shows up under “In cameras”.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="load-stock">Film stock</Label>
            <Select value={stock} onValueChange={setStock}>
              <SelectTrigger id="load-stock" className="h-11">
                <SelectValue placeholder="Film stock" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Not recorded</SelectItem>
                {filmstocks.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.name}
                    {s.iso ? ` · ISO ${s.iso}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="load-lens">Lens</Label>
            <Select value={lens} onValueChange={setLens}>
              <SelectTrigger id="load-lens" className="h-11">
                <SelectValue placeholder="Lens" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Not recorded</SelectItem>
                {usableLenses.map((l) => (
                  <SelectItem key={l.id} value={String(l.id)}>
                    {l.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="load-title">Title</Label>
            <Input id="load-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Leave empty for “<film> in <camera>, <date>”" className="h-11" />
          </div>
          {occupied ? (
            <p role="alert" className="type-body text-destructive">
              {occupied}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          {occupied ? (
            <Button variant="destructive" onClick={() => submit(true)} disabled={busy}>
              Load anyway
            </Button>
          ) : null}
          <Button onClick={() => submit(false)} disabled={busy} data-testid="load-film-confirm">
            {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Load film
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
