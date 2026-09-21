"use client"

import { useSyncExternalStore } from "react"

/** Nothing to subscribe to: the date is read once, when the browser takes over. */
const noSubscribe = () => () => {}

const today = () => new Date().toLocaleDateString([], { dateStyle: "medium" })

/**
 * "Printed 21 Sep 2026" — the date the sheet came off the printer (M4).
 *
 * The server has no business formatting this: it would render in the container's
 * locale and timezone, which are not the reader's, and the two would disagree on
 * hydration. So the server snapshot is empty and the browser fills the slot in
 * with its own date, a moment before anyone reaches the Print button.
 */
export function PrintedOn({ prefix = "Printed" }: { prefix?: string }) {
  const printed = useSyncExternalStore(noSubscribe, today, () => null)
  return <>{printed ? `${prefix} ${printed}` : ""}</>
}
