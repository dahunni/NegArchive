"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { CheckCircle2, Loader2, Printer } from "lucide-react"

import {
  type PrintQueue as Queue,
  PRINT_QUEUE_PAGE,
  errorMessage,
  getPrintQueue,
  markPrinted,
} from "@/lib/api"
import { formatDateRange, formatStorage, pluralize } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { EmptyState } from "@/components/empty-state"
import { PrintMenu } from "@/components/print-menu"
import { StatusBadge } from "@/components/status-stepper"
import { useToast } from "@/hooks/use-toast"

/**
 * Rolls that still need a label (M4): never printed, or moved since the last print.
 *
 * Two things this page learned the hard way. It is **paged** — an archive that has
 * never printed a label has its whole catalogue in the queue, and a list of every
 * roll you own is something you scroll past rather than work through. And nothing
 * is selected until you select it: "mark printed" freezes a serial, and a button
 * that arrives reading "Mark 145 printed" is one click away from freezing the lot.
 */
export function PrintQueueView({ queue: firstPage }: { queue: Queue }) {
  const router = useRouter()
  const { toast } = useToast()

  const [items, setItems] = useState(firstPage.items)
  const [total, setTotal] = useState(firstPage.total)
  const [hasMore, setHasMore] = useState(Boolean(firstPage.has_more))
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(() => new Set())
  const [marking, setMarking] = useState(false)

  const ids = items.filter((item) => selected.has(item.id)).map((item) => item.id)
  const allShownSelected = items.length > 0 && items.every((item) => selected.has(item.id))

  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const selectShown = () =>
    setSelected((current) => {
      const next = new Set(current)
      if (allShownSelected) items.forEach((item) => next.delete(item.id))
      else items.forEach((item) => next.add(item.id))
      return next
    })

  const loadMore = async () => {
    setLoading(true)
    try {
      const next = await getPrintQueue({ limit: PRINT_QUEUE_PAGE, offset: items.length })
      setItems((current) => [...current, ...next.items])
      setTotal(next.total)
      setHasMore(Boolean(next.has_more))
    } catch (error) {
      toast({ title: "Could not load more", description: errorMessage(error), variant: "destructive" })
    } finally {
      setLoading(false)
    }
  }

  const done = async () => {
    setMarking(true)
    try {
      const count = await markPrinted(ids)
      toast({
        title: `${pluralize(count, "label")} marked printed`,
        description: "Their serials are frozen now; a move puts them back in the queue.",
      })
      setSelected(new Set())
      router.refresh()
    } catch (error) {
      toast({ title: "Could not mark", description: errorMessage(error), variant: "destructive" })
    } finally {
      setMarking(false)
    }
  }

  return (
    <div className="space-y-6" data-testid="print-queue">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="type-page">Print queue</h1>
          <p className="mt-1 type-body text-muted-foreground">
            {pluralize(total, "roll")} without a current label. Open a printout, cut it out, then mark those
            labels printed — that freezes their serials, and a later move puts a roll back in the queue.
          </p>
        </div>
        <div className="flex flex-wrap gap-2" data-print-hide>
          <Button variant="outline" className="min-h-11" asChild>
            <Link href="/print/commands" target="_blank" rel="noopener">
              <Printer className="mr-2 h-4 w-4" />
              Command cards
            </Link>
          </Button>
          {ids.length > 0 ? <PrintMenu rollIds={ids} label={`Print ${ids.length}`} /> : null}
          <Button
            className="min-h-11"
            onClick={done}
            disabled={ids.length === 0 || marking}
            data-testid="mark-all-printed"
          >
            {marking ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="mr-2 h-4 w-4" />
            )}
            {ids.length === 0 ? "Mark printed" : `Mark ${ids.length} printed`}
          </Button>
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState
          icon={Printer}
          title="Nothing to print"
          description="Every roll has a label that matches where it is."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3" data-print-hide>
            <label className="flex items-center gap-2">
              <Checkbox
                checked={allShownSelected}
                onCheckedChange={selectShown}
                aria-label={allShownSelected ? "Clear the selection" : "Select the rolls shown"}
                data-testid="select-shown"
                className="h-5 w-5"
              />
              <span className="type-body">
                {allShownSelected ? "Clear selection" : `Select these ${items.length}`}
              </span>
            </label>
            <span className="type-meta" data-testid="queue-count">
              {selected.size > 0 ? `${selected.size} selected · ` : ""}
              showing {items.length} of {total}
            </span>
          </div>

          <ul className="space-y-2" data-testid="print-queue-list">
            {items.map((roll) => (
              <li key={roll.id} className="flex items-center gap-3 rounded-lg border border-border bg-card p-3">
                <Checkbox
                  checked={selected.has(roll.id)}
                  onCheckedChange={() => toggle(roll.id)}
                  aria-label={`Select ${roll.title}`}
                  className="h-5 w-5"
                  data-print-hide
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link href={`/films/${roll.id}`} className="truncate type-body font-medium hover:underline">
                      {roll.title}
                    </Link>
                    <Badge variant="outline" className="type-numeric">
                      {roll.archive_serial}
                    </Badge>
                    <StatusBadge status={roll.status} />
                    <Badge variant={roll.reason === "moved_since_print" ? "secondary" : "outline"} className="text-xs">
                      {roll.reason === "moved_since_print" ? "moved since last print" : "never printed"}
                    </Badge>
                  </div>
                  <p className="type-meta truncate">
                    {formatDateRange(roll.start_date, roll.end_date)} · {formatStorage(roll)}
                  </p>
                </div>
                <div data-print-hide>
                  <PrintMenu rollIds={[roll.id]} />
                </div>
              </li>
            ))}
          </ul>

          {hasMore ? (
            <div className="flex justify-center" data-print-hide>
              <Button variant="outline" className="min-h-11" onClick={loadMore} disabled={loading} data-testid="queue-load-more">
                {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Load {Math.min(PRINT_QUEUE_PAGE, total - items.length)} more
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
