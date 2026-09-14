/**
 * shadcn/ui primitives, collected in one file.
 *
 * shadcn is copy-in source rather than an installed package, which is the
 * reason it was chosen: this product needs dense, domain-shaped tables and
 * forms (batch pickers with expiry dates, bed boards, triage queues) that no
 * generic component library gets right, and owning the source means editing
 * rather than fighting it.
 *
 * They live together while the set is small. Split them into one file per
 * component when this exceeds roughly a screenful each.
 */

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Button                                                                      */
/* -------------------------------------------------------------------------- */

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline:
          "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render as the child element instead of a <button>, for links. */
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

/* -------------------------------------------------------------------------- */
/* Card                                                                        */
/* -------------------------------------------------------------------------- */

export const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "rounded-xl border border-border/60 bg-card text-card-foreground shadow-raised",
      className,
    )}
    {...props}
  />
));
Card.displayName = "Card";

export const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col space-y-1.5 p-6", className)}
    {...props}
  />
));
CardHeader.displayName = "CardHeader";

export const CardTitle = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-base font-semibold leading-none tracking-tight", className)}
    {...props}
  />
));
CardTitle.displayName = "CardTitle";

export const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
));
CardDescription.displayName = "CardDescription";

export const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
));
CardContent.displayName = "CardContent";

export const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-6 pt-0", className)}
    {...props}
  />
));
CardFooter.displayName = "CardFooter";

/* -------------------------------------------------------------------------- */
/* Badge                                                                       */
/* -------------------------------------------------------------------------- */

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/10 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive:
          "border-transparent bg-destructive/10 text-destructive",
        // Amber, for states that are neither fine nor failed: over a warning
        // threshold, awaiting a decision, in a grace period.
        warning: "border-transparent bg-warning/15 text-warning",
        success: "border-transparent bg-good/15 text-good",
        outline: "text-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

/* -------------------------------------------------------------------------- */
/* Input, Label, Textarea                                                      */
/* -------------------------------------------------------------------------- */

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, type, ...props }, ref) => (
  <input
    type={type}
    ref={ref}
    className={cn(
      "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export const Label = React.forwardRef<
  HTMLLabelElement,
  React.LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => (
  <label
    ref={ref}
    className={cn(
      "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
      className,
    )}
    {...props}
  />
));
Label.displayName = "Label";

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(
      "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Select.displayName = "Select";

/* -------------------------------------------------------------------------- */
/* Progress                                                                    */
/* -------------------------------------------------------------------------- */

export function Progress({
  value,
  max = 100,
  tone = "default",
  className,
}: {
  value: number;
  max?: number;
  /** Signals how close to the limit this is, without needing a legend. */
  tone?: "default" | "warning" | "danger";
  className?: string;
}) {
  const percent = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const toneClass = {
    default: "bg-primary",
    warning: "bg-warning",
    danger: "bg-destructive",
  }[tone];

  return (
    <div
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-secondary",
        className,
      )}
      role="progressbar"
      aria-valuenow={value}
      aria-valuemax={max}
    >
      <div
        className={cn("h-full transition-all", toneClass)}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Table                                                                       */
/* -------------------------------------------------------------------------- */

export function Table({
  className,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="relative w-full overflow-auto">
      <table
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  );
}

export function TableHeader(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className="[&_tr]:border-b" {...props} />;
}

export function TableBody(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className="[&_tr:last-child]:border-0" {...props} />;
}

/**
 * A table row, which behaves like a button when it is one.
 *
 * **Every row used to get `hover:bg-muted/50`, clickable or not**, so the hover
 * signal meant nothing: eighteen screens open a record when you click a row and
 * looked exactly like the eleven that do not. "Most things are unclickable" was
 * the report, and the truth was worse — most things *were* clickable and
 * nothing said so.
 *
 * So the affordance follows the behaviour. A row with an `onClick` gets the
 * pointer, a stronger hover and a focus ring; a row without gets a hover so
 * faint it reads as "you are on this line" rather than "this does something".
 * Derived from `onClick` rather than from a prop, so the eighteen screens
 * already passing one get it without being edited — and any new screen gets it
 * by writing the handler it was going to write anyway.
 *
 * **And it is reachable from a keyboard**, which it was not. A `<tr>` with a
 * click handler is invisible to Tab, so every one of those records could only
 * be opened with a mouse. `role="button"` and `tabIndex` fix that; the Enter
 * and Space handler fires only when the row itself has focus, so a button
 * inside the row is not double-triggered by its own keypress.
 */
export function TableRow({
  className,
  onClick,
  onKeyDown,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) {
  const interactive = Boolean(onClick);

  return (
    <tr
      className={cn(
        "border-b transition-colors data-[state=selected]:bg-muted",
        interactive
          ? "cursor-pointer hover:bg-muted focus-visible:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          : "hover:bg-muted/30",
        className,
      )}
      onClick={onClick}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (!interactive || event.defaultPrevented) return;
        // Only when the row itself has focus. A button inside the row handles
        // its own Enter, and firing both would open the record *and* do
        // whatever the button does.
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick?.(event as unknown as React.MouseEvent<HTMLTableRowElement>);
        }
      }}
      {...props}
    />
  );
}

export function TableHead({
  className,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "h-10 px-3 text-left align-middle text-xs font-medium uppercase tracking-wide text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({
  className,
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-3 py-2.5 align-middle", className)} {...props} />;
}

/* -------------------------------------------------------------------------- */
/* Alert                                                                       */
/* -------------------------------------------------------------------------- */

const alertVariants = cva(
  "relative w-full rounded-lg border p-4 text-sm [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-4 [&>svg~*]:pl-7",
  {
    variants: {
      variant: {
        default: "bg-background text-foreground",
        destructive:
          "border-destructive/40 bg-destructive/5 text-destructive [&>svg]:text-destructive",
        // The ink-on-tint pair, not the bare ink. `text-warning` on a 5% wash
        // is about 3.7:1 — the amber is light enough that it fails small text —
        // which is what the colour codemod produced from `text-amber-800`. The
        // subtle pair was contrast-checked as a pair (6.8:1 light, 8.7:1 dark).
        warning:
          "border-warning/40 bg-warning-subtle text-warning-subtle-foreground [&>svg]:text-warning",
        info: "border-primary/30 bg-primary/5 text-foreground [&>svg]:text-primary",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Alert({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>) {
  return (
    <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />
  );
}

export function AlertTitle({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h5
      className={cn("mb-1 font-medium leading-none tracking-tight", className)}
      {...props}
    />
  );
}

export function AlertDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <div className={cn("text-sm [&_p]:leading-relaxed", className)} {...props} />
  );
}

/* -------------------------------------------------------------------------- */
/* Detail panel                                                               */
/* -------------------------------------------------------------------------- */

/**
 * The panel a row opens into.
 *
 * Most screens in this console are a table and nothing else: rows you can read
 * and no way to see the thing behind one. The data is usually already there —
 * facilities have a detail endpoint with their departments on it that no screen
 * had ever called — so the product reads as thinner than it is.
 *
 * One component so that opening a row feels the same everywhere. A pattern
 * invented per screen is how a product ends up with four different ideas of
 * what "view" means.
 *
 * **A slide-over on a wide screen, a full sheet on a narrow one.** A modal
 * centred on a phone leaves no room for the content and hides the list it came
 * from; a full-width sheet on a monitor loses the context that makes a detail
 * view worth having.
 *
 * Escape closes it, and so does the backdrop. Both are what people try first,
 * and a panel that traps you is worse than no panel.
 */
export function DetailPanel({
  open,
  title,
  subtitle,
  onClose,
  footer,
  children,
}: {
  open: boolean;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  onClose: () => void;
  footer?: React.ReactNode;
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
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        className="relative flex h-full w-full flex-col border-l bg-background shadow-xl sm:max-w-lg"
      >
        <header className="flex items-start justify-between gap-3 border-b px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{title}</h2>
            {subtitle ? (
              <p className="truncate text-xs text-muted-foreground">
                {subtitle}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-muted"
          >
            ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer ? (
          <footer className="border-t px-5 py-3">{footer}</footer>
        ) : null}
      </aside>
    </div>
  );
}

/**
 * One labelled fact inside a detail panel.
 *
 * A dash rather than an empty cell for a missing value: blank reads as "the
 * screen failed to load it", and an em dash reads as "there isn't one", which
 * are different things a reader should not have to guess between.
 */
export function DetailRow({
  label,
  children,
}: {
  label: string;
  children?: React.ReactNode;
}) {
  const empty =
    children === null || children === undefined || children === "";
  return (
    <div className="flex items-start justify-between gap-4 border-b py-2 last:border-b-0">
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 text-right text-sm">
        {empty ? <span className="text-muted-foreground">—</span> : children}
      </span>
    </div>
  );
}
