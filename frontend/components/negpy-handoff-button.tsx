"use client"

import { useState } from "react"
import { FlaskConical, Loader2 } from "lucide-react"

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
import { CopyValue } from "@/components/copy-value"
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

  const steps: { label: string; value: string; copyLabel: string; note?: string }[] = result
    ? [
        { label: "Add this folder in NegPy", value: result.folder, copyLabel: "the folder" },
        ...(result.preset_path
          ? [
              {
                label: "Apply the metadata preset",
                value: result.preset_path,
                copyLabel: "the preset path",
              },
            ]
          : []),
        {
          label: "Export with this filename pattern",
          value: result.filename_pattern,
          copyLabel: "the filename pattern",
          note: "Export into a folder NegArchive watches and the edited scans come back with their roll and frame numbers intact.",
        },
      ]
    : []

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
              {/* Numbered from the steps there actually are: a roll without a preset
                  has two, and "1 · … 3 · …" reads like a step went missing. */}
              {steps.map((step, index) => (
                <li key={step.label} className="min-w-0">
                  <span className="type-meta uppercase tracking-wide">
                    {index + 1} · {step.label}
                  </span>
                  <CopyValue value={step.value} label={step.copyLabel} />
                  {step.note ? <p className="mt-1 type-meta">{step.note}</p> : null}
                </li>
              ))}
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
