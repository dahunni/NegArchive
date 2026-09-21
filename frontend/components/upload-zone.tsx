"use client"

import { useCallback, useRef, useState } from "react"
import { CheckCircle2, FileArchive, ImageIcon, Upload, XCircle } from "lucide-react"

import { ACCEPTED_IMAGE_TYPES, type Image as Frame, errorMessage } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"

interface QueueItem {
  key: string
  name: string
  progress: number
  status: "waiting" | "uploading" | "done" | "failed"
  detail?: string
}

const CONCURRENCY = 2

/**
 * Drag files (or a ZIP) anywhere onto this box, or tap it to pick some. Each file is
 * uploaded on its own request so the progress bar next to it is real; ZIPs go to the
 * ZIP importer and report how many frames came out.
 */
export function UploadZone({
  upload,
  onUploaded,
  hint = "Drop scans or a ZIP here",
  // The backend's allowlist plus ZIP (M2, R#18): offering more only earns a 415.
  accept = `${ACCEPTED_IMAGE_TYPES},.zip`,
  className,
}: {
  upload: (file: File, onProgress: (fraction: number) => void) => Promise<{ images: Frame[] }>
  onUploaded: (images: Frame[]) => void
  hint?: string
  accept?: string
  className?: string
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [queue, setQueue] = useState<QueueItem[]>([])
  /**
   * How many batches are in flight, not whether one is (R#91): dropping a second
   * file while the first is uploading used to make "Clear list" appear the moment
   * the earlier batch finished, with the later one still running.
   */
  const [inFlight, setInFlight] = useState(0)
  const busy = inFlight > 0
  /**
   * `dragenter`/`dragleave` fire for every child the pointer crosses, so a plain
   * boolean flickers as the cursor moves inside the box. Counting the depth does not.
   */
  const dragDepth = useRef(0)

  const patch = useCallback((key: string, values: Partial<QueueItem>) => {
    setQueue((items) => items.map((item) => (item.key === key ? { ...item, ...values } : item)))
  }, [])

  const run = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return
      const items: QueueItem[] = files.map((file, index) => ({
        key: `${Date.now()}-${index}-${file.name}`,
        name: file.name,
        progress: 0,
        status: "waiting",
      }))
      setQueue((existing) => [...existing, ...items])
      setInFlight((count) => count + 1)

      const uploaded: Frame[] = []
      let cursor = 0
      const worker = async () => {
        while (cursor < files.length) {
          const index = cursor++
          const item = items[index]
          patch(item.key, { status: "uploading" })
          try {
            const result = await upload(files[index], (fraction) =>
              patch(item.key, { progress: Math.round(fraction * 100) }),
            )
            uploaded.push(...result.images)
            patch(item.key, {
              status: "done",
              progress: 100,
              detail:
                result.images.length === 1 ? undefined : `${result.images.length} frames`,
            })
          } catch (error) {
            patch(item.key, { status: "failed", detail: errorMessage(error, "Upload failed.") })
          }
        }
      }

      try {
        await Promise.all(Array.from({ length: Math.min(CONCURRENCY, files.length) }, worker))
      } finally {
        setInFlight((count) => count - 1)
      }
      if (uploaded.length > 0) onUploaded(uploaded)
    },
    [onUploaded, patch, upload],
  )

  const pending = queue.filter((item) => item.status !== "done").length

  return (
    <div className={cn("space-y-3", className)}>
      <div
        role="button"
        tabIndex={0}
        aria-label={hint}
        data-testid="upload-zone"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            inputRef.current?.click()
          }
        }}
        onDragEnter={(event) => {
          event.preventDefault()
          dragDepth.current += 1
          setDragging(true)
        }}
        onDragOver={(event) => {
          event.preventDefault()
        }}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1)
          if (dragDepth.current === 0) setDragging(false)
        }}
        onDrop={(event) => {
          event.preventDefault()
          dragDepth.current = 0
          setDragging(false)
          void run(Array.from(event.dataTransfer.files))
        }}
        className={cn(
          "flex min-h-32 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors",
          dragging
            ? "border-primary bg-secondary"
            : "border-border hover:border-muted-foreground/50 hover:bg-secondary/40",
        )}
      >
        <Upload className="h-6 w-6 text-muted-foreground" />
        <p className="type-body font-medium">{hint}</p>
        <p className="type-meta">
          JPEG, PNG, TIFF or a ZIP of a whole roll. Multiple files at once are fine.
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          data-testid="upload-input"
          className="sr-only"
          onChange={(event) => {
            void run(Array.from(event.target.files ?? []))
            event.target.value = ""
          }}
        />
      </div>

      {queue.length > 0 ? (
        <ul className="space-y-2" data-testid="upload-queue">
          {queue.map((item) => (
            <li key={item.key} className="rounded-md border border-border px-3 py-2">
              <div className="flex items-center gap-2">
                {item.name.toLowerCase().endsWith(".zip") ? (
                  <FileArchive className="h-4 w-4 shrink-0 text-muted-foreground" />
                ) : (
                  <ImageIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                )}
                <span className="truncate type-body">{item.name}</span>
                <span className="ml-auto flex shrink-0 items-center gap-2 type-meta">
                  {item.detail}
                  {item.status === "done" ? (
                    <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
                  ) : null}
                  {item.status === "failed" ? <XCircle className="h-4 w-4 text-destructive" /> : null}
                  {item.status === "uploading" ? `${item.progress}%` : null}
                </span>
              </div>
              {item.status === "failed" ? null : (
                <Progress value={item.status === "waiting" ? 0 : item.progress} className="mt-2 h-1" />
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {queue.length > 0 && !busy ? (
        <Button variant="ghost" size="sm" onClick={() => setQueue([])}>
          Clear list{pending > 0 ? ` (${pending} not uploaded)` : ""}
        </Button>
      ) : null}
    </div>
  )
}
