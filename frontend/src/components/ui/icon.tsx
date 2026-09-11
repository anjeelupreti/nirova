/**
 * Icons, as a vocabulary rather than as a shopping trip.
 *
 * **The problem this solves is not "we need icons" — lucide was already
 * installed and used on every screen. It is that nothing agreed.** A patient
 * was `Users` in the sidebar, `UserCog` in the directory and `UserCheck` in
 * self-service. Sizes ranged from `h-3 w-3` to `h-5 w-5` inside a single card.
 * Stroke weight was whatever lucide's default happened to be, at every size,
 * so a 16px icon and a 32px icon were drawn with the same 2px line and the
 * large one looked hollow.
 *
 * Two fixes, both here:
 *
 *  1. **`ICONS` is the vocabulary.** A concept in this product — a patient, a
 *     ward, a batch, an invoice — has exactly one glyph, named for the concept
 *     and not for the picture. Screens ask for `ICONS.patient`, so the day
 *     somebody decides a patient is better drawn some other way, it changes
 *     once and everywhere.
 *
 *  2. **`<Icon>` owns size and stroke together.** Stroke weight scales *down*
 *     as the icon grows — 1.75 at 14px, 1.5 at 20px, 1.25 above — because a
 *     constant stroke makes small icons muddy and large ones skeletal. This is
 *     the single most visible difference between an icon set that was styled
 *     and one that was imported.
 */

import * as React from "react";
import {
  Activity, AlertTriangle, ArchiveRestore, ArrowDownRight, ArrowLeftRight,
  ArrowRight, ArrowUpRight, BadgeCheck, BarChart3, Beaker, BedDouble, Bell,
  Blocks, Bookmark, Box, Boxes, Brain, Building2, CalendarClock, CalendarDays,
  CalendarRange, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  ChevronsUpDown, CircleDot, ClipboardCheck, ClipboardList, Clock, Coins,
  Command, Copy, CreditCard, Download, Droplet, Ellipsis, ExternalLink, Eye,
  FileSpreadsheet, FileText, FlaskConical, Gauge, GaugeCircle, Globe,
  GraduationCap, Grid2x2, HeartPulse, History, Home, Hospital, Inbox, Info,
  KeyRound, LayoutDashboard, LayoutGrid, LifeBuoy, ListOrdered, Lock, LogOut,
  Mail, MapPin, Microscope, Minus, Moon, Package, PanelLeftClose,
  PanelLeftOpen, Paperclip, Pencil, Phone, Pill, Pin, Plus, Printer, RefreshCw,
  Rows3, Scale, Scissors, ScrollText, Search, Send, Settings2, Share2, Shield,
  ShieldAlert, ShieldCheck, ShoppingCart, SlidersHorizontal, Snowflake, Sparkles,
  Stethoscope, Sun, Syringe, Table2, Tags, Thermometer, Trash2, TrendingDown,
  TrendingUp, Truck, User, UserCheck, UserCog, UserPlus, UserX, Users, Wallet,
  X, Zap,
} from "lucide-react";

import { cn } from "@/lib/utils";

export type IconComponent = typeof Users;

/* -------------------------------------------------------------------------- */
/* The vocabulary                                                              */
/* -------------------------------------------------------------------------- */

/**
 * Named by the concept, never by the picture.
 *
 * `ICONS.expiring` rather than `Clock`, because the day expiry is better drawn
 * as an hourglass, every screen that means "expiring" should change and every
 * screen that meant "a duration" should not. Naming by picture makes those two
 * indistinguishable in a search.
 */
export const ICONS = {
  /* -- People ---------------------------------------------------------- */
  patient: Users,
  patientSingle: User,
  staff: UserCog,
  doctor: Stethoscope,
  nurse: ClipboardCheck,
  invite: UserPlus,
  deactivate: UserX,
  verifiedPerson: UserCheck,
  directory: Users,

  /* -- Clinical -------------------------------------------------------- */
  encounter: ClipboardList,
  consultation: Stethoscope,
  vitals: Activity,
  emergency: Zap,
  triage: Thermometer,
  ward: BedDouble,
  icu: HeartPulse,
  theatre: Scissors,
  prescription: Pill,
  laboratory: FlaskConical,
  imaging: Microscope,
  bloodBank: Droplet,
  referral: Send,
  specimen: Beaker,
  immunisation: Syringe,
  diagnosis: Brain,

  /* -- Scheduling ------------------------------------------------------ */
  appointment: CalendarDays,
  queue: ListOrdered,
  roster: CalendarRange,
  attendance: CalendarClock,
  duration: Clock,
  history: History,

  /* -- Supply ---------------------------------------------------------- */
  pharmacy: Package,
  product: Box,
  stock: Boxes,
  batch: Blocks,
  counter: ShoppingCart,
  procurement: Truck,
  supplier: Building2,
  coldChain: Snowflake,
  expiring: Clock,
  returnGoods: ArchiveRestore,

  /* -- Money ----------------------------------------------------------- */
  invoice: FileText,
  billing: CreditCard,
  payment: Wallet,
  payroll: Coins,
  finance: Scale,
  claim: ShieldCheck,
  price: Tags,

  /* -- Organization ---------------------------------------------------- */
  organization: Hospital,
  facility: Building2,
  department: Blocks,
  capacity: GaugeCircle,
  platform: Globe,
  changeRequest: ScrollText,
  configuration: SlidersHorizontal,
  dataImport: FileSpreadsheet,

  /* -- Access ---------------------------------------------------------- */
  access: KeyRound,
  role: Shield,
  permission: Lock,
  privacy: ShieldAlert,
  breakGlass: LifeBuoy,
  audit: History,
  credential: BadgeCheck,
  training: GraduationCap,

  /* -- Workspace ------------------------------------------------------- */
  home: Home,
  dashboard: LayoutDashboard,
  workspace: Inbox,
  notification: Bell,
  report: BarChart3,
  search: Search,
  command: Command,
  pin: Pin,
  bookmark: Bookmark,
  settings: Settings2,
  signOut: LogOut,

  /* -- View modes ------------------------------------------------------ */
  viewTable: Table2,
  viewCards: LayoutGrid,
  viewBoard: Rows3,
  viewGrid: Grid2x2,
  viewCalendar: CalendarDays,

  /* -- Actions --------------------------------------------------------- */
  add: Plus,
  edit: Pencil,
  remove: Trash2,
  refresh: RefreshCw,
  download: Download,
  print: Printer,
  copy: Copy,
  share: Share2,
  attach: Paperclip,
  open: ExternalLink,
  view: Eye,
  transfer: ArrowLeftRight,
  next: ArrowRight,
  more: Ellipsis,
  close: X,
  confirm: Check,

  /* -- Feedback -------------------------------------------------------- */
  success: CheckCircle2,
  warning: AlertTriangle,
  info: Info,
  live: CircleDot,
  trendUp: TrendingUp,
  trendDown: TrendingDown,
  trendFlat: Minus,
  riseSmall: ArrowUpRight,
  fallSmall: ArrowDownRight,
  meter: Gauge,
  spark: Sparkles,

  /* -- Chrome ---------------------------------------------------------- */
  collapse: PanelLeftClose,
  expand: PanelLeftOpen,
  chevronDown: ChevronDown,
  chevronRight: ChevronRight,
  chevronLeft: ChevronLeft,
  chevronUpDown: ChevronsUpDown,
  themeLight: Sun,
  themeDark: Moon,
  mail: Mail,
  phone: Phone,
  location: MapPin,
} satisfies Record<string, IconComponent>;

export type IconName = keyof typeof ICONS;

/* -------------------------------------------------------------------------- */
/* The renderer                                                                */
/* -------------------------------------------------------------------------- */

const SIZES = {
  xs: { px: 12, className: "h-3 w-3", stroke: 2 },
  sm: { px: 14, className: "h-3.5 w-3.5", stroke: 1.75 },
  md: { px: 16, className: "h-4 w-4", stroke: 1.75 },
  lg: { px: 20, className: "h-5 w-5", stroke: 1.5 },
  xl: { px: 24, className: "h-6 w-6", stroke: 1.5 },
  "2xl": { px: 32, className: "h-8 w-8", stroke: 1.25 },
} as const;

export type IconSize = keyof typeof SIZES;

export interface IconProps extends Omit<React.SVGProps<SVGSVGElement>, "name"> {
  /** A concept from `ICONS`, or a lucide component for the rare one-off. */
  name: IconName | IconComponent;
  size?: IconSize;
  /**
   * The accessible name. **Omit it for a decorative icon** — one that sits
   * beside a label saying the same thing — and the icon is hidden from screen
   * readers instead of read out twice, which is the commoner mistake.
   */
  label?: string;
}

export function Icon({
  name,
  size = "md",
  label,
  className,
  ...props
}: IconProps) {
  const Glyph = (typeof name === "string" ? ICONS[name] : name) as IconComponent;
  const spec = SIZES[size];

  return (
    <Glyph
      className={cn("shrink-0", spec.className, className)}
      strokeWidth={spec.stroke}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
      {...props}
    />
  );
}

/**
 * An icon in a tinted container — for a stat tile, an empty state, the head of
 * a section.
 *
 * A bare icon at 32px floating in whitespace looks unfinished; the same icon
 * at 16px inside a 32px tinted square looks placed. The tint defaults to the
 * neutral fill rather than the brand, because a page where six things are
 * teal has no accent left.
 */
export function IconTile({
  name,
  tone = "neutral",
  size = "md",
  className,
}: {
  name: IconName | IconComponent;
  tone?: "neutral" | "brand" | "good" | "warning" | "serious" | "critical" | "info";
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const box = {
    sm: "h-7 w-7 rounded-md",
    md: "h-9 w-9 rounded-lg",
    lg: "h-11 w-11 rounded-lg",
  }[size];
  const glyph = { sm: "sm", md: "md", lg: "lg" }[size] as IconSize;

  const tones = {
    neutral: "bg-muted text-muted-foreground",
    brand: "bg-primary-subtle text-primary-subtle-foreground",
    good: "bg-good-subtle text-good-subtle-foreground",
    warning: "bg-warning-subtle text-warning-subtle-foreground",
    serious: "bg-serious-subtle text-serious-subtle-foreground",
    critical: "bg-critical-subtle text-critical-subtle-foreground",
    info: "bg-info-subtle text-info-subtle-foreground",
  } as const;

  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center",
        box,
        tones[tone],
        className,
      )}
    >
      <Icon name={name} size={glyph} />
    </div>
  );
}
