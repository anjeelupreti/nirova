"""The organization's day, in one answer -- and the same answer for yesterday.

**The owner's dashboard had no figures about the organization.** Its top band
counted the owner's own inbox, and every panel read one department at one
facility. This answers what somebody who runs a hospital asks first: patients
seen, beds, laboratory, money.

Each block is included only when the viewer may read what it counts **and**
the plan includes the module it belongs to. A block left out is absent, never
zero: "no inpatients" and "you may not see inpatients" are not the same claim.

**Against yesterday, fairly.** A figure without a comparison cannot say
whether a day is going well. Two kinds of figure need two answers:

- A figure that *counts events* -- patients seen, admissions, money collected
  -- is compared with **yesterday up to this same time of day**, counted from
  the records. Compared with yesterday's whole day instead, every figure reads
  as a collapse at nine in the morning.
- A figure that is a *level* -- beds occupied, money owed, work outstanding --
  cannot be recounted for yesterday, because the records say what is true now,
  not what was true then. Those come from the nightly `DailySnapshot`, and
  where no snapshot exists yet there is no comparison rather than a guess.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.rbac.permissions import Scope

_CENTS = Decimal("0.01")

#: Figures that are a level now rather than a count over the day. Their
#: yesterday comes only from a snapshot.
POINT_IN_TIME = {
    "outpatients": ("waiting",),
    "emergency": ("in_department",),
    "inpatients": ("occupied", "beds", "occupancy_percent"),
    "laboratory": ("outstanding", "critical_open"),
    "billing": ("outstanding", "overdue_invoices"),
}


def _money(value) -> str:
    return str((value or Decimal("0")).quantize(_CENTS))


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def figures(authorization, entitlements, facility=None, start=None, until=None) -> dict:
    """Every block this viewer may see, for events in `[start, until)`.

    Levels (beds occupied, money owed) are always as they stand now; the caller
    decides whether those belong in its answer.
    """
    until = until or timezone.now()
    start = start or _day_start(timezone.localdate(until))
    day = timezone.localtime(start).date()
    at = {"facility": facility} if facility is not None else {}

    def may(code: str, scope: str = Scope.FACILITY) -> bool:
        return authorization.has(code, scope)

    result: dict = {}

    if may("encounter.read", Scope.OWN):
        from apps.encounters.models import OPEN_ENCOUNTER_STATUSES, Encounter, EncounterType
        from apps.scheduling.models import Appointment, AppointmentStatus

        seen = Encounter.objects.filter(
            encounter_type=EncounterType.OUTPATIENT,
            started_at__gte=start, started_at__lt=until, **at,
        )
        # Bookings are for the whole day, not up to a time of it.
        booked = Appointment.objects.filter(scheduled_for__date=day, **at).exclude(
            status__in=[AppointmentStatus.CANCELLED, AppointmentStatus.RESCHEDULED],
        )
        result["outpatients"] = {
            "seen": seen.count(),
            "waiting": seen.filter(status__in=list(OPEN_ENCOUNTER_STATUSES)).count(),
            "appointments": booked.count(),
            "no_shows": booked.filter(status=AppointmentStatus.NO_SHOW).count(),
        }

        if entitlements.has_module("hospital"):
            emergency = Encounter.objects.filter(encounter_type=EncounterType.EMERGENCY, **at)
            result["emergency"] = {
                "arrivals": emergency.filter(started_at__gte=start, started_at__lt=until).count(),
                "in_department": emergency.filter(
                    status__in=list(OPEN_ENCOUNTER_STATUSES),
                ).count(),
            }

        if entitlements.has_module("laboratory"):
            from apps.diagnostics.models import (
                AlertStatus,
                CriticalValueAlert,
                DiagnosticOrder,
                OrderStatus,
            )

            orders = DiagnosticOrder.objects.filter(**at)
            alerts = CriticalValueAlert.objects.filter(
                status__in=[AlertStatus.PENDING, AlertStatus.ESCALATED],
            )
            if facility is not None:
                alerts = alerts.filter(order__facility=facility)
            result["laboratory"] = {
                "outstanding": orders.filter(
                    status__in=[
                        OrderStatus.ORDERED,
                        OrderStatus.COLLECTED,
                        OrderStatus.RECEIVED,
                        OrderStatus.IN_PROGRESS,
                        OrderStatus.RESULTED,
                        OrderStatus.VERIFIED,
                    ],
                ).count(),
                "critical_open": alerts.count(),
                "released": orders.filter(released_at__gte=start, released_at__lt=until).count(),
            }

    if entitlements.has_module("hospital") and may("patient.clinical.read"):
        from apps.inpatient.models import Admission, Bed, BedStatus

        beds = Bed.objects.filter(is_active=True)
        admissions = Admission.objects.all()
        if facility is not None:
            beds = beds.filter(ward__facility=facility)
            admissions = admissions.filter(facility=facility)
        total = beds.count()
        occupied = beds.filter(status=BedStatus.OCCUPIED).count()
        result["inpatients"] = {
            "occupied": occupied,
            "beds": total,
            "occupancy_percent": round(occupied * 100 / total, 1) if total else None,
            "admitted": admissions.filter(admitted_at__gte=start, admitted_at__lt=until).count(),
            "discharged": admissions.filter(discharged_at__gte=start, discharged_at__lt=until).count(),
        }

    if may("invoice.read"):
        from apps.billing.models import Invoice, InvoiceStatus, Payment, PaymentStatus

        collected = Payment.objects.filter(
            status=PaymentStatus.COMPLETED, received_at__gte=start, received_at__lt=until, **at,
        ).aggregate(total=Sum("amount"))["total"]
        # Credit notes are issued invoices with negative totals, not debts, and
        # an overpaid invoice owes nothing rather than a negative amount.
        open_invoices = Invoice.objects.filter(
            status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID],
            is_credit_note=False,
            **at,
        )
        money = DecimalField(max_digits=14, decimal_places=2)
        owed = open_invoices.aggregate(
            total=Sum(
                Greatest(
                    ExpressionWrapper(F("total") - F("amount_paid"), output_field=money),
                    Value(Decimal("0"), output_field=money),
                ),
            ),
        )["total"]
        result["billing"] = {
            "collected": _money(collected),
            "outstanding": _money(owed),
            "overdue_invoices": open_invoices.filter(due_date__lt=day).count(),
        }

    if entitlements.has_module("pharmacy") and may("sale.read"):
        from apps.pos.models import Sale, SaleStatus

        sales = Sale.objects.filter(
            status__in=[SaleStatus.COMPLETED, SaleStatus.PARTIALLY_RETURNED],
            sold_at__gte=start, sold_at__lt=until,
            **at,
        )
        result["pharmacy"] = {
            "takings": _money(sales.aggregate(total=Sum("total"))["total"]),
            "sales": sales.count(),
        }

    return result


def organization_today(authorization, entitlements, facility=None, now=None) -> dict:
    """Today so far, and yesterday to compare it with.

    `facility` narrows every block to one building; `None` is the whole
    organization. `authorization` answers `has(code, scope)` and
    `entitlements` answers `has_module(code)`.
    """
    from apps.organization.models import DailySnapshot

    now = now or timezone.now()
    today = timezone.localdate(now)
    start = _day_start(today)

    result: dict = {
        "as_of": now.isoformat(),
        "facility": facility.name if facility is not None else None,
    }
    result.update(figures(authorization, entitlements, facility, start, now))

    # Events: yesterday up to this time of day, counted from the records.
    previous = figures(
        authorization, entitlements, facility,
        _day_start(today - timedelta(days=1)), now - timedelta(days=1),
    )
    for block, keys in POINT_IN_TIME.items():
        for key in keys:
            previous.get(block, {}).pop(key, None)

    # Levels: only from last night's snapshot, and only for blocks this viewer
    # was shown today -- a snapshot is taken with every figure in it.
    snapshot = DailySnapshot.objects.filter(
        date=today - timedelta(days=1), facility=facility,
    ).first()
    if snapshot is not None:
        for block, keys in POINT_IN_TIME.items():
            if block not in result or block not in (snapshot.figures or {}):
                continue
            for key in keys:
                if key in snapshot.figures[block]:
                    previous.setdefault(block, {})[key] = snapshot.figures[block][key]

    result["previous"] = {
        "label": "this time yesterday",
        "snapshot_date": snapshot.date.isoformat() if snapshot is not None else None,
        "blocks": previous,
    }
    return result


class _EveryFigure:
    """The nightly record is taken with every figure in it; what a viewer is
    shown from it is still decided by that viewer's own permissions."""

    def has(self, code, scope=None) -> bool:
        return True


def take_snapshot(entitlements, day=None) -> int:
    """Keep today's figures: the organization's, and each facility's.

    Idempotent per day and facility, so a second run -- a retry, a second
    scheduler -- replaces the record rather than adding one.
    """
    from apps.organization.models import DailySnapshot, Facility

    now = timezone.now()
    day = day or timezone.localdate(now)
    start = _day_start(day)
    until = min(start + timedelta(days=1), now)

    rows = 0
    for facility in [None, *Facility.objects.all()]:
        data = figures(_EveryFigure(), entitlements, facility, start, until)
        DailySnapshot.objects.update_or_create(
            date=day, facility=facility,
            defaults={"figures": data, "taken_at": now},
        )
        rows += 1
    return rows
