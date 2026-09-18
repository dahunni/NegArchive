"use client"

import { useState } from "react"
import { Check, Copy, FlaskConical, Loader2 } from "lucide-react"

import { type HandoffResult, errorMessage, prepareNegpyHandoff } from "@/lib/api"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useToast } from "@/hooks/use-toast"

/**
 * "Open in NegPy" (roadmap M5).
 *
 * NegPy has no CLI, no URL scheme and nothing listening, so this cannot launch
 * anything — and pretending otherwise would be the worst kind of button. What it
 * does instead is prepare the roll: a folder of hard links named with NegPy's
 * export preset, and a metadata preset carrying the roll's serial and gear. The
 * dialog then hands over the two paths, because the last step happens in NegPy.
 */
export function NegpyHandoffButton({ rollId, disabled }: { rollId: number; disabled?: boolean }) {
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<HandoffResult | null>(null)

  const prepare = async () => {
    setBusy(true)
    try {
      setResult(await prepareNegpyHandoff(rollId))
    } catch (error) {
      toast({
        title: "Could not prepare the roll",
        description: errorMessage(error),
        variant: "destructive",
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button
        variant="outline"
        className="min-h-11"
        onClick={prepare}
        disabled={busy || disabled}
        title={disabled ? "This roll has no scans yet" : undefined}
        data-testid="open-in-negpy"
      >
        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FlaskConical className="mr-2 h-4 w-4" />}
        Open in NegPy
      </Button>

      <Dialog open={result !== null} onOpenChange={(open) => !open && setResult(null)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Ready for NegPy</DialogTitle>
            <DialogDescription>
              {result
                ? `${result.frames} frames ${result.copied ? "copied" : "hard-linked"} — the originals were not moved,
                   renamed or changed.`
                : null}
            </DialogDescription>
          </DialogHeader>

          {/* min-w-0 all the way down: DialogContent is a grid, and without it a long
              absolute path makes the dialog wider than the screen instead of
              truncating inside it. */}
          {result ? (
            <ol className="min-w-0 space-y-3 type-body" data-testid="handoff-steps">
              <li className="min-w-0">
                <span className="type-meta uppercase tracking-wide">1 · Add this folder in NegPy</span>
                <PathRow value={result.folder} />
              </li>
              {result.preset_path ? (
                <li className="min-w-0">
                  <span className="type-meta uppercase tracking-wide">2 · Apply the metadata preset</span>
                  <PathRow value={result.preset_path} />
                </li>
              ) : null}
              <li className="min-w-0">
                <span className="type-meta uppercase tracking-wide">3 · Export with this filename pattern</span>
                <PathRow value={result.filename_pattern} />
                <p className="mt-1 type-meta">
                  Export into a folder NegArchive watches and the edited scans come back with their roll and
                  frame numbers intact.
                </p>
              </li>
              {result.skipped.length > 0 ? (
                <li className="type-meta text-destructive">
                  {result.skipped.length} file(s) could not be read and were left out.
                </li>
              ) : null}
            </ol>
          ) : null}

          <DialogFooter>
            <Button onClick={() => setResult(null)} className="min-h-11">
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** A path with a copy button: it has to be pasted into another application. */
function PathRow({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="mt-1 flex min-w-0 items-center gap-2">
      <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 type-numeric text-sm" title={value}>
        {value}
      </code>
      <Button
        variant="ghost"
        size="icon"
        className="h-9 w-9 shrink-0"
        aria-label={`Copy ${value}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          } catch {
            // No clipboard permission (or no clipboard at all, over plain http on
            // some browsers): the path is on screen and selectable anyway.
          }
        }}
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </Button>
    </div>
  )
}
