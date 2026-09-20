"use client"

import { useEffect, useState } from "react"
import { Check, Copy, HardDrive, Loader2, Plug, Sparkles, Unplug } from "lucide-react"

import {
  type LiveState,
  type SmbStatus,
  applyLiveMode,
  errorMessage,
  forgetSmbPassword,
  getLiveState,
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
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-stretch gap-2">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-md border border-border bg-muted/50 px-2 py-1.5 type-numeric text-xs">
        {value}
      </code>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="shrink-0"
        aria-label={`Copy ${label}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          } catch {
            // A browser that refuses the clipboard is not an error worth a toast:
            // the text is right there to select.
          }
        }}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </Button>
    </div>
  )
}

export function ShareSettings({ onChanged }: { onChanged?: () => void }) {
  const { toast } = useToast()
  const [status, setStatus] = useState<SmbStatus | null>(null)
  const [live, setLive] = useState<LiveState | null>(null)
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

  const reload = async () => {
    const [nextStatus, nextLive] = await Promise.all([
      getSmbStatus().catch(() => null),
      getLiveState().catch(() => null),
    ])
    setStatus(nextStatus)
    setLive(nextLive)
    if (nextStatus) {
      setHost(nextStatus.config.host)
      setShare(nextStatus.config.share)
      setSubpath(nextStatus.config.subpath)
      setUsername(nextStatus.config.username)
      setVersion(nextStatus.config.version)
      setReadonly(nextStatus.config.readonly)
    }
  }

  useEffect(() => {
    void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const run = async (key: string, work: () => Promise<string>) => {
    setBusy(key)
    setError(null)
    try {
      const message = await work()
      await reload()
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
    })

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

  const setUpLive = () =>
    run("live", async () => {
      const report = await applyLiveMode()
      return report.summary
    })

  const forget = () => run("forget", async () => { await forgetSmbPassword(); return "Password forgotten" })

  const blocked = status?.unavailable_reason ?? null
  const mounted = status?.mounted ?? false
  const canMount = host.trim().length > 0 && share.trim().length > 0 && !blocked

  // Where the same share appears on the Mac running NegPy. Finder mounts a share
  // at /Volumes/<share>, and the folder inside it comes along.
  const macBase = share.trim() ? `/Volumes/${share.trim()}${subpath.trim() ? `/${subpath.trim()}` : ""}` : "/Volumes/<share>"
  const smbUrl = host.trim() && share.trim() ? `smb://${host.trim()}/${share.trim()}` : "smb://<nas>/<share>"

  return (
    <section className="space-y-3">
      <div>
        <h2 className="type-section">Network share</h2>
        <p className="mt-1 type-body text-muted-foreground">
          NegArchive runs on this server; NegPy runs on your Mac. For NegPy to edit a scan and for
          the archive to notice, both have to be looking at <em>the same folder</em> — so the
          archive mounts your NAS here, and you mount it on the Mac. Then you just work in NegPy and
          the archive keeps up on its own.
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

      {/* ------------------------------------------------------------- live mode */}
      <div className="space-y-4 rounded-lg border border-border bg-card p-4" data-testid="live-mode">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="type-section text-base">Work live in NegPy</h3>
            <p className="mt-1 type-meta">
              {live?.ready
                ? "Set up. Edit a scan in NegPy and this archive picks the edit up within 30 seconds."
                : "One button: makes the folders on the share, watches them, and points NegPy’s gear and presets at them."}
            </p>
          </div>
          <Button
            className="min-h-11"
            onClick={setUpLive}
            disabled={!mounted || busy === "live"}
            data-testid="live-setup"
          >
            {busy === "live" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
            {busy === "live" ? "Setting up…" : live?.ready ? "Check again" : "Set up live mode"}
          </Button>
        </div>

        {!mounted ? (
          <p className="type-meta text-muted-foreground">Mount the share first.</p>
        ) : (
          <ol className="space-y-3 border-t border-border pt-4 type-body">
            <li className="space-y-1.5">
              <span className="font-medium">1 · Mount the same share on the Mac</span>
              <span className="block type-meta">In Finder press ⌘K and connect to:</span>
              <CopyLine value={smbUrl} label="the share address" />
            </li>
            <li className="space-y-1.5">
              <span className="font-medium">2 · Point NegPy at the scans</span>
              <span className="block type-meta">
                Add this as a library root in NegPy. Everything you shoot lives here, and you edit it
                in place — the archive links these files, it never copies them.
              </span>
              <CopyLine value={`${macBase}/rolls`} label="the scans folder" />
            </li>
            <li className="space-y-1.5">
              <span className="font-medium">3 · Turn on sidecars in NegPy</span>
              <span className="block type-meta">
                NegPy → Settings → write <code className="type-numeric">.negpy</code> files next to the
                originals. This is the one setting the whole thing depends on: the sidecar is how an
                edit travels from your Mac to the archive.
              </span>
            </li>
            <li className="space-y-1.5">
              <span className="font-medium">4 · Share NegPy’s gear and presets</span>
              <span className="block type-meta">
                Paste both lines into Terminal once. Your cameras, lenses and films then appear in
                NegPy, and every roll you prepare here shows up as a preset.
              </span>
              <CopyLine
                value={`ln -sfn "${macBase}/negpy-user/gear" ~/.negpy/gear`}
                label="the gear link command"
              />
              <CopyLine
                value={`mkdir -p ~/.negpy/presets && ln -sfn "${macBase}/negpy-user/presets/metadata" ~/.negpy/presets/metadata`}
                label="the presets link command"
              />
              <span className="block type-meta">
                NegPy’s own <code className="type-numeric">edits.db</code> stays on the Mac on purpose —
                a database on a network share is how databases get corrupted.
              </span>
            </li>
            <li className="space-y-1.5">
              <span className="font-medium">5 · Send NegPy’s exports back</span>
              <span className="block type-meta">
                In NegPy’s export settings, set the output folder and the filename pattern below.
                Finished positives then file themselves onto the right roll.
              </span>
              <CopyLine value={`${macBase}/exports`} label="the exports folder" />
              <CopyLine value={live?.client.filename_pattern ?? "{{ roll }}_{{ frame|pad(3) }}_{{ film }}"} label="the filename pattern" />
            </li>
            <li className="space-y-1.5">
              <span className="font-medium">6 · Scan straight into the archive (camera scanning)</span>
              <span className="block type-meta">
                If you scan with a camera, point NegPy’s Live View &amp; Scan at the folder below and name each
                roll after the archive’s serial — every roll page shows the exact two lines to paste. The raws
                are filed onto that roll as they land; nothing is copied.
              </span>
              <CopyLine value={`${macBase}/rolls`} label="the scan output folder" />
            </li>
          </ol>
        )}

        {live && mounted ? (
          <p className="type-meta" data-testid="live-readout">
            {live.folders
              .map((folder) => `${folder.path.split("/").pop()}: ${folder.watched ? "watched" : "not watched"}`)
              .join(" · ")}
            {live.watch_enabled ? " · background checks on" : " · background checks OFF"}
          </p>
        ) : null}
      </div>
    </section>
  )
}
