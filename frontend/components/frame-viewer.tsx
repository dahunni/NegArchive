"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  Maximize2,
  Trash2,
  ZoomIn,
  ZoomOut,
} from "lucide-react"

import {
  type Film,
  type Image as Frame,
  errorMessage,
  getImageDownloadUrl,
  getPreviewUrl,
  updateImage,
} from "@/lib/api"
import { formatDate, frameLabel } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/hooks/use-toast"

const NO_ROLL = "__none__"
const MIN_ZOOM = 1
const MAX_ZOOM = 6

/**
 * The frame viewer: previous/next, zoom, download and the metadata panel beside the
 * image. It replaces both the old image detail page and the old image edit page.
 */
export function FrameViewer({
  frames,
  index,
  onIndexChange,
  onClose,
  rolls,
  onChanged,
  onDeleted,
}: {
  frames: Frame[]
  index: number
  onIndexChange: (index: number) => void
  onClose: () => void
  rolls: Film[]
  onChanged?: (frame: Frame) => void
  onDeleted?: (frame: Frame) => void
}) {
  const { toast } = useToast()
  const frame = frames[index]

  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const drag = useRef<{ x: number; y: number } | null>(null)

  const [draft, setDraft] = useState({ frame_number: "", capture_date: "", notes: "", film_roll_id: NO_ROLL })
  const [saving, setSaving] = useState(false)
  const [fieldError, setFieldError] = useState<string | null>(null)

  // A different frame resets both the view and the edit draft.
  useEffect(() => {
    if (!frame) return
    setZoom(1)
    setOffset({ x: 0, y: 0 })
    setFieldError(null)
    setDraft({
      frame_number: frame.frame_number === null ? "" : String(frame.frame_number),
      capture_date: frame.capture_date ?? "",
      notes: frame.notes ?? "",
      film_roll_id: frame.film_roll_id === null ? NO_ROLL : String(frame.film_roll_id),
    })
  }, [frame])

  const step = useCallback(
    (delta: number) => {
      if (frames.length < 2) return
      const next = (index + delta + frames.length) % frames.length
      onIndexChange(next)
    },
    [frames.length, index, onIndexChange],
  )

  // Arrow keys move between frames unless the user is typing in the metadata panel.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return
      if (event.key === "ArrowLeft") {
        event.preventDefault()
        step(-1)
      } else if (event.key === "ArrowRight") {
        event.preventDefault()
        step(1)
      } else if (event.key === "+" || event.key === "=") {
        setZoom((z) => Math.min(MAX_ZOOM, z + 0.5))
      } else if (event.key === "-") {
        setZoom((z) => Math.max(MIN_ZOOM, z - 0.5))
      } else if (event.key === "0") {
        setZoom(1)
        setOffset({ x: 0, y: 0 })
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [step])

  if (!frame) return null

  const save = async () => {
    setSaving(true)
    setFieldError(null)
    try {
      const updated = await updateImage(frame.id, {
        frame_number: draft.frame_number.trim() === "" ? null : Number(draft.frame_number),
        capture_date: draft.capture_date.trim() === "" ? null : draft.capture_date,
        notes: draft.notes.trim() === "" ? null : draft.notes,
        film_roll_id: draft.film_roll_id === NO_ROLL ? null : Number(draft.film_roll_id),
      })
      onChanged?.(updated)
      toast({ title: "Frame saved" })
    } catch (error) {
      setFieldError(errorMessage(error, "Could not save this frame."))
    } finally {
      setSaving(false)
    }
  }

  const roll = rolls.find((r) => r.id === frame.film_roll_id) ?? null

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton
        className="flex h-[100dvh] w-screen max-w-none flex-col gap-0 overflow-hidden rounded-none border-0 p-0 sm:max-w-none"
        data-testid="frame-viewer"
      >
        <DialogTitle className="sr-only">{frameLabel(frame)}</DialogTitle>
        <DialogDescription className="sr-only">
          Use the left and right arrow keys to move between frames, Escape to close.
        </DialogDescription>

        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          {/* Image stage */}
          <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-neutral-950">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              key={frame.id}
              src={getPreviewUrl(frame.id, 1600)}
              alt={frameLabel(frame)}
              data-testid="viewer-image"
              className="max-h-full max-w-full object-contain select-none"
              style={{
                transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
                cursor: zoom > 1 ? "grab" : "default",
                transition: drag.current ? "none" : "transform 120ms ease-out",
              }}
              draggable={false}
              onMouseDown={(event) => {
                if (zoom <= 1) return
                drag.current = { x: event.clientX - offset.x, y: event.clientY - offset.y }
              }}
              onMouseMove={(event) => {
                if (!drag.current) return
                setOffset({ x: event.clientX - drag.current.x, y: event.clientY - drag.current.y })
              }}
              onMouseUp={() => {
                drag.current = null
              }}
              onMouseLeave={() => {
                drag.current = null
              }}
              onDoubleClick={() => {
                setZoom((z) => (z > 1 ? 1 : 2))
                setOffset({ x: 0, y: 0 })
              }}
            />

            {frames.length > 1 ? (
              <>
                <Button
                  variant="secondary"
                  size="icon"
                  aria-label="Previous frame"
                  data-testid="viewer-prev"
                  className="absolute top-1/2 left-2 h-12 w-12 -translate-y-1/2 opacity-90"
                  onClick={() => step(-1)}
                >
                  <ChevronLeft className="h-6 w-6" />
                </Button>
                <Button
                  variant="secondary"
                  size="icon"
                  aria-label="Next frame"
                  data-testid="viewer-next"
                  className="absolute top-1/2 right-2 h-12 w-12 -translate-y-1/2 opacity-90"
                  onClick={() => step(1)}
                >
                  <ChevronRight className="h-6 w-6" />
                </Button>
              </>
            ) : null}

            <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full bg-background/90 px-2 py-1 shadow-sm">
              <Button
                variant="ghost"
                size="icon"
                className="h-10 w-10"
                aria-label="Zoom out"
                onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 0.5))}
                disabled={zoom <= MIN_ZOOM}
              >
                <ZoomOut className="h-4 w-4" />
              </Button>
              <span className="type-numeric w-12 text-center" data-testid="viewer-zoom">
                {Math.round(zoom * 100)}%
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-10 w-10"
                aria-label="Zoom in"
                onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 0.5))}
                disabled={zoom >= MAX_ZOOM}
              >
                <ZoomIn className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-10 w-10"
                aria-label="Fit to screen"
                onClick={() => {
                  setZoom(1)
                  setOffset({ x: 0, y: 0 })
                }}
              >
                <Maximize2 className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* Metadata panel */}
          <aside className="w-full shrink-0 overflow-y-auto border-t border-border bg-background p-4 lg:w-96 lg:border-t-0 lg:border-l">
            <div className="flex items-center gap-2">
              <h2 className="type-section">{frameLabel(frame)}</h2>
              <Badge variant="outline" className="type-numeric">
                {index + 1}/{frames.length}
              </Badge>
            </div>
            <p className="mt-1 type-meta">
              {roll ? roll.title : "Not in a roll"} · added {formatDate(frame.created_at)}
            </p>

            <div className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="viewer-frame-number">Frame number</Label>
                  <Input
                    id="viewer-frame-number"
                    data-testid="viewer-frame-number"
                    inputMode="numeric"
                    value={draft.frame_number}
                    onChange={(event) => setDraft({ ...draft, frame_number: event.target.value })}
                    className="h-11"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="viewer-capture-date">Captured</Label>
                  <Input
                    id="viewer-capture-date"
                    type="date"
                    value={draft.capture_date}
                    onChange={(event) => setDraft({ ...draft, capture_date: event.target.value })}
                    className="h-11"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="viewer-roll">Roll</Label>
                <Select
                  value={draft.film_roll_id}
                  onValueChange={(value) => setDraft({ ...draft, film_roll_id: value })}
                >
                  <SelectTrigger id="viewer-roll" className="h-11 w-full">
                    <SelectValue placeholder="Not in a roll" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_ROLL}>Not in a roll</SelectItem>
                    {rolls.map((item) => (
                      <SelectItem key={item.id} value={String(item.id)}>
                        {item.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="viewer-notes">Notes</Label>
                <Textarea
                  id="viewer-notes"
                  value={draft.notes}
                  onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
                  rows={4}
                  placeholder="What is on this frame?"
                />
              </div>

              {fieldError ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {fieldError}
                </p>
              ) : null}

              <div className="flex flex-wrap gap-2">
                <Button onClick={save} disabled={saving} className="min-h-11" data-testid="viewer-save">
                  {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Save
                </Button>
                <Button variant="outline" asChild className="min-h-11">
                  <a href={getImageDownloadUrl(frame)} download>
                    <Download className="mr-2 h-4 w-4" />
                    Download
                  </a>
                </Button>
                {onDeleted ? (
                  <Button
                    variant="ghost"
                    className="min-h-11 text-destructive hover:text-destructive"
                    onClick={() => onDeleted(frame)}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </Button>
                ) : null}
              </div>

              <dl className="space-y-1 border-t border-border pt-3">
                <div className="flex justify-between gap-4">
                  <dt className="type-meta">Type</dt>
                  <dd className="type-body">{frame.type === "scan" ? "Scan" : "Contact sheet"}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="type-meta">File</dt>
                  <dd className="truncate type-numeric" title={frame.path}>
                    {frame.path.split("/").pop()}
                  </dd>
                </div>
              </dl>
            </div>
          </aside>
        </div>
      </DialogContent>
    </Dialog>
  )
}
