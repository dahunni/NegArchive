"use client"

import { useMemo, useState } from "react"
import { useRouter } from "next/navigation"

import { type Film, type Image as Frame, uploadLooseFile } from "@/lib/api"
import { pluralize } from "@/lib/format"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { FrameGrid } from "@/components/frame-grid"
import { UploadZone } from "@/components/upload-zone"
import { useToast } from "@/hooks/use-toast"

const ALL = "__all__"
const LOOSE = "__loose__"

/**
 * Every frame in the archive, including the ones that are not in a roll yet. The roll
 * list is the way in; this page is how a stray scan finds its roll again.
 */
export function FramesBrowser({ frames, rolls }: { frames: Frame[]; rolls: Film[] }) {
  const router = useRouter()
  const { toast } = useToast()
  const [roll, setRoll] = useState(ALL)

  const visible = useMemo(() => {
    if (roll === ALL) return frames
    if (roll === LOOSE) return frames.filter((frame) => frame.film_roll_id === null)
    return frames.filter((frame) => frame.film_roll_id === Number(roll))
  }, [frames, roll])

  const looseCount = frames.filter((frame) => frame.film_roll_id === null).length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="type-page">Frames</h1>
        <p className="mt-1 type-body text-muted-foreground">
          {pluralize(frames.length, "frame")} scanned
          {looseCount > 0 ? ` · ${looseCount} not in a roll` : ""}
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full space-y-1.5 sm:w-64">
          <Label htmlFor="frames-roll">Roll</Label>
          <Select value={roll} onValueChange={setRoll}>
            <SelectTrigger id="frames-roll" className="h-11 w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All rolls</SelectItem>
              <SelectItem value={LOOSE}>Not in a roll</SelectItem>
              {rolls.map((item) => (
                <SelectItem key={item.id} value={String(item.id)}>
                  {item.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <UploadZone
        upload={uploadLooseFile}
        onUploaded={(images) => {
          toast({
            title: `${pluralize(images.length, "frame")} uploaded`,
            description: "Select them and use “Move to roll” to file them.",
          })
          router.refresh()
        }}
        hint="Drop scans that do not belong to a roll yet"
        accept="image/*,.tif,.tiff"
      />

      <FrameGrid
        frames={visible}
        rolls={rolls}
        emptyTitle="No frames here"
        emptyDescription="Upload scans above, or pick another roll."
      />
    </div>
  )
}
