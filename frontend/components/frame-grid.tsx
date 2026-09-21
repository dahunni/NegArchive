"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { CalendarDays, FolderInput, Images, Loader2, Trash2, X } from "lucide-react"

import {
  type Film,
  type Image as Frame,
  bulkDeleteImages,
  bulkUpdateImages,
  errorMessage,
  getPreviewUrl,
  previewVersion,
  updateImage,
} from "@/lib/api"
import { formatDate, formatStripPosition } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { EmptyState } from "@/components/empty-state"
import { FrameViewer } from "@/components/frame-viewer"
import { useToast } from "@/hooks/use-toast"

const NO_ROLL = "__none__"

/**
 * The frame grid of a roll (and of the loose-frames page).
 *
 * - frame number and capture date are visible on every cell, and the number and the
 *   note are edited in place (Enter or blur saves)
 * - arrow keys walk the grid, Enter opens the viewer, Escape drops the selection
 * - checkboxes select; the bar at the bottom deletes, reassigns or dates the selection
 */
export function FrameGrid({
  frames: incoming,
  rolls,
  emptyTitle = "No frames yet",
  emptyDescription = "Drop scans into the upload zone above and they appear here.",
  strips,
}: {
  frames: Frame[]
  rolls: Film[]
  emptyTitle?: string
  emptyDescription?: string
  /** M4: the roll's strip lengths, so each cell can say "Strip 3 · Pos 2". */
  strips?: number[]
}) {
  const router = useRouter()
  const { toast } = useToast()

  const [frames, setFrames] = useState<Frame[]>(incoming)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [focus, setFocus] = useState(0)
  const [viewerIndex, setViewerIndex] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [bulkDate, setBulkDate] = useState("")
  const cellRefs = useRef<(HTMLDivElement | null)[]>([])

  // The server component is the source of truth; local state only exists so an inline
  // edit shows immediately instead of waiting for the refresh round trip.
  useEffect(() => {
    setFrames(incoming)
    setSelected((current) => new Set([...current].filter((id) => incoming.some((f) => f.id === id))))
  }, [incoming])

  // A deletion can leave the roving tabindex and the open viewer pointing past the
  // end of the list (R#92): clamp the one, close the other.
  useEffect(() => {
    setFocus((current) => Math.min(current, Math.max(0, frames.length - 1)))
    setViewerIndex((current) => (current !== null && current >= frames.length ? null : current))
  }, [frames.length])

  const patchLocal = useCallback((frame: Frame) => {
    setFrames((current) => current.map((item) => (item.id === frame.id ? frame : item)))
  }, [])

  const toggle = (id: number) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  /** How many cells fit on one row right now, read off the DOM so it follows the CSS. */
  const columns = useCallback(() => {
    const cells = cellRefs.current.filter(Boolean) as HTMLDivElement[]
    if (cells.length === 0) return 1
    const top = cells[0].offsetTop
    const count = cells.findIndex((cell) => cell.offsetTop > top)
    return count === -1 ? cells.length : Math.max(1, count)
  }, [])

  const moveFocus = (next: number) => {
    const clamped = Math.max(0, Math.min(frames.length - 1, next))
    setFocus(clamped)
    cellRefs.current[clamped]?.focus()
  }

  const onCellKeyDown = (event: React.KeyboardEvent, index: number) => {
    const perRow = columns()
    switch (event.key) {
      case "ArrowRight":
        event.preventDefault()
        moveFocus(index + 1)
        break
      case "ArrowLeft":
        event.preventDefault()
        moveFocus(index - 1)
        break
      case "ArrowDown":
        event.preventDefault()
        moveFocus(index + perRow)
        break
      case "ArrowUp":
        event.preventDefault()
        moveFocus(index - perRow)
        break
      case "Home":
        event.preventDefault()
        moveFocus(0)
        break
      case "End":
        event.preventDefault()
        moveFocus(frames.length - 1)
        break
      case "Enter":
        event.preventDefault()
        setViewerIndex(index)
        break
      case " ":
        event.preventDefault()
        toggle(frames[index].id)
        break
      case "Escape":
        if (selected.size > 0) {
          event.preventDefault()
          setSelected(new Set())
        }
        break
      default:
        break
    }
  }

  const saveField = async (frame: Frame, patch: Partial<Frame>) => {
    try {
      const updated = await updateImage(frame.id, patch)
      patchLocal(updated)
      router.refresh()
    } catch (error) {
      patchLocal(frame) // put the old value back
      toast({ title: "Could not save the frame", description: errorMessage(error), variant: "destructive" })
    }
  }

  const selectedIds = useMemo(() => [...selected], [selected])

  const runBulk = async (action: () => Promise<string>) => {
    setBusy(true)
    try {
      const message = await action()
      toast({ title: message })
      setSelected(new Set())
      router.refresh()
    } catch (error) {
      toast({ title: "Bulk action failed", description: errorMessage(error), variant: "destructive" })
    } finally {
      setBusy(false)
    }
  }

  if (frames.length === 0) {
    return <EmptyState icon={Images} title={emptyTitle} description={emptyDescription} />
  }

  return (
    <div className="space-y-4">
      <div
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
        data-testid="frame-grid"
        role="group"
        aria-label="Frames"
      >
        {frames.map((frame, index) => {
          const isSelected = selected.has(frame.id)
          return (
            <div
              key={frame.id}
              ref={(node) => {
                cellRefs.current[index] = node
              }}
              tabIndex={index === focus ? 0 : -1}
              role="button"
              aria-label={`Frame ${frame.frame_number ?? "unnumbered"}`}
              aria-pressed={isSelected}
              data-testid="frame-cell"
              onFocus={() => setFocus(index)}
              onKeyDown={(event) => onCellKeyDown(event, index)}
              className={cn(
                "rounded-lg border bg-card p-2 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                isSelected ? "border-primary ring-1 ring-primary" : "border-border",
              )}
            >
              <div className="relative">
                <button
                  type="button"
                  className="frame-cell block w-full"
                  onClick={() => setViewerIndex(index)}
                  aria-label={`Open frame ${frame.frame_number ?? "unnumbered"}`}
                  tabIndex={-1}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={getPreviewUrl(frame.id, 480, undefined, previewVersion(frame))}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    data-testid="frame-thumb"
                  />
                </button>
                <span className="absolute top-1 left-1 rounded bg-background/85 p-1">
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={() => toggle(frame.id)}
                    aria-label={`Select frame ${frame.frame_number ?? "unnumbered"}`}
                    className="h-5 w-5"
                  />
                </span>
              </div>

              <div className="mt-2 flex items-center gap-2">
                <span className="type-meta shrink-0">#</span>
                <InlineNumber
                  value={frame.frame_number}
                  ariaLabel={`Frame number of frame ${frame.id}`}
                  onCommit={(value) => {
                    if (value === frame.frame_number) return
                    patchLocal({ ...frame, frame_number: value })
                    void saveField(frame, { frame_number: value })
                  }}
                />
                <span className="ml-auto truncate type-meta">{formatDate(frame.capture_date) ?? "No date"}</span>
              </div>
              {strips ? (
                <p className="type-meta mt-0.5 truncate" data-testid="frame-position">
                  {formatStripPosition(frame.frame_number, strips) ?? "Not on the sleeve"}
                </p>
              ) : null}

              <InlineText
                value={frame.notes}
                placeholder="Add a note"
                ariaLabel={`Notes for frame ${frame.id}`}
                onCommit={(value) => {
                  if ((value ?? "") === (frame.notes ?? "")) return
                  patchLocal({ ...frame, notes: value })
                  void saveField(frame, { notes: value })
                }}
              />
            </div>
          )
        })}
      </div>

      {selected.size > 0 ? (
        <div
          className="sticky bottom-3 z-30 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3 shadow-lg"
          data-testid="bulk-bar"
        >
          <span className="type-body font-medium">
            {selected.size} selected
            {busy ? <Loader2 className="ml-2 inline h-3 w-3 animate-spin" /> : null}
          </span>

          <Select
            value=""
            onValueChange={(value) =>
              void runBulk(async () => {
                const count = (
                  await bulkUpdateImages(selectedIds, {
                    film_roll_id: value === NO_ROLL ? null : Number(value),
                  })
                ).length
                return `${count} frame${count === 1 ? "" : "s"} moved`
              })
            }
          >
            <SelectTrigger className="h-11 w-48" aria-label="Move to roll" data-testid="bulk-move">
              <FolderInput className="mr-2 h-4 w-4" />
              <SelectValue placeholder="Move to roll" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_ROLL}>Remove from roll</SelectItem>
              {rolls.map((roll) => (
                <SelectItem key={roll.id} value={String(roll.id)}>
                  {roll.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="flex items-center gap-2">
            <CalendarDays className="h-4 w-4 text-muted-foreground" />
            <Input
              type="date"
              value={bulkDate}
              aria-label="Capture date for the selected frames"
              data-testid="bulk-date"
              className="h-11 w-40"
              onChange={(event) => setBulkDate(event.target.value)}
            />
            <Button
              variant="outline"
              className="min-h-11"
              disabled={!bulkDate || busy}
              onClick={() =>
                void runBulk(async () => {
                  const count = (await bulkUpdateImages(selectedIds, { capture_date: bulkDate })).length
                  setBulkDate("")
                  return `Capture date set on ${count} frame${count === 1 ? "" : "s"}`
                })
              }
            >
              Set date
            </Button>
          </div>

          <Button
            variant="ghost"
            className="min-h-11 text-destructive hover:text-destructive"
            disabled={busy}
            onClick={() => setConfirmDelete(true)}
            data-testid="bulk-delete"
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Delete
          </Button>

          <Button variant="ghost" className="ml-auto min-h-11" onClick={() => setSelected(new Set())}>
            <X className="mr-2 h-4 w-4" />
            Clear
          </Button>
        </div>
      ) : null}

      {viewerIndex !== null ? (
        <FrameViewer
          frames={frames}
          index={viewerIndex}
          onIndexChange={setViewerIndex}
          onClose={() => setViewerIndex(null)}
          rolls={rolls}
          onChanged={(frame) => {
            patchLocal(frame)
            router.refresh()
          }}
        />
      ) : null}

      <DeleteConfirmationDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        offerKeepFiles
        title={`Delete ${selected.size} frame${selected.size === 1 ? "" : "s"}?`}
        description="The frame records are removed from the archive, and their scan files are deleted with them."
        onConfirm={({ keepFiles }) => {
          setConfirmDelete(false)
          void runBulk(async () => {
            const count = await bulkDeleteImages(selectedIds, keepFiles)
            return `${count} frame${count === 1 ? "" : "s"} deleted${
              keepFiles ? ", files kept on disk" : ""
            }`
          })
        }}
      />
    </div>
  )
}

/** A number that looks like text until you click it; Enter or blur saves. */
function InlineNumber({
  value,
  onCommit,
  ariaLabel,
}: {
  value: number | null
  onCommit: (value: number | null) => void
  ariaLabel: string
}) {
  const [draft, setDraft] = useState(value === null ? "" : String(value))
  useEffect(() => setDraft(value === null ? "" : String(value)), [value])

  const commit = () => {
    const trimmed = draft.trim()
    if (trimmed === "") return onCommit(null)
    const parsed = Number(trimmed)
    if (!Number.isFinite(parsed) || parsed < 0) {
      setDraft(value === null ? "" : String(value))
      return
    }
    onCommit(Math.trunc(parsed))
  }

  return (
    <input
      value={draft}
      aria-label={ariaLabel}
      data-testid="frame-number-input"
      inputMode="numeric"
      placeholder="—"
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault()
          ;(event.target as HTMLInputElement).blur()
        } else if (event.key === "Escape") {
          setDraft(value === null ? "" : String(value))
          ;(event.target as HTMLInputElement).blur()
        }
        event.stopPropagation()
      }}
      className="w-12 rounded border border-transparent bg-transparent px-1 py-0.5 type-numeric hover:border-border focus:border-ring focus:bg-background focus:outline-none"
    />
  )
}

function InlineText({
  value,
  onCommit,
  ariaLabel,
  placeholder,
}: {
  value: string | null
  onCommit: (value: string | null) => void
  ariaLabel: string
  placeholder: string
}) {
  const [draft, setDraft] = useState(value ?? "")
  useEffect(() => setDraft(value ?? ""), [value])

  return (
    <input
      value={draft}
      aria-label={ariaLabel}
      data-testid="frame-notes-input"
      placeholder={placeholder}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => onCommit(draft.trim() === "" ? null : draft.trim())}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault()
          ;(event.target as HTMLInputElement).blur()
        } else if (event.key === "Escape") {
          setDraft(value ?? "")
          ;(event.target as HTMLInputElement).blur()
        }
        event.stopPropagation()
      }}
      className="mt-1 w-full truncate rounded border border-transparent bg-transparent px-1 py-0.5 type-body hover:border-border focus:border-ring focus:bg-background focus:outline-none"
    />
  )
}
