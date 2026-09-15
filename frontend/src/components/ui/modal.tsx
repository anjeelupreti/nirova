/**
 * One modal, with a width.
 *
 * **Sixteen screens hand-rolled their own** -- `fixed inset-0` over a
 * `max-w-lg` card -- and every one of them grew downward as content was added,
 * because the only dimension a hand-rolled dialog ever gets is height. A
 * discharge form with eight fields became a column two screens tall on a
 * monitor with 1200 unused pixels either side.
 *
 * So the width is a decision the caller makes (`size`), the body scrolls
 * inside the dialog rather than the page scrolling behind it, and the header
 * and footer stay put -- which is what makes a long form usable: the title
 * says what you are doing and the buttons never run away.
 *
 * Radix underneath, for the parts that are tedious and noticed when wrong:
 * focus is trapped and returned, Escape and the overlay dismiss, the page
 * behind is inert, and the dialog is announced with its title.
 *
 * `ModalColumns` is the other half of the answer: two columns on a wide
 * screen, one on a phone, so a form uses the width it was given.
 */

import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

const SIZES = {
  sm: "max-w-md",
  md: "max-w-xl",
  lg: "max-w-3xl",
  xl: "max-w-5xl",
  full: "max-w-[min(80rem,95vw)]",
} as const;

export function Modal({
  open,
  onClose,
  title,
  description,
  size = "md",
  footer,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** How wide it may grow. A form with two columns wants `lg` or wider. */
  size?: keyof typeof SIZES;
  /** Pinned to the bottom: the buttons never scroll out of reach. */
  footer?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-neutral-1000/40 backdrop-blur-[2px]",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
          )}
        />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[95vw] -translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-2xl border bg-card shadow-modal outline-none",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
            SIZES[size],
            className,
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold tracking-tight">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-0.5 text-sm text-muted-foreground">
                  {description}
                </Dialog.Description>
              ) : null}
            </div>
            <Dialog.Close
              aria-label="Close"
              className="rounded-md p-1.5 text-muted-foreground transition-colors duration-quick hover:bg-accent hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          {/* The body scrolls, not the page: a modal that scrolls the page
              behind it loses its own buttons and the reader's place at once. */}
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

          {footer ? (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t px-5 py-3.5">
              {footer}
            </div>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Two columns on a wide dialog, one on a phone.
 *
 * The reason a form gets a width at all: eight fields in one column is a
 * scroll, and in two columns it is a form somebody can see at once.
 */
export function ModalColumns({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("grid gap-4 sm:grid-cols-2", className)}>{children}</div>;
}

/** A field that should span both columns inside `ModalColumns`. */
export function ModalWide({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("sm:col-span-2", className)}>{children}</div>;
}
