"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Database, Download, FlaskConical, FolderPlus, HardDrive, RefreshCw, Trash2, Upload } from "lucide-react"

import {
  type LibraryRoot,
  type LibraryRoots,
  type NegpyStatus,
  type PreviewRender,
  type Settings,
  type SystemInfo,
  type WatchState,
  EXPORT_CSV_URL,
  EXPORT_URL,
  createLibraryRoot,
  deleteLibraryRoot,
  errorMessage,
  getLibraryRoots,
  getNegpyStatus,
  getSettings,
  getSystemInfo,
  importArchive,
  ingestNegpyMetadata,
  matchNegpyEdits,
  scanLibraryRoot,
  syncNegpyGear,
  updateLibraryRoot,
  updateSettings,
} from "@/lib/api"
import { formatDate } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { InboxCard } from "@/components/inbox-card"
import { ShareSettings } from "@/components/share-settings"
import { EmptyState } from "@/components/empty-state"
import { useToast } from "@/hooks/use-toast"

/**
 * Settings: the folders NegArchive links files from, the watch folder toggle,
 * and getting the whole archive out (roadmap M3).
 *
 * Everything here is deployment-adjacent, so each section says what it does to
 * your files. The one rule worth repeating in the UI as well as the code: a
 * linked folder is never written to, and removing it never deletes anything.
 */
export function SettingsWorkspace() {
  const router = useRouter()
  const { toast } = useToast()

  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [library, setLibrary] = useState<LibraryRoots | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [watch, setWatch] = useState<WatchState | null>(null)
  const [negpy, setNegpy] = useState<NegpyStatus | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [pendingRemove, setPendingRemove] = useState<LibraryRoot | null>(null)

  const [newPath, setNewPath] = useState("")
  const [newLabel, setNewLabel] = useState("")
  const [newWatch, setNewWatch] = useState(true)
  const [addError, setAddError] = useState<string | null>(null)

  const importInput = useRef<HTMLInputElement>(null)
  // Which button opened the file picker. A ref, not state: the click handler
  // fires before React would re-render, and the change handler needs it now.
  const importDryRun = useRef(false)

  const reload = async () => {
    const [nextInfo, nextLibrary, nextSettings, nextNegpy] = await Promise.all([
      getSystemInfo().catch(() => null),
      getLibraryRoots().catch(() => null),
      getSettings().catch(() => null),
      getNegpyStatus().catch(() => null),
    ])
    setInfo(nextInfo)
    setLibrary(nextLibrary)
    setNegpy(nextNegpy)
    if (nextSettings) {
      setSettings(nextSettings.settings)
      setWatch(nextSettings.watch)
    }
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const addRoot = async (event: React.FormEvent) => {
    event.preventDefault()
    setAddError(null)
    setBusy("add")
    try {
      await createLibraryRoot({ path: newPath.trim(), label: newLabel.trim() || undefined, watch: newWatch })
      setNewPath("")
      setNewLabel("")
      await reload()
      toast({ title: "Folder registered", description: "Scan it to bring its rolls in." })
    } catch (caught) {
      setAddError(errorMessage(caught, "Could not register that folder."))
    } finally {
      setBusy(null)
    }
  }

  const scan = async (root: LibraryRoot) => {
    setBusy(`scan-${root.id}`)
    try {
      const result = await scanLibraryRoot(root.id)
      await reload()
      router.refresh()
      toast({ title: "Scan finished", description: result.summary })
    } catch (caught) {
      toast({ title: "Scan failed", description: errorMessage(caught), variant: "destructive" })
    } finally {
      setBusy(null)
    }
  }

  const toggleWatch = async (root: LibraryRoot, value: boolean) => {
    try {
      await updateLibraryRoot(root.id, { watch: value })
      await reload()
    } catch (caught) {
      toast({ title: "Could not save", description: errorMessage(caught), variant: "destructive" })
    }
  }

  const removeRoot = async () => {
    if (!pendingRemove) return
    try {
      await deleteLibraryRoot(pendingRemove.id)
      setPendingRemove(null)
      await reload()
      toast({
        title: "Folder removed",
        description: "The frames and the files on disk were left exactly as they were.",
      })
    } catch (caught) {
      toast({ title: "Could not remove", description: errorMessage(caught), variant: "destructive" })
    }
  }

  const saveSetting = async (patch: Partial<Settings>) => {
    try {
      const next = await updateSettings(patch)
      setSettings(next.settings)
      setNegpy(await getNegpyStatus().catch(() => negpy))
    } catch (caught) {
      toast({ title: "Could not save", description: errorMessage(caught), variant: "destructive" })
    }
  }

  const syncGear = async () => {
    setBusy("gear")
    try {
      const result = await syncNegpyGear()
      await reload()
      toast({
        title: "Gear written for NegPy",
        description: `${result.total} entries in ${result.directory}`,
      })
    } catch (caught) {
      toast({ title: "Could not write the gear files", description: errorMessage(caught), variant: "destructive" })
    } finally {
      setBusy(null)
    }
  }

  const readBacklog = async () => {
    setBusy("ingest")
    try {
      const report = await ingestNegpyMetadata()
      await reload()
      router.refresh()
      toast({
        title: "Files read",
        description: `${report.examined} looked at, ${report.changed} filled in, ${report.sidecars} NegPy sidecars`,
      })
    } catch (caught) {
      toast({ title: "Could not read the files", description: errorMessage(caught), variant: "destructive" })
    } finally {
      setBusy(null)
    }
  }

  const matchEdits = async () => {
    setBusy("edits")
    try {
      const report = await matchNegpyEdits()
      await reload()
      router.refresh()
      toast({
        title: "NegPy edits matched",
        description: `${report.matched} of ${report.examined} frames found in ${report.database}`,
      })
    } catch (caught) {
      toast({ title: "Could not read edits.db", description: errorMessage(caught), variant: "destructive" })
    } finally {
      setBusy(null)
    }
  }

  const setWatchEnabled = async (value: boolean) => {
    try {
      const next = await updateSettings({ watch_enabled: value })
      setSettings(next.settings)
      setWatch(next.watch)
    } catch (caught) {
      toast({ title: "Could not save", description: errorMessage(caught), variant: "destructive" })
    }
  }

  const runImport = async (file: File, dryRun: boolean) => {
    setBusy("import")
    try {
      const report = await importArchive(file, dryRun)
      const summary = Object.entries(report)
        .filter(([key, value]) => typeof value === "number" && value > 0 && key !== "format")
        .map(([key, value]) => `${value} ${key.replace(/_/g, " ")}`)
        .join(", ")
      toast({
        title: dryRun ? "Dry run" : "Import finished",
        description: summary || "Nothing to do: this archive already has all of it.",
      })
      if (!dryRun) router.refresh()
    } catch (caught) {
      toast({ title: "Import failed", description: errorMessage(caught), variant: "destructive" })
    } finally {
      setBusy(null)
      if (importInput.current) importInput.current.value = ""
    }
  }

  return (
    <div className="space-y-8" data-testid="settings">
      <div>
        <h1 className="type-page">Settings</h1>
        <p className="mt-1 type-body text-muted-foreground">
          Where the archive keeps its files, which folders it links, and how to get everything out again.
        </p>
      </div>

      {/* ------------------------------------------------------------ this machine */}
      <section className="space-y-3">
        <h2 className="type-section">This machine</h2>
        <dl className="grid gap-x-6 gap-y-2 rounded-lg border border-border bg-card p-4 sm:grid-cols-2">
          <Fact label="Data directory" value={info?.data_dir ?? "…"} mono />
          <Fact label="On this network" value={info?.ui_url ?? "no LAN address found"} mono />
          <Fact label="Rolls" value={info ? String(info.counts.rolls) : "…"} />
          <Fact label="Frames" value={info ? String(info.counts.frames) : "…"} />
          <Fact label="Password" value={info?.auth_required ? "set" : "not set (open on this network)"} />
        </dl>
      </section>

      {/* ---------------------------------------------- M6.2: the archive's own share */}
      {/* First, because it is the whole NegPy setup for most people: export into the
          folder the stack serves, and the archive does the rest. */}
      <InboxCard onChanged={reload} />

      {/* ------------------------------------------------- the share, and live mode */}
      {/* M6. Above the linked folders on purpose: on a two-machine setup the
          folders below usually live on this share, so mounting it is step one. */}
      <ShareSettings onChanged={reload} />

      {/* ------------------------------------------------------- linked folders */}
      <section className="space-y-3">
        <div>
          <h2 className="type-section">Linked folders</h2>
          <p className="mt-1 type-body text-muted-foreground">
            Import scans <em>by reference</em>: each subfolder becomes a roll and each file a frame,
            and the files stay exactly where they are. NegArchive never writes to, moves or deletes
            anything in here — not even when you delete the frame.
          </p>
        </div>

        {library && !library.enabled ? (
          <div className="rounded-lg border border-dashed border-border p-4 type-body text-muted-foreground">
            Import by reference is switched off. Set <code className="type-numeric">LIBRARY_ROOTS_ALLOW</code>{" "}
            on the backend to the folder(s) NegArchive may read — in Docker that is{" "}
            <code className="type-numeric">/library</code> — and restart the stack.
          </div>
        ) : (
          <form className="grid gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-[2fr_1fr_auto]" onSubmit={addRoot}>
            <div className="space-y-1.5">
              <Label htmlFor="root-path">Folder</Label>
              <Input
                id="root-path"
                value={newPath}
                onChange={(event) => setNewPath(event.target.value)}
                placeholder={library?.allowed_bases[0] ?? "/library"}
                className="h-11 type-numeric"
                data-testid="root-path"
                aria-invalid={addError ? true : undefined}
                aria-describedby={addError ? "root-error" : undefined}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="root-label">Label</Label>
              <Input
                id="root-label"
                value={newLabel}
                onChange={(event) => setNewLabel(event.target.value)}
                placeholder="Scanner output"
                className="h-11"
              />
            </div>
            <div className="flex items-end">
              <Button type="submit" className="min-h-11 w-full" disabled={!newPath.trim() || busy === "add"}>
                <FolderPlus className="mr-2 h-4 w-4" />
                Add
              </Button>
            </div>
            <label className="flex items-center gap-2 sm:col-span-3">
              <Checkbox checked={newWatch} onCheckedChange={(value) => setNewWatch(value === true)} />
              <span className="type-body">Watch this folder for new rolls and frames</span>
            </label>
            {addError ? (
              <p id="root-error" role="alert" className="type-meta text-destructive sm:col-span-3">
                {addError}
              </p>
            ) : null}
          </form>
        )}

        {library && library.roots.length > 0 ? (
          <ul className="space-y-2" data-testid="library-roots">
            {library.roots.map((root) => (
              <li key={root.id} className="rounded-lg border border-border bg-card p-3 sm:p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="type-numeric truncate text-sm">{root.path}</p>
                    <p className="type-meta">
                      {root.label ? `${root.label} · ` : ""}
                      {root.frame_count ?? 0} linked frames ·{" "}
                      {root.last_scan_at
                        ? `last scan ${formatDate(root.last_scan_at)} — ${root.last_scan_summary}`
                        : "never scanned"}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <label className="flex items-center gap-2">
                      <Checkbox
                        checked={root.watch}
                        onCheckedChange={(value) => toggleWatch(root, value === true)}
                        aria-label={`Watch ${root.path}`}
                      />
                      <span className="type-meta">Watch</span>
                    </label>
                    <Button
                      variant="outline"
                      size="sm"
                      className="min-h-10"
                      onClick={() => scan(root)}
                      disabled={busy === `scan-${root.id}`}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      {busy === `scan-${root.id}` ? "Scanning…" : "Scan"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-10 w-10"
                      aria-label={`Remove ${root.path}`}
                      onClick={() => setPendingRemove(root)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : library?.enabled ? (
          <EmptyState
            icon={HardDrive}
            title="No folders linked yet"
            description="Point NegArchive at the folder your scanner writes into, then scan it."
          />
        ) : null}
      </section>

      {/* ---------------------------------------------------------- watch folder */}
      <section className="space-y-3">
        <h2 className="type-section">Watch folder</h2>
        <div className="space-y-2 rounded-lg border border-border bg-card p-4">
          <label className="flex items-center gap-2">
            <Checkbox
              checked={settings?.watch_enabled ?? false}
              onCheckedChange={(value) => setWatchEnabled(value === true)}
              aria-label="Watch registered folders"
              data-testid="watch-toggle"
            />
            <span className="type-body">Check the watched folders in the background</span>
          </label>
          <p className="type-meta" data-testid="watch-readout">
            {watch?.interval_seconds
              ? `Every ${watch.interval_seconds} seconds · ${watch.roots_watched ?? 0} of ${watch.roots_total ?? 0} folders watched`
              : "The poller is switched off on the server (WATCH_INTERVAL_SECONDS)."}
            {watch?.last_scan_at ? ` · last scan ${formatDate(watch.last_scan_at)}` : " · never scanned"}
          </p>
        </div>
      </section>

      {/* ---------------------------------------------------------------- NegPy */}
      <section className="space-y-3">
        <div>
          <h2 className="type-section">NegPy</h2>
          <p className="mt-1 type-body text-muted-foreground">
            NegArchive and NegPy exchange files, never code: a scan you export from NegPy arrives here
            already knowing its roll, frame, date and gear, and a roll you prepare here arrives in NegPy
            with the same. Nothing below needs NegPy to be running, or even installed on this machine.
          </p>
        </div>

        <div className="space-y-3 rounded-lg border border-border bg-card p-4" data-testid="negpy-settings">
          <label className="flex items-start gap-2">
            <Checkbox
              className="mt-1"
              checked={settings?.negpy_ingest ?? true}
              onCheckedChange={(value) => saveSetting({ negpy_ingest: value === true })}
              aria-label="Read metadata from uploaded files"
              data-testid="negpy-ingest-toggle"
            />
            <span className="type-body">
              Read EXIF and NegPy metadata from every file
              <span className="block type-meta">
                Fills the frame number, the capture date and the roll’s gear when they are empty. It never
                overwrites something you typed.
              </span>
            </span>
          </label>

          <label className="flex items-start gap-2">
            <Checkbox
              className="mt-1"
              checked={settings?.negpy_create_gear ?? false}
              onCheckedChange={(value) => saveSetting({ negpy_create_gear: value === true })}
              aria-label="Add gear the files name"
              data-testid="negpy-create-gear-toggle"
            />
            <span className="type-body">
              Add cameras, lenses and film stocks the files name
              <span className="block type-meta">
                Off by default: EXIF spellings (“NIKON CORPORATION NIKON F5”) make near-duplicates of
                entries your catalog already has.
              </span>
            </span>
          </label>

          {/* M5: how previews are rendered. The scan on disk is never changed —
              a rendering lives in the disposable preview cache. */}
          <div className="space-y-2 border-t border-border pt-3">
            <Label htmlFor="preview-render">Previews</Label>
            <select
              id="preview-render"
              data-testid="preview-render"
              className="h-11 w-full rounded-md border border-input bg-background px-3 type-body"
              value={settings?.preview_render ?? "auto"}
              onChange={(event) => saveSetting({ preview_render: event.target.value as PreviewRender })}
            >
              <option value="auto">Print what is known to be a negative (recommended)</option>
              <option value="raw">Always show the scan as it was stored</option>
              <option value="positive">Always print as a positive</option>
            </select>
            <p className="type-meta">
              A positive preview is an <em>approximation</em>: it applies the tone controls and the crop from a
              NegPy edit — grade, exposure, toe and shoulder, the zone densities — and not dodging, burning,
              toning, retouching or paper profiles. The frame viewer says how much of each recipe it rendered,
              and has a toggle back to the scan. Nothing on disk changes either way.
            </p>
          </div>

          <dl className="grid gap-x-6 gap-y-2 border-t border-border pt-3 sm:grid-cols-2">
            <Fact label="Gear files" value={negpy?.paths.gear_dir ?? "—"} mono />
            <Fact label="Roll folders" value={negpy?.paths.handoff_dir ?? "—"} mono />
            <Fact label="Export filename pattern" value={negpy?.filename_pattern ?? "—"} mono />
            <Fact
              label="Read so far"
              value={
                negpy
                  ? `${negpy.frames_with_metadata} frames · ${negpy.frames_edited_in_negpy} edited in NegPy`
                  : "…"
              }
            />
          </dl>
          {negpy?.paths.error ? (
            <p role="alert" className="type-meta text-destructive">
              {negpy.paths.error}
            </p>
          ) : null}
          <p className="type-meta">
            Set <code className="type-numeric">NEGPY_USER_DIR</code> to write straight into NegPy’s own user
            directory; without it these live inside the archive’s data directory, ready to copy across.
            {negpy?.gear_synced_at ? ` Gear last written ${formatDate(negpy.gear_synced_at)}.` : ""}
          </p>

          {/* NegPy's own edits database, if this machine has one. Read-only: the
              backend opens it immutable, so nothing here can cost you an edit. */}
          <p className="type-meta" data-testid="negpy-edits-readout">
            {negpy?.edits_db?.readable
              ? `NegPy's edits.db: ${negpy.edits_db.rows ?? "?"} edits at ${negpy.edits_db.path}. Matched by content hash, read-only.`
              : negpy?.edits_db?.exists
                ? `An edits.db is at ${negpy.edits_db.path}, but its tables are not the ones NegArchive knows. It is left alone.`
                : "No NegPy edits.db on this machine. Sidecars beside the scans are the other way to see edits."}
          </p>

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="min-h-11" onClick={syncGear} disabled={busy === "gear"} data-testid="negpy-sync-gear">
              <FlaskConical className="mr-2 h-4 w-4" />
              {busy === "gear" ? "Writing…" : "Write gear for NegPy"}
            </Button>
            <Button variant="outline" className="min-h-11" onClick={readBacklog} disabled={busy === "ingest"} data-testid="negpy-ingest-backlog">
              <RefreshCw className="mr-2 h-4 w-4" />
              {busy === "ingest" ? "Reading…" : "Read metadata of older frames"}
            </Button>
            {negpy?.edits_db?.readable ? (
              <Button
                variant="outline"
                className="min-h-11"
                onClick={matchEdits}
                disabled={busy === "edits"}
                data-testid="negpy-match-edits"
              >
                <Database className="mr-2 h-4 w-4" />
                {busy === "edits" ? "Matching…" : "Match NegPy's edits"}
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------- backup & export */}
      <section className="space-y-3">
        <div>
          <h2 className="type-section">Backup and export</h2>
          <p className="mt-1 type-body text-muted-foreground">
            The export is a ZIP holding every table as plain JSON plus the files NegArchive manages —
            readable without NegArchive, which is the point. Files you linked are listed but not
            copied; they live in your own folder. For a restorable snapshot of the database itself,
            run <code className="type-numeric">make backup</code> on the server.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 rounded-lg border border-border bg-card p-4">
          <Button asChild variant="outline" className="min-h-11">
            <a href={EXPORT_URL} download data-testid="export-zip">
              <Download className="mr-2 h-4 w-4" />
              Export everything (.zip)
            </a>
          </Button>
          <Button asChild variant="outline" className="min-h-11">
            <a href={EXPORT_CSV_URL} download data-testid="export-csv">
              <Download className="mr-2 h-4 w-4" />
              Rolls as CSV
            </a>
          </Button>
          <input
            ref={importInput}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            data-testid="import-input"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) runImport(file, importDryRun.current)
            }}
          />
          <Button
            variant="outline"
            className="min-h-11"
            disabled={busy === "import"}
            onClick={() => {
              importDryRun.current = true
              importInput.current?.click()
            }}
          >
            <Upload className="mr-2 h-4 w-4" />
            Try an import (dry run)
          </Button>
          <Button
            variant="outline"
            className="min-h-11"
            disabled={busy === "import"}
            onClick={() => {
              importDryRun.current = false
              importInput.current?.click()
            }}
          >
            <Upload className="mr-2 h-4 w-4" />
            Import an export
          </Button>
        </div>
      </section>

      <DeleteConfirmationDialog
        open={pendingRemove !== null}
        onOpenChange={(open) => !open && setPendingRemove(null)}
        onConfirm={removeRoot}
        title="Stop tracking this folder?"
        description={`NegArchive forgets ${pendingRemove?.path}. The files stay on disk and the frames stay in the archive; only the automatic scanning stops.`}
      />
    </div>
  )
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="type-meta uppercase tracking-wide">{label}</dt>
      <dd className={mono ? "truncate type-numeric text-sm" : "truncate type-body"}>{value}</dd>
    </div>
  )
}
