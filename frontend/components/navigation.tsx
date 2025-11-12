"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { Film, ImageIcon, Camera, Blend as Lens, Package, Search } from "lucide-react"

const navItems = [
  { href: "/films", label: "Films", icon: Film },
  { href: "/images", label: "Images", icon: ImageIcon },
  { href: "/cameras", label: "Cameras", icon: Camera },
  { href: "/lenses", label: "Lenses", icon: Lens },
  { href: "/filmstocks", label: "Filmstocks", icon: Package },
  { href: "/search", label: "Search", icon: Search },
]

export function Navigation() {
  const pathname = usePathname()

  return (
    <nav className="border-b border-border bg-background">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <div className="flex items-center gap-8">
            <Link href="/" className="text-xl font-semibold">
              NegArchive
            </Link>
            <div className="flex gap-1">
              {navItems.map((item) => {
                const Icon = item.icon
                const isActive = pathname.startsWith(item.href)
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-secondary text-secondary-foreground"
                        : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </nav>
  )
}
