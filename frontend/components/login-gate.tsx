"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Lock } from "lucide-react"

import { errorMessage, getSystemInfo, login, readTokenCookie } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"

/**
 * The sign-in sheet for the optional shared password (roadmap M3, R#26).
 *
 * Renders nothing at all unless the backend says `auth_required`, which is off by
 * default: a single-user archive on a home network should not have a login
 * screen. When it is on, this asks once per browser and stores the token in a
 * cookie, which the page requests carry so server-rendered pages work too.
 *
 * `/api/system/info` stays open precisely so this component can ask.
 */
export function LoginGate() {
  const router = useRouter()
  const [required, setRequired] = useState(false)
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    getSystemInfo()
      .then((info) => {
        if (cancelled) return
        setRequired(info.auth_required && !readTokenCookie())
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(password)
      setRequired(false)
      setPassword("")
      // The server rendered this page without a token; re-render it with one.
      router.refresh()
    } catch (caught) {
      setError(errorMessage(caught, "Could not sign in."))
    } finally {
      setBusy(false)
    }
  }

  if (!required) return null

  return (
    <Sheet open onOpenChange={() => undefined}>
      <SheetContent side="bottom" className="mx-auto max-w-md" data-testid="login-sheet">
        <SheetHeader className="text-left">
          <SheetTitle className="flex items-center gap-2">
            <Lock className="h-4 w-4" />
            This archive is locked
          </SheetTitle>
          <SheetDescription>
            One shared password, set on the server. It is remembered in this browser until you clear
            its cookies.
          </SheetDescription>
        </SheetHeader>

        <form className="space-y-3 p-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="login-password">Password</Label>
            <Input
              id="login-password"
              type="password"
              value={password}
              autoFocus
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              className="h-11"
              data-testid="login-password"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "login-error" : undefined}
            />
            {error ? (
              <p id="login-error" role="alert" className="type-meta text-destructive">
                {error}
              </p>
            ) : null}
          </div>
          <Button type="submit" className="min-h-11 w-full" disabled={busy || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  )
}
