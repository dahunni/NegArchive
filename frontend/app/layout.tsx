import type React from "react"
import type { Metadata } from "next"

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
    apple: "/apple-icon.png",
  },
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
