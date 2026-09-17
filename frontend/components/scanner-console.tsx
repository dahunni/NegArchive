"use client"

import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useRef, useState } from "react"
import { Camera, CheckCircle2, Keyboard, Loader2, MapPin, ScanLine, X, XCircle } from "lucide-react"

import {
  type Film,
  type Location,
  type RollStatus,
  type ScanResolution,
  bulkMoveRolls,
  errorMessage,
  markPrinted,
  resolveScan,
  setRollStatus,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { StatusBadge } from "@/components/status-stepper"
import { useToast } from "@/hooks/use-toast"

type Mode = "lookup" | "move" | "status" | "printed"

interface LogEntry {
  id: number
  at: string
  input: string
  text: string
  tone: "ok" | "info" | "error"
}

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "lookup", label: "Look up", hint: "Scan a roll or a location to open it." },
  { value: "move", label: "Move", hint: "Scan one or more rolls, then the destination. Scan CMD-DONE or press Enter on an empty field to finish." },
  { value: "status", label: "Set status", hint: "Pick a status, then scan every roll that reached it." },
  { value: "printed", label: "Mark printed", hint: "Scan each roll whose label you have just stuck on." },
]

const STATUS_COMMANDS: Record<string, RollStatus> = {
  "STATUS-LOADED": "loaded",
  "STATUS-SHOT": "shot",
  "STATUS-ATLAB": "at_lab",
  "STATUS-BACK": "back",
  "STATUS-SCANNED": "scanned",
  "STATUS-SLEEVED": "sleeved",
}

/**
 * The scanner console (M4).
 *
 * One always-focused input. A USB or Bluetooth barcode scanner types a code and
 * Enter; the phone camera decodes a QR or a Code128; a person can type a serial.
 * Whatever arrives goes through `POST /api/scan/resolve`, and the mode decides
 * what happens next:
 *
 * - look up: open the roll or the location
 * - move: collect rolls until a location arrives, then move them all there
 * - set status: apply the chosen status to every roll scanned
 * - mark printed: stamp `label_printed_at`
 *
 * Command cards (`CMD-MOVE`, `CMD-STATUS-ATLAB`, `CMD-DONE`, …) switch modes
 * without touching the screen, so the whole workflow can be done with the
 * scanner in one hand and the binder in the other.
 */
export function ScannerConsole() {
  const router = useRouter()
  const params = useSearchParams()
  const { toast } = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const [value, setValue] = useState("")
  const [mode, setMode] = useState<Mode>("lookup")
  const [status, setStatus] = useState<RollStatus>("sleeved")
  const [pending, setPending] = useState<Film[]>([])
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState<LogEntry[]>([])
  const [camera, setCamera] = useState(false)
  const counter = useRef(0)

  const note = useCallback((input: string, text: string, tone: LogEntry["tone"] = "info") => {
    counter.current += 1
    const entry = { id: counter.current, at: new Date().toLocaleTimeString([], { timeStyle: "short" }), input, text, tone }
    setLog((current) => [entry, ...current].slice(0, 40))
  }, [])

  // Keep the field focused so the scanner always has somewhere to type.
  useEffect(() => {
    const focus = () => inputRef.current?.focus()
    focus()
    const interval = window.setInterval(() => {
      const active = document.activeElement
      if (!active || active === document.body) focus()
    }, 1000)
    return () => window.clearInterval(interval)
  }, [])

  const applyCommand = useCallback(
    (verb: string): boolean => {
      if (verb === "LOOKUP") setMode("lookup")
      else if (verb === "MOVE") setMode("move")
      else if (verb === "PRINTED") setMode("printed")
      else if (verb in STATUS_COMMANDS) {
        setMode("status")
        setStatus(STATUS_COMMANDS[verb])
      } else if (verb === "CANCEL") {
        setPending([])
        note(`CMD-${verb}`, "Sequence cancelled")
        return true
      } else if (verb === "DONE") {
        setPending([])
        note(`CMD-${verb}`, "Sequence finished")
        return true
      } else {
        note(`CMD-${verb}`, "Unknown command", "error")
        return false
      }
      note(`CMD-${verb}`, `Mode: ${MODES.find((m) => m.value === (verb in STATUS_COMMANDS ? "status" : verb.toLowerCase()))?.label ?? verb}`)
      return true
    },
    [note],
  )

  // `/scan?command=MOVE` from the shell's global scanner handler.
  useEffect(() => {
    const command = params.get("command")
    if (command) applyCommand(command.toUpperCase())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handle = useCallback(
    async (raw: string) => {
      const code = raw.trim()
      if (!code) {
        // Enter on an empty field ends a move sequence without a destination.
        if (pending.length > 0) {
          setPending([])
          note("", "Sequence cleared")
        }
        return
      }
      setBusy(true)
      try {
        let result: ScanResolution
        try {
          result = await resolveScan(code)
        } catch (error) {
          note(code, errorMessage(error), "error")
          return
        }

        if (result.kind === "command") {
          applyCommand(result.command)
          return
        }

        if (mode === "lookup") {
          note(code, result.kind === "roll" ? `Opening ${result.roll.title}` : `Opening ${result.location.path}`, "ok")
          router.push(result.url)
          return
        }

        if (mode === "move") {
          if (result.kind === "roll") {
            setPending((current) => (current.some((r) => r.id === result.roll.id) ? current : [...current, result.roll]))
            note(code, `${result.roll.archive_serial}: ${result.roll.title} — now scan the destination`)
            return
          }
          if (pending.length === 0) {
            note(code, `${result.location.path}: scan a roll first, then the destination`, "error")
            return
          }
          const moved = await bulkMoveRolls(
            pending.map((r) => r.id),
            result.location.id,
          )
          const where = moved[0]?.path ?? result.location.path
          note(code, `${moved.length} roll${moved.length === 1 ? "" : "s"} → ${where}`, "ok")
          toast({ title: `Moved ${moved.length} roll${moved.length === 1 ? "" : "s"}`, description: where ?? undefined })
          setPending([])
          return
        }

        if (result.kind !== "roll") {
          note(code, `${result.location.path}: this mode wants a roll`, "error")
          return
        }
        if (mode === "status") {
          const updated = await setRollStatus(result.roll.id, status)
          note(code, `${updated.archive_serial}: ${updated.status_label}`, "ok")
          return
        }
        if (mode === "printed") {
          await markPrinted([result.roll.id])
          note(code, `${result.roll.archive_serial}: label marked printed`, "ok")
        }
      } catch (error) {
        note(code, errorMessage(error), "error")
      } finally {
        setBusy(false)
        setValue("")
        inputRef.current?.focus()
      }
    },
    [applyCommand, mode, note, pending, router, status, toast],
  )

  return (
    <div className="space-y-6" data-testid="scanner-console">
      <div>
        <h1 className="type-page">Scan</h1>
        <p className="mt-1 type-body text-muted-foreground">
          Point a barcode scanner at a label, or the phone camera at a QR code. Serials open rolls, LOC codes
          open locations, CMD cards switch modes.
        </p>
      </div>

      <form
        className="rounded-lg border border-border bg-card p-3 sm:p-4"
        onSubmit={(event) => {
          event.preventDefault()
          void handle(value)
        }}
      >
        <div className="flex items-center gap-2">
          <ScanLine className="h-5 w-5 shrink-0 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Scan or type a code and press Enter"
            className="h-12 type-numeric text-base"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            data-testid="scan-input"
            aria-label="Scanned code"
          />
          {busy ? <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /> : null}
          <Button type="button" variant={camera ? "secondary" : "outline"} className="min-h-11" onClick={() => setCamera((on) => !on)} aria-pressed={camera} data-testid="camera-toggle">
            <Camera className="mr-2 h-4 w-4" />
            Camera
          </Button>
        </div>
        {camera ? <CameraScanner onCode={(code) => void handle(code)} onClose={() => setCamera(false)} /> : null}
      </form>

      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Scan mode">
        {MODES.map((entry) => (
          <button
            key={entry.value}
            type="button"
            role="radio"
            aria-checked={mode === entry.value}
            onClick={() => {
              setMode(entry.value)
              setPending([])
              inputRef.current?.focus()
            }}
            data-testid={`mode-${entry.value}`}
            className={cn(
              "min-h-11 rounded-full border px-4 text-sm font-medium transition-colors",
              mode === entry.value ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-secondary/60",
            )}
          >
            {entry.label}
          </button>
        ))}
        {mode === "status" ? (
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as RollStatus)}
            className="min-h-11 rounded-md border border-border bg-background px-3 text-sm"
            aria-label="Status to set"
            data-testid="status-select"
          >
            <option value="loaded">In camera</option>
            <option value="shot">Shot</option>
            <option value="at_lab">At the lab</option>
            <option value="back">Back from the lab</option>
            <option value="scanned">Scanned</option>
            <option value="sleeved">Sleeved</option>
          </select>
        ) : null}
      </div>
      <p className="type-meta -mt-3">{MODES.find((m) => m.value === mode)?.hint}</p>

      {mode === "move" ? (
        <div className={cn("rounded-lg border p-3", pending.length > 0 ? "border-primary bg-secondary/40" : "border-dashed border-border")} data-testid="pending-rolls">
          <div className="flex items-center justify-between gap-2">
            <p className="type-body font-medium">
              <MapPin className="mr-2 inline h-4 w-4" />
              {pending.length === 0 ? "Waiting for a roll" : `${pending.length} roll${pending.length === 1 ? "" : "s"} waiting for a destination`}
            </p>
            {pending.length > 0 ? (
              <Button variant="ghost" size="sm" onClick={() => setPending([])}>
                <X className="mr-1 h-4 w-4" />
                Clear
              </Button>
            ) : null}
          </div>
          {pending.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-2">
              {pending.map((roll) => (
                <li key={roll.id} className="flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1 text-sm">
                  <span className="type-numeric">{roll.archive_serial}</span>
                  <span className="truncate">{roll.title}</span>
                  <StatusBadge status={roll.status} />
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="type-section">Log</h2>
          <Link href="/print/commands" target="_blank" rel="noopener" className="type-meta underline">
            Print the command cards
          </Link>
        </div>
        {log.length === 0 ? (
          <p className="type-body text-muted-foreground">
            <Keyboard className="mr-2 inline h-4 w-4" />
            Nothing scanned yet. Try typing a serial like NEG-2024-0001 and pressing Enter.
          </p>
        ) : (
          <ol className="space-y-1" data-testid="scan-log">
            {log.map((entry) => (
              <li key={entry.id} className="flex items-start gap-2 rounded-md border border-border px-3 py-2 type-body">
                {entry.tone === "ok" ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                ) : entry.tone === "error" ? (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                ) : (
                  <ScanLine className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                )}
                <span className="type-numeric shrink-0 text-muted-foreground">{entry.at}</span>
                {entry.input ? <span className="type-numeric shrink-0">{entry.input}</span> : null}
                <span className="min-w-0 flex-1">{entry.text}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

/**
 * The phone camera as a scanner. `BarcodeDetector` where the browser has it
 * (Chrome, Android, recent Safari); a jsQR fallback that reads QR codes only.
 * Needs a secure context (HTTPS or localhost) for `getUserMedia`.
 */
function CameraScanner({ onCode, onClose }: { onCode: (code: string) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState<string | null>(null)
  const lastCode = useRef<{ code: string; at: number } | null>(null)

  useEffect(() => {
    let stream: MediaStream | null = null
    let stopped = false
    let frame = 0
    const video = videoRef.current
    if (!video) return

    const emit = (code: string) => {
      const now = Date.now()
      if (lastCode.current && lastCode.current.code === code && now - lastCode.current.at < 2500) return
      lastCode.current = { code, at: now }
      onCode(code)
    }

    const run = async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("This browser cannot open the camera here. The page must be served over HTTPS or on localhost.")
        return
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
      } catch (caught) {
        setError(`Camera not available: ${caught instanceof Error ? caught.message : String(caught)}`)
        return
      }
      if (stopped) return
      video.srcObject = stream
      await video.play().catch(() => undefined)

      const Detector = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => { detect: (v: HTMLVideoElement) => Promise<{ rawValue: string }[]> } }).BarcodeDetector
      const detector = Detector ? new Detector({ formats: ["qr_code", "code_128"] }) : null
      type JsQr = (data: Uint8ClampedArray, w: number, h: number) => { data: string } | null
      let jsQR: JsQr | null = null
      if (!detector) {
        const mod = await import("jsqr")
        jsQR = mod.default as unknown as JsQr
      }
      const canvas = document.createElement("canvas")

      const tick = async () => {
        if (stopped) return
        try {
          if (detector) {
            const found = await detector.detect(video)
            for (const item of found) if (item.rawValue) emit(item.rawValue)
          } else if (jsQR && video.videoWidth > 0) {
            canvas.width = video.videoWidth
            canvas.height = video.videoHeight
            const context = canvas.getContext("2d", { willReadFrequently: true })
            if (context) {
              context.drawImage(video, 0, 0)
              const image = context.getImageData(0, 0, canvas.width, canvas.height)
              const result = jsQR(image.data, image.width, image.height)
              if (result?.data) emit(result.data)
            }
          }
        } catch {
          // a frame that could not be decoded is not an error
        }
        frame = window.setTimeout(() => void tick(), 250)
      }
      void tick()
    }
    void run()

    return () => {
      stopped = true
      window.clearTimeout(frame)
      stream?.getTracks().forEach((track) => track.stop())
    }
  }, [onCode])

  return (
    <div className="mt-3 space-y-2" data-testid="camera-scanner">
      {error ? (
        <p role="alert" className="type-body text-destructive">
          {error}
        </p>
      ) : (
        <video ref={videoRef} className="max-h-72 w-full rounded-md bg-black object-cover" muted playsInline />
      )}
      <div className="flex items-center justify-between">
        <p className="type-meta">Hold a QR code or a barcode in front of the camera.</p>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Close camera
        </Button>
      </div>
    </div>
  )
}
