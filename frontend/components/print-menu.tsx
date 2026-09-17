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

  const items = [
    single !== null ? { href: `/print/roll/${single}`, label: "Sleeve cover sheet (A4)" } : { href: `/print/covers?ids=${ids}`, label: "Sleeve cover sheets (A4 each)" },
    { href: `/print/stickers?ids=${ids}`, label: "Small stickers (50 × 25 mm)" },
    { href: `/print/cards?ids=${ids}`, label: "Index cards (A6, 4 per sheet)" },
  ]

  return (
    <div className="relative" ref={ref}>
      <Button variant="outline" className="min-h-11" onClick={() => setOpen((o) => !o)} aria-expanded={open} data-testid="print-menu">
        <Printer className="mr-2 h-4 w-4" />
        {label}
        <ChevronDown className="ml-2 h-3 w-3" />
      </Button>
      {open ? (
        <ul className="absolute right-0 z-30 mt-1 w-64 rounded-md border border-border bg-popover p-1 shadow-md" role="menu">
          {items.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                target="_blank"
                rel="noopener"
                role="menuitem"
                className="block rounded px-3 py-2 text-sm hover:bg-secondary"
                onClick={() => setOpen(false)}
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
