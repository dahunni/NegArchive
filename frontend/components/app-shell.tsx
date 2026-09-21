"use client"

import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { Film, Images, MapPin, Menu, Printer, ScanLine, Search, Settings, Wrench } from "lucide-react"

import { errorMessage, resolveScan } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { LanFooter } from "@/components/lan-footer"
import { LoginGate } from "@/components/login-gate"
import { OfflineBanner } from "@/components/offline-banner"
import { SearchPalette } from "@/components/search-palette"
import { ThemeToggle } from "@/components/theme-toggle"
import { WhatsNewDialog } from "@/components/whats-new-dialog"
import { useAppVersion, useVersionPolling } from "@/hooks/use-app-version"
import { useScannerWedge } from "@/hooks/use-scanner-wedge"
import { useToast } from "@/hooks/use-toast"

/**
 * Rolls are the work, frames are everything loose, gear is the catalog, locations
 * are the shelves (M4), scan is the scanner console (M4), print is the queue of
 * labels still to cut out (M4), settings is where the archive itself lives.
 */
const NAV = [
  { href: "/", label: "Rolls", icon: Film, match: (p: string) => p === "/" || p.startsWith("/films") },
  { href: "/images", label: "Frames", icon: Images, match: (p: string) => p.startsWith("/images") },
  { href: "/locations", label: "Locations", icon: MapPin, match: (p: string) => p.startsWith("/locations") },
  { href: "/scan", label: "Scan", icon: ScanLine, match: (p: string) => p.startsWith("/scan") },
  { href: "/print/queue", label: "Print", icon: Printer, match: (p: string) => p.startsWith("/print") },
  { href: "/gear", label: "Gear", icon: Wrench, match: (p: string) => p.startsWith("/gear") },
  { href: "/settings", label: "Settings", icon: Settings, match: (p: string) => p.startsWith("/settings") },
]

/** Print pages render bare: no header, no footer, nothing but the sheet. */
function isPrintRoute(pathname: string): boolean {
  return pathname.startsWith("/print/") && pathname !== "/print/queue"
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { toast } = useToast()
  const [mobileOpen, setMobileOpen] = useState(false)
  // M7: the search palette, and the "what's new" dialog (opened by an update, or on request).
  const [searchOpen, setSearchOpen] = useState(false)
  const [whatsNew, setWhatsNew] = useState<"update" | "all" | null>(null)
  useVersionPolling()
  const version = useAppVersion()

  // The nav sheet must not stay open across a navigation on a phone.
  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  // An update was noticed (the first load after `docker compose pull`, or a
  // tab left open through it): show what changed, once, until it is acknowledged.
  useEffect(() => {
    if (version.updated && whatsNew === null && !isPrintRoute(pathname)) setWhatsNew("update")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version.updated])

  // M4: a barcode scanner works from any page. The scanner console has its own
  // handling (multi-step sequences), so the shell stays out of its way there.
  useScannerWedge(
    async (code) => {
      try {
        const result = await resolveScan(code)
        if (result.kind === "command") {
          router.push(`/scan?command=${encodeURIComponent(result.command)}`)
          return
        }
        toast({ title: `Scanned ${code}`, description: result.kind === "roll" ? result.roll.title : result.location.path ?? "" })
        router.push(result.url)
      } catch (error) {
        toast({ title: `Unknown code: ${code}`, description: errorMessage(error), variant: "destructive" })
      }
    },
    { enabled: !pathname.startsWith("/scan") },
  )

  // `⌘K` / `Ctrl+K` opens the search palette from anywhere, even inside a text
  // field (M7). `/` keeps its M4 meaning on the roll list — focus the filter
  // bar's search box, the way a barcode scanner expects a field to type into —
  // and on every other page it opens the palette instead of leaving the page.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey) {
        event.preventDefault()
        setSearchOpen((open) => !open)
        return
      }
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      if (target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable)) return
      const search = document.querySelector<HTMLInputElement>('[data-testid="roll-search"]')
      event.preventDefault()
      if (search) {
        search.focus()
        search.select()
      } else {
        setSearchOpen(true)
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [])

  if (isPrintRoute(pathname)) {
    return <>{children}</>
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* M3: the PWA says plainly when it is showing a cached archive. */}
      <OfflineBanner />

      {/* Screen chrome: hidden on paper, so ⌘P on any page prints the page. */}
      <header
        data-print-hide
        className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80"
      >
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4 sm:h-16 sm:px-6 lg:px-8">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-11 w-11 lg:hidden"
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

          <nav className="ml-4 hidden gap-1 lg:flex">
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

          <div className="ml-auto flex items-center gap-1">
            {/* M7: search everything. A labelled button with the shortcut on a
                desktop, an icon on a phone. */}
            <Button
              variant="outline"
              className="hidden h-10 min-w-56 justify-start gap-2 text-muted-foreground lg:flex"
              onClick={() => setSearchOpen(true)}
              data-testid="search-open"
            >
              <Search className="h-4 w-4" />
              <span className="flex-1 text-left font-normal">Search…</span>
              <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px]">⌘K</kbd>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-11 w-11 lg:hidden"
              onClick={() => setSearchOpen(true)}
              aria-label="Search the archive"
              data-testid="search-open-mobile"
            >
              <Search className="h-5 w-5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-11 w-11 lg:hidden" asChild aria-label="Scan a code">
              <Link href="/scan">
                <ScanLine className="h-5 w-5" />
              </Link>
            </Button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">{children}</main>

      {/* M3: the address to type on a phone, and the QR that saves the typing.
          M7: and which NegArchive this is, with "what's new" a click away. */}
      <LanFooter onWhatsNew={() => setWhatsNew("all")} />
      {/* M3: renders nothing unless NEGARCHIVE_PASSWORD is set on the backend. */}
      <LoginGate />

      <SearchPalette open={searchOpen} onOpenChange={setSearchOpen} />
      <WhatsNewDialog open={whatsNew !== null} onOpenChange={(open) => !open && setWhatsNew(null)} mode={whatsNew ?? "all"} />
    </div>
  )
}
