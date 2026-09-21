"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Search } from "lucide-react"

import {
  ACCEPTED_IMAGE_TYPES,
  type Film,
  type Image as Frame,
  type ImageQuery,
  type Page,
  errorMessage,
  getImagesPage,
  uploadLooseFile,
} from "@/lib/api"
import { pluralize } from "@/lib/format"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ErrorState } from "@/components/error-state"
import { FrameGrid } from "@/components/frame-grid"
import { UploadZone } from "@/components/upload-zone"
import { useToast } from "@/hooks/use-toast"

const ALL = "__all__"
const LOOSE = "__loose__"
const DEBOUNCE_MS = 250

/**
 * Every frame in the archive, including the ones that are not in a roll yet. The roll
 * list is the way in; this page is how a stray scan finds its roll again.
 *
 * M3 (R#20): the roll filter and the search run in Postgres and the grid pages,
 * because "every frame in the archive" is the one list that grows without limit —
 * 36 frames per roll, forever.
 */
export function FramesBrowser({
  initial,
  rolls,
}: {
  initial: Page<Frame>
  rolls: Film[]
}) {
  const router = useRouter()
  const { toast } = useToast()

  const [roll, setRoll] = useState(ALL)
  const [query, setQuery] = useState("")

  const [items, setItems] = useState<Frame[]>(initial.items)
  const [total, setTotal] = useState(initial.total)
  const [hasMore, setHasMore] = useState(initial.has_more)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const filters: ImageQuery = useMemo(
    () => ({
      type: "scan",
      q: query.trim() || undefined,
      film_id: roll === ALL || roll === LOOSE ? undefined : Number(roll),
      unassigned: roll === LOOSE ? true : undefined,
    }),
    [roll, query],
  )

  /**
   * R#71: every request takes a ticket, and only the newest one is allowed to write
   * to the list — so a slow answer for an older search cannot replace a newer one,
   * and "Load more" appends only while the filters it asked with still apply.
   */
  const request = useRef(0)
  const currentFilters = useRef(filters)
  useEffect(() => {
    currentFilters.current = filters
  }, [filters])

  const fetchPage = useCallback(
    async (offset: number, append: boolean) => {
      const ticket = (request.current += 1)
      const asked = filters
      setLoading(true)
      try {
        const page = await getImagesPage({ ...filters, offset })
        if (ticket !== request.current || (append && currentFilters.current !== asked)) return
        setItems((current) => (append ? [...current, ...page.items] : page.items))
        setTotal(page.total)
        setHasMore(page.has_more)
        setLoadError(null)
      } catch (error) {
        if (ticket !== request.current) return
        setLoadError(errorMessage(error, "Could not load the frames."))
      } finally {
        if (ticket === request.current) setLoading(false)
      }
    },
    [filters],
  )

  const hydrated = useRef(false)
  useEffect(() => {
    if (!hydrated.current) {
      hydrated.current = true
      return
    }
    const handle = window.setTimeout(() => fetchPage(0, false), DEBOUNCE_MS)
    return () => window.clearTimeout(handle)
  }, [fetchPage])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="type-page">Frames</h1>
        <p className="mt-1 type-body text-muted-foreground">
          {pluralize(total, "frame")} {roll === ALL && !query ? "scanned" : "match this filter"}
          {items.length < total ? ` · showing ${items.length}` : ""}
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

        <div className="w-full space-y-1.5 sm:w-72">
          <Label htmlFor="frames-search">Search</Label>
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="frames-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Note or original filename…"
              className="h-11 pl-9"
              data-testid="frame-search"
            />
          </div>
        </div>
      </div>

      <UploadZone
        upload={uploadLooseFile}
        onUploaded={(images) => {
          toast({
            title: `${pluralize(images.length, "frame")} uploaded`,
            description: "Select them and use “Move to roll” to file them.",
          })
          fetchPage(0, false)
          router.refresh()
        }}
        hint="Drop scans that do not belong to a roll yet"
        accept={ACCEPTED_IMAGE_TYPES}
      />

      {loadError ? (
        <ErrorState
          title="Could not load the frames"
          error={new Error(loadError)}
          reset={() => fetchPage(0, false)}
        />
      ) : (
        <>
          <FrameGrid
            frames={items}
            rolls={rolls}
            emptyTitle="No frames here"
            emptyDescription="Upload scans above, or pick another roll."
          />

          {hasMore ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                className="min-h-11"
                disabled={loading}
                onClick={() => fetchPage(items.length, true)}
                data-testid="load-more-frames"
              >
                {loading ? "Loading…" : `Load more (${total - items.length} left)`}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
