"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { ChevronDown, Printer } from "lucide-react"

import { Button } from "@/components/ui/button"

/**
 * The printouts for one or more rolls (M4). Each opens a print-optimised page in
 * a new tab; the browser's Print dialog (or "Save as PDF") does the rest.
 */
export function PrintMenu({ rollIds, label = "Print" }: { rollIds: number[]; label?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const itemRefs = useRef<(HTMLAnchorElement | null)[]>([])
  const ids = rollIds.join(",")
  const single = rollIds.length === 1 ? rollIds[0] : null

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", close)
    return () => document.removeEventListener("mousedown", close)
  }, [open])

  /** A menu closes on Escape and hands focus back to the button that opened it (R#100). */
  const onMenuKeyDown = (event: React.KeyboardEvent, index: number) => {
    if (event.key === "Escape") {
      event.preventDefault()
      setOpen(false)
      buttonRef.current?.focus()
      return
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Home" && event.key !== "End") return
    event.preventDefault()
    const last = itemRefs.current.length - 1
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? last
          : event.key === "ArrowDown"
            ? (index + 1) % (last + 1)
            : (index - 1 + last + 1) % (last + 1)
    itemRefs.current[next]?.focus()
  }

  const items = [
    single !== null ? { href: `/print/roll/${single}`, label: "Sleeve cover sheet (A4)" } : { href: `/print/covers?ids=${ids}`, label: "Sleeve cover sheets (A4 each)" },
    { href: `/print/stickers?ids=${ids}`, label: "Small stickers (50 × 25 mm)" },
    { href: `/print/cards?ids=${ids}`, label: "Index cards (A6, 4 per sheet)" },
  ]

  return (
    <div className="relative" ref={ref}>
      <Button
        ref={buttonRef}
        variant="outline"
        className="min-h-11"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) {
            event.preventDefault()
            setOpen(false)
          } else if (event.key === "ArrowDown" && open) {
            event.preventDefault()
            itemRefs.current[0]?.focus()
          }
        }}
        data-testid="print-menu"
      >
        <Printer className="mr-2 h-4 w-4" />
        {label}
        <ChevronDown className="ml-2 h-3 w-3" />
      </Button>
      {open ? (
        <ul className="absolute right-0 z-30 mt-1 w-64 rounded-md border border-border bg-popover p-1 shadow-md" role="menu">
          {items.map((item, index) => (
            <li key={item.href} role="none">
              <Link
                ref={(node) => {
                  itemRefs.current[index] = node
                }}
                href={item.href}
                target="_blank"
                rel="noopener"
                role="menuitem"
                className="block rounded px-3 py-2 text-sm hover:bg-secondary focus:bg-secondary focus:outline-none"
                onClick={() => setOpen(false)}
                onKeyDown={(event) => onMenuKeyDown(event, index)}
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
