"use client"

import { useEffect, useState } from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"

interface DeleteConfirmationDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** `keepFiles` is what the checkbox below says; ignore it where it is not offered. */
  onConfirm: (options: { keepFiles: boolean }) => void
  title: string
  description: string
  /**
   * Show the "keep the files on disk" checkbox (M2, R#9).
   *
   * Deleting a roll or a frame now deletes the scan file with it. That is what
   * people expect and it is the only way disk usage ever goes down, but it is not
   * undoable — so the dialog says so, and this opts out per deletion.
   */
  offerKeepFiles?: boolean
  /** What the files belong to, for the checkbox's explanation. */
  fileNoun?: string
  confirmLabel?: string
  /**
   * Radix closes the dialog on the confirm button by default. Set this false when
   * the request can come back with something to say — a 409 "still in use", say —
   * and the caller closes the dialog itself once it knows (R#66).
   */
  closeOnConfirm?: boolean
  /** An answer from the last attempt, shown in the dialog that asked. */
  notice?: string | null
}

export function DeleteConfirmationDialog({
  open,
  onOpenChange,
  onConfirm,
  title,
  description,
  offerKeepFiles = false,
  fileNoun = "scan files",
  confirmLabel = "Delete",
  closeOnConfirm = true,
  notice = null,
}: DeleteConfirmationDialogProps) {
  const [keepFiles, setKeepFiles] = useState(false)

  // Every deletion is its own decision; the box does not stay ticked.
  useEffect(() => {
    if (open) setKeepFiles(false)
  }, [open])

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>

        {offerKeepFiles ? (
          <div className="flex items-start gap-2 rounded-md border border-border p-3">
            <Checkbox
              id="keep-files"
              checked={keepFiles}
              onCheckedChange={(checked) => setKeepFiles(checked === true)}
              data-testid="keep-files"
              className="mt-0.5"
            />
            <div className="space-y-0.5">
              <Label htmlFor="keep-files" className="font-normal">
                Keep the {fileNoun} on disk
              </Label>
              <p className="type-meta">
                The records go either way. Left on disk, the files become orphans you can
                find again with the orphan sweep.
              </p>
            </div>
          </div>
        ) : null}

        {notice ? (
          <p role="alert" className="type-body text-destructive" data-testid="delete-notice">
            {notice}
          </p>
        ) : null}

        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={(event) => {
              if (!closeOnConfirm) event.preventDefault()
              onConfirm({ keepFiles })
            }}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
