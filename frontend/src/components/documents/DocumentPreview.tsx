/**
 * Look at a document before it goes to the printer.
 *
 * **Printing blind is how the wrong invoice gets handed to a patient.** A
 * "Print" button that goes straight to the dialog prints whatever is under it,
 * and the counter learns it was the previous patient's bill when the patient
 * reads it. So documents open here first, at the width of the paper, with the
 * print action beside them.
 *
 * Wider than `DetailPanel` on purpose. A slide-over at 32rem is right for a
 * record's facts and wrong for an A4 invoice, whose line-item table then wraps
 * every description onto three lines and reads nothing like what prints.
 *
 * **The print-mode classes on the wrappers are not decoration.** The print
 * stylesheet lifts the `[data-printable]` element to the top-left of the sheet
 * with `position: absolute`; inside a `position: fixed`, `overflow: auto`
 * modal, "absolute" resolves against the modal and the overflow clips it — so
 * a two-page invoice printed as its first screenful. The wrappers go static
 * and unclipped for print, which is what lets a long document paginate.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { Button } from "@/components/ui/primitives";
import { printElement } from "@/lib/export";

export function DocumentPreview({
  open,
  onClose,
  title,
  subtitle,
  /** The `id` of the `PrintableDocument` inside `children`. */
  printTarget,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  printTarget: string;
  children: React.ReactNode;
}) {
  React.useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/40 p-4 backdrop-blur-sm sm:p-8",
        "print:static print:block print:overflow-visible print:bg-transparent print:p-0 print:backdrop-blur-none",
      )}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : "Document preview"}
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "w-full max-w-4xl rounded-xl border bg-background shadow-modal animate-in fade-in-0 zoom-in-[0.98] duration-quick",
          "print:max-w-none print:rounded-none print:border-0 print:shadow-none",
        )}
      >
        <header
          data-print="hide"
          className="flex items-center justify-between gap-3 border-b px-5 py-3"
        >
          <div className="min-w-0">
            <p className="truncate type-heading">{title}</p>
            {subtitle ? <p className="truncate type-caption">{subtitle}</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" onClick={() => printElement(printTarget)}>
              <Icon name="print" size="sm" className="mr-1.5" />
              Print or save as PDF
            </Button>
            <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close">
              <Icon name="close" size="sm" />
            </Button>
          </div>
        </header>

        {/* A grey gutter around a white sheet, so it reads as paper on a desk
            rather than as another panel of the application. */}
        <div className="bg-muted/50 p-4 sm:p-8 print:bg-transparent print:p-0">
          <div className="mx-auto max-w-[52rem] bg-card shadow-raised print:max-w-none print:shadow-none">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
