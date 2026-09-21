"use client"

import { useEffect, useState } from "react"
import { Loader2, MapPin } from "lucide-react"

import { type Film, type Location, type RollBrief, errorMessage, getLocations, moveRoll, bulkMoveRolls } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LocationPicker } from "@/components/location-picker"
import { useToast } from "@/hooks/use-toast"

/**
 * Move one roll or many. A binder as the target means "next free page"; the API
 * refuses an occupied sleeve with a 409 that names the roll already in it.
 */
export function MoveRollDialog({
  open,
  onOpenChange,
  rolls,
  onMoved,
  locations: preloaded,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  rolls: (Film | RollBrief)[]
  onMoved?: (paths: (string | null)[]) => void
  locations?: Location[]
}) {
  const { toast } = useToast()
  const [locations, setLocations] = useState<Location[]>(preloaded ?? [])
  const [target, setTarget] = useState("")
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setNote("")
    if (preloaded) {
      setLocations(preloaded)
      return
    }
    getLocations()
      .then(setLocations)
      .catch((caught) => setError(errorMessage(caught)))
  }, [open, preloaded])

  const single = rolls.length === 1 ? rolls[0] : null
  // Seeded when the dialog opens or the roll changes — not on every new object with
  // the same id, which a background refresh produces while the picker is open (R#96).
  const singleId = single?.id ?? null
  useEffect(() => {
    if (open) setTarget(single?.location_id ? String(single.location_id) : "")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, singleId])

  const move = async () => {
    setBusy(true)
    setError(null)
    try {
      const locationId = target ? Number(target) : null
      let paths: (string | null)[]
      if (single) {
        const result = await moveRoll(single.id, locationId, note || undefined)
        paths = [result.path]
      } else {
        const results = await bulkMoveRolls(
          rolls.map((r) => r.id),
          locationId,
          note || undefined,
        )
        paths = results.map((r) => r.path)
      }
      toast({
        title: rolls.length === 1 ? "Roll moved" : `${rolls.length} rolls moved`,
        description: paths[0] ? `Now in ${paths[0]}${paths.length > 1 ? " …" : ""}` : "Now unfiled",
      })
      onMoved?.(paths)
      onOpenChange(false)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="move-dialog">
        <DialogHeader>
          <DialogTitle>
            <MapPin className="mr-2 inline h-5 w-5" />
            {single ? `Move ${single.archive_serial ?? single.title}` : `Move ${rolls.length} rolls`}
          </DialogTitle>
          <DialogDescription>
            Pick the sleeve, binder, box or envelope the negatives go into. Choosing a binder files the roll on
            its next free page.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="move-target">Destination</Label>
            <LocationPicker id="move-target" locations={locations} value={target} onChange={setTarget} placeholder="Unfiled (take it out)" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="move-note">Note</Label>
            <Input id="move-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Re-sleeved from the DM envelope" className="h-11" />
          </div>
          {error ? (
            <p role="alert" className="text-xs font-medium text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={move} disabled={busy} data-testid="move-confirm">
            {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Move
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
