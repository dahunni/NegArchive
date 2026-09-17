"use client"

import { useMemo } from "react"

import type { Location, LocationKind } from "@/lib/api"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export const NO_LOCATION = "__none__"

/** The tree flattened in display order, each node with its depth. */
export function flattenLocations(locations: Location[]): { node: Location; depth: number }[] {
  const byParent = new Map<number | null, Location[]>()
  for (const node of locations) {
    const list = byParent.get(node.parent_id) ?? []
    list.push(node)
    byParent.set(node.parent_id, list)
  }
  for (const list of byParent.values()) list.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
  const out: { node: Location; depth: number }[] = []
  const walk = (parent: number | null, depth: number) => {
    for (const node of byParent.get(parent) ?? []) {
      out.push({ node, depth })
      walk(node.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
}

const KIND_ICON: Record<LocationKind, string> = {
  building: "🏛",
  room: "🚪",
  shelf: "▤",
  row: "≡",
  box: "▣",
  binder: "📒",
  envelope: "✉",
  sleeve: "▭",
  other: "•",
}

/**
 * Pick a location from the whole tree. Sleeves that already hold a roll are
 * marked, and a binder can be chosen directly: the API files the roll on its next
 * free page.
 */
export function LocationPicker({
  locations,
  value,
  onChange,
  id,
  placeholder = "Not filed",
  allowKinds,
  occupiedSleeveIds,
}: {
  locations: Location[]
  value: string
  onChange: (value: string) => void
  id?: string
  placeholder?: string
  /** Limit the choices to these kinds (a move dialog offers sleeves, binders, boxes…). */
  allowKinds?: LocationKind[]
  /** Sleeves that hold a roll, to grey out. Derived from `roll_count` when omitted. */
  occupiedSleeveIds?: Set<number>
}) {
  const flat = useMemo(() => flattenLocations(locations), [locations])
  const occupied = useMemo(
    () => occupiedSleeveIds ?? new Set(locations.filter((n) => n.kind === "sleeve" && n.roll_count > 0).map((n) => n.id)),
    [locations, occupiedSleeveIds],
  )
  return (
    <Select value={value || NO_LOCATION} onValueChange={(next) => onChange(next === NO_LOCATION ? "" : next)}>
      <SelectTrigger id={id} className="h-11 w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="max-h-80">
        <SelectItem value={NO_LOCATION}>{placeholder}</SelectItem>
        {flat.map(({ node, depth }) => {
          const disabled = allowKinds ? !allowKinds.includes(node.kind) : false
          const taken = node.kind === "sleeve" && occupied.has(node.id) && String(node.id) !== value
          return (
            <SelectItem key={node.id} value={String(node.id)} disabled={disabled || taken}>
              <span style={{ paddingLeft: `${depth * 0.75}rem` }}>
                <span className="mr-1.5 opacity-70">{KIND_ICON[node.kind]}</span>
                {node.label}
                {node.kind === "binder" ? " (next free page)" : ""}
                {taken ? " · occupied" : ""}
              </span>
            </SelectItem>
          )
        })}
      </SelectContent>
    </Select>
  )
}
