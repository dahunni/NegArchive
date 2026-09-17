"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { CheckCircle2, Printer } from "lucide-react"

import { type PrintQueue as Queue, errorMessage, markPrinted } from "@/lib/api"
import { formatDateRange, formatStorage, pluralize } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { EmptyState } from "@/components/empty-state"
import { PrintMenu } from "@/components/print-menu"
import { StatusBadge } from "@/components/status-stepper"
import { useToast } from "@/hooks/use-toast"

/** Rolls that still need a label (M4): never printed, or moved since the last print. */
export function PrintQueueView({ queue }: { queue: Queue }) {
  const router = useRouter()
  const { toast } = useToast()
  const [selected, setSelected] = useState<Set<number>>(() => new Set(queue.items.map((i) => i.id)))
  const ids = queue.items.filter((i) => selected.has(i.id)).map((i) => i.id)

  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const done = async () => {
    try {
      const count = await markPrinted(ids)
      toast({ title: `${pluralize(count, "label")} marked printed` })
      router.refresh()
    } catch (error) {
      toast({ title: "Could not mark", description: errorMessage(error), variant: "destructive" })
    }
  }

  return (
    <div className="space-y-6" data-testid="print-queue">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="type-page">Print queue</h1>
          <p className="mt-1 type-body text-muted-foreground">
            {pluralize(queue.total, "roll")} without a current label. Open a printout, cut it out, then mark the
            labels printed so the serials freeze.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="min-h-11" asChild>
            <Link href="/print/commands" target="_blank" rel="noopener">
              <Printer className="mr-2 h-4 w-4" />
              Command cards
            </Link>
          </Button>
          {ids.length > 0 ? <PrintMenu rollIds={ids} label={`Print ${ids.length}`} /> : null}
          <Button className="min-h-11" onClick={done} disabled={ids.length === 0} data-testid="mark-all-printed">
            <CheckCircle2 className="mr-2 h-4 w-4" />
            Mark {ids.length} printed
          </Button>
        </div>
      </div>

      {queue.items.length === 0 ? (
        <EmptyState icon={Printer} title="Nothing to print" description="Every roll has a label that matches where it is." />
      ) : (
        <ul className="space-y-2" data-testid="print-queue-list">
          {queue.items.map((roll) => (
            <li key={roll.id} className="flex items-center gap-3 rounded-lg border border-border bg-card p-3">
              <Checkbox checked={selected.has(roll.id)} onCheckedChange={() => toggle(roll.id)} aria-label={`Select ${roll.title}`} className="h-5 w-5" />
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
              <PrintMenu rollIds={[roll.id]} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
