import type React from "react"
import type { Metadata, Viewport } from "next"

import "./globals.css"
import { Toaster } from "@/components/ui/toaster"
import { AppShell } from "@/components/app-shell"
import { ThemeProvider } from "@/components/theme-provider"

// No web fonts and no analytics on purpose: this is an offline-first archive that
// must build and run without internet (R#27, R#28). The system font stack lives in
// globals.css.

export const metadata: Metadata = {
  title: "NegArchive",
  description: "A self-hosted archive for film rolls, their scans and where the negatives live.",
  // M3: installable on a phone or tablet, for the lookup you do at the shelf.
  manifest: "/manifest.webmanifest",
  applicationName: "NegArchive",
  appleWebApp: {
    capable: true,
    title: "NegArchive",
    statusBarStyle: "black-translucent",
  },
  icons: {
    icon: [
      {
        url: "/icon-light-32x32.png",
        media: "(prefers-color-scheme: light)",
      },
      {
        url: "/icon-dark-32x32.png",
        media: "(prefers-color-scheme: dark)",
      },
      {
        url: "/icon.svg",
        type: "image/svg+xml",
      },
    ],
    apple: "/icons/apple-touch-icon.png",
  },
}

/**
 * The colour the phone paints around the installed app. Both schemes are given,
 * because the archive follows the system theme and a white bar above a dark page
 * is the tell-tale sign of a web page pretending to be an app.
 */
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0b" },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <AppShell>{children}</AppShell>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  )
}
