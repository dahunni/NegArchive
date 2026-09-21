"use client"

import { useEffect, useState } from "react"
import { HardDrive, Loader2, Plug, Unplug } from "lucide-react"

import {
  type SmbStatus,
  errorMessage,
  forgetSmbPassword,
  getSmbStatus,
  mountSmb,
  saveSmbConfig,
  testSmb,
  unmountSmb,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { CopyValue } from "@/components/copy-value"
import { useToast } from "@/hooks/use-toast"

/**
 * The network share, and the live mode built on it (roadmap M6).
 *
 * This is the card that makes the NegPy integration work across two machines. The
 * explanation in it is deliberately five steps and no theory: the reasoning lives
 * in docs/NEGPY_LIVE.md, and somebody standing at a NAS wants the steps.
 *
 * The macOS paths are *computed from the saved share*, not hard-coded, so the
 * commands can be pasted as they are — `/Volumes/<share>/<folder>/rolls` is what
 * Finder will actually have mounted after step 1.
 */

/** Free space, in the unit that makes it readable. A 64 MB test share reading
 *  "0 GB free" is the kind of small wrongness that makes people distrust a page. */
function formatBytes(bytes: number): string {
  if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(bytes >= 1e10 ? 0 : 1)} GB`
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`
  return `${Math.round(bytes / 1e3)} kB`
}

/** A one-line command with a copy button. The steps are useless if they are retyped. */
export function CopyLine({ value, label }: { value: string; label: string }) {
  return <CopyValue value={value} label={label} variant="command" />
}

export function ShareSettings({ onChanged }: { onChanged?: () => void }) {
  const { toast } = useToast()
  const [status, setStatus] = useState<SmbStatus | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [host, setHost] = useState("")
  const [share, setShare] = useState("")
  const [subpath, setSubpath] = useState("")
  const [username, setUsername] = useState("")
  // Empty means "keep the stored one"; the placeholder says so.
  const [password, setPassword] = useState("")
  const [version, setVersion] = useState("3.0")
  const [readonly, setReadonly] = useState(false)

  /**
   * `intoForm` is the whole point of the split: testing, mounting or forgetting a
   * password must not overwrite what is half-typed in the fields. Only a save —
   * and the first load — may put the stored config back into the inputs.
   */
  const reload = async (intoForm: boolean) => {
    const nextStatus = await getSmbStatus().catch(() => null)
    setStatus(nextStatus)
    if (nextStatus && intoForm) {
      setHost(nextStatus.config.host)
      setShare(nextStatus.config.share)
      setSubpath(nextStatus.config.subpath)
      setUsername(nextStatus.config.username)
      setVersion(nextStatus.config.version)
      setReadonly(nextStatus.config.readonly)
    }
  }

  useEffect(() => {
    void reload(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const run = async (key: string, work: () => Promise<string>, intoForm = false) => {
    setBusy(key)
    setError(null)
    try {
      const message = await work()
      await reload(intoForm)
      onChanged?.()
      if (message) toast({ title: message })
    } catch (caught) {
      setError(errorMessage(caught, "That did not work."))
    } finally {
      setBusy(null)
    }
  }

  const save = () =>
    run("save", async () => {
      await saveSmbConfig({
        host: host.trim(),
        share: share.trim(),
        subpath: subpath.trim(),
        username: username.trim(),
        // Only send a password that was actually typed, so saving a changed folder
        // does not wipe the stored one.
        ...(password ? { password } : {}),
        version,
        readonly,
        enabled: true,
      })
      setPassword("")
      return "Share saved"
    }, true)

  const test = () =>
    run("test", async () => {
      const result = await testSmb({ host: host.trim(), share: share.trim() })
      if (!result.ok) throw new Error(result.error ?? "The NAS did not answer.")
      return `${host.trim()} answered on port 445`
    })

  const mount = () =>
    run("mount", async () => {
      await saveSmbConfig({
        host: host.trim(),
        share: share.trim(),
        subpath: subpath.trim(),
        username: username.trim(),
        ...(password ? { password } : {}),
        version,
        readonly,
        enabled: true,
      })
      setPassword("")
      await mountSmb()
      return "Share mounted"
    })

  const unmount = () => run("unmount", async () => { await unmountSmb(); return "Share unmounted" })

  const forget = () => run("forget", async () => { await forgetSmbPassword(); return "Password forgotten" })

  const blocked = status?.unavailable_reason ?? null
  const mounted = status?.mounted ?? false
  const canMount = host.trim().length > 0 && share.trim().length > 0 && !blocked

  return (
    <section className="space-y-3">
      <div>
        <h3 className="type-section text-base">Mount a NAS into the archive instead</h3>
        <p className="mt-1 type-body text-muted-foreground">
          Only if your scans must stay on a NAS: the archive mounts it here, and folders on it can be
          linked. It needs the two capability lines in <code className="type-numeric">docker-compose.yml</code>,
          which are off by default since the archive serves a share of its own.
        </p>
      </div>

      {blocked ? (
        <div
          role="alert"
          className="rounded-lg border border-dashed border-destructive/50 bg-destructive/5 p-4 type-body"
          data-testid="smb-unavailable"
        >
          {blocked}
        </div>
      ) : null}

      <div className="space-y-4 rounded-lg border border-border bg-card p-4" data-testid="smb-settings">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="smb-host">NAS address</Label>
            <Input
              id="smb-host"
              value={host}
              onChange={(event) => setHost(event.target.value)}
              placeholder="nas.local or 192.168.1.10"
              className="h-11 type-numeric"
              data-testid="smb-host"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smb-share">Share</Label>
            <Input
              id="smb-share"
              value={share}
              onChange={(event) => setShare(event.target.value)}
              placeholder="photo"
              className="h-11 type-numeric"
              data-testid="smb-share"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smb-subpath">Folder in the share (optional)</Label>
            <Input
              id="smb-subpath"
              value={subpath}
              onChange={(event) => setSubpath(event.target.value)}
              placeholder="film"
              className="h-11 type-numeric"
              data-testid="smb-subpath"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smb-version">SMB version</Label>
            <Select value={version} onValueChange={setVersion}>
              <SelectTrigger id="smb-version" className="h-11 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(status?.versions ?? ["3.1.1", "3.0", "2.1", "default"]).map((item) => (
                  <SelectItem key={item} value={item}>
                    {item === "default" ? "Negotiate automatically" : item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smb-user">User</Label>
            <Input
              id="smb-user"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="leave empty for a guest share"
              className="h-11"
              autoComplete="off"
              data-testid="smb-user"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smb-password">Password</Label>
            <Input
              id="smb-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={status?.has_credentials ? "stored — leave empty to keep it" : "NAS password"}
              className="h-11"
              autoComplete="new-password"
              data-testid="smb-password"
            />
          </div>
        </div>

        <label className="flex items-start gap-2">
          <Checkbox
            className="mt-1"
            checked={readonly}
            onCheckedChange={(value) => setReadonly(value === true)}
            aria-label="Mount read-only"
          />
          <span className="type-body">
            Mount read-only
            <span className="block type-meta">
              Safer, but NegPy’s gear and presets cannot be written to the share, so live mode needs
              this off.
            </span>
          </span>
        </label>

        {error ? (
          <p role="alert" className="type-meta text-destructive" data-testid="smb-error">
            {error}
          </p>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="min-h-11" onClick={test} disabled={!host.trim() || busy === "test"}>
            {busy === "test" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plug className="mr-2 h-4 w-4" />}
            {busy === "test" ? "Testing…" : "Test connection"}
          </Button>
          {mounted ? (
            <Button variant="outline" className="min-h-11" onClick={unmount} disabled={busy === "unmount"} data-testid="smb-unmount">
              <Unplug className="mr-2 h-4 w-4" />
              {busy === "unmount" ? "Unmounting…" : "Unmount"}
            </Button>
          ) : (
            <Button className="min-h-11" onClick={mount} disabled={!canMount || busy === "mount"} data-testid="smb-mount">
              {busy === "mount" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <HardDrive className="mr-2 h-4 w-4" />}
              {busy === "mount" ? "Mounting…" : "Save and mount"}
            </Button>
          )}
          <Button variant="outline" className="min-h-11" onClick={save} disabled={!host.trim() || busy === "save"}>
            {busy === "save" ? "Saving…" : "Save"}
          </Button>
          {status?.has_credentials ? (
            <Button variant="ghost" className="min-h-11" onClick={forget} disabled={busy === "forget"}>
              Forget password
            </Button>
          ) : null}
        </div>

        <p className="type-meta" data-testid="smb-readout">
          {mounted
            ? `Mounted: ${status?.config.display} at ${status?.mountpoint}${
                status?.space ? ` · ${formatBytes(status.space.free)} free` : ""
              }`
            : status?.config.host
              ? `Not mounted. ${status.config.display} is saved and will be mounted when the archive starts.`
              : "No share yet."}
        </p>
        <p className="type-meta">
          The password is kept in a file only the server can read, not in the database and not in a
          backup export.
        </p>
      </div>

    </section>
  )
}
