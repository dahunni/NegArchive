"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"
import { Film, Images, Menu, Settings, Wrench } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { LanFooter } from "@/components/lan-footer"
import { LoginGate } from "@/components/login-gate"
import { OfflineBanner } from "@/components/offline-banner"
import { ThemeToggle } from "@/components/theme-toggle"

/**
 * Four destinations, not six: rolls are the work, frames are everything loose, gear
 * is the catalog, settings is where the archive itself lives. Search used to be a
 * page; it is now the filter bar on the roll list.
 */
const NAV = [
  { href: "/", label: "Rolls", icon: Film, match: (p: string) => p === "/" || p.startsWith("/films") },
  { href: "/images", label: "Frames", icon: Images, match: (p: string) => p.startsWith("/images") },
  { href: "/gear", label: "Gear", icon: Wrench, match: (p: string) => p.startsWith("/gear") },
  // M3: linked folders, the watch toggle, backup and export.
  { href: "/settings", label: "Settings", icon: Settings, match: (p: string) => p.startsWith("/settings") },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)

  // The nav sheet must not stay open across a navigation on a phone.
  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* M3: the PWA says plainly when it is showing a cached archive. */}
      <OfflineBanner />

      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4 sm:h-16 sm:px-6 lg:px-8">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-11 w-11 md:hidden"
                aria-label="Open navigation"
              >
                <Menu className="h-5 w-5" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-0">
              <SheetHeader className="border-b border-border px-4 py-4 text-left">
                <SheetTitle>NegArchive</SheetTitle>
              </SheetHeader>
              <nav className="flex flex-col gap-1 p-3">
                {NAV.map((item) => {
                  const Icon = item.icon
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cn(
                        "flex min-h-12 items-center gap-3 rounded-md px-3 text-base font-medium transition-colors",
                        item.match(pathname)
                          ? "bg-secondary text-secondary-foreground"
                          : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                      )}
                    >
                      <Icon className="h-5 w-5" />
                      {item.label}
                    </Link>
                  )
                })}
              </nav>
            </SheetContent>
          </Sheet>

          <Link href="/" className="text-base font-semibold tracking-tight sm:text-lg">
            NegArchive
          </Link>

          <nav className="ml-6 hidden gap-1 md:flex">
            {NAV.map((item) => {
              const Icon = item.icon
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    item.match(pathname)
                      ? "bg-secondary text-secondary-foreground"
                      : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              )
            })}
          </nav>

          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">{children}</main>

      {/* M3: the address to type on a phone, and the QR that saves the typing. */}
      <LanFooter />
      {/* M3: renders nothing unless NEGARCHIVE_PASSWORD is set on the backend. */}
      <LoginGate />
    </div>
  )
}
