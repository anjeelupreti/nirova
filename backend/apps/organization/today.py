"""The organization's day, in one answer.

**The owner's dashboard had no figures about the organization.** Its top band
counted the owner's own inbox -- approvals waiting, notifications unread --
which is what My day is for, and every panel below it read one department's
summary at one facility. Nothing said how many patients had been seen, how
full the beds were, or what had been collected and was still owed: the three
things somebody who runs a hospital asks first.

Each block is included only when the viewer may read what it counts **and**
the plan includes the module it belongs to. A block that is left out is
absent, never zero: "no inpatients" and "you may not see inpatients" are not
the same claim, and a dashboard that renders both as 0 lies to exactly the
person it is for.

Counts, not rows. Every figure is a door to a list that already exists and is
already authorised; this endpoint only says how many are behind each door.
"""

from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.rbac.permissions import Scope

_CENTS = Decimal("0.01")


def _money(value) -> str:
    return str((value or Decimal("0")).quantize(_CENTS))


def organization_today(authorization, entitlements, facility=None, now=None) -> dict:
    """What happened today, and what stands open now.

    `facility` narrows every block to one building; `None` is the whole
    organization. `authorization` answers `has(code, scope)` and
    `entitlements` answers `has_module(code)`, so both are easy to stand in for.
    """
    now = now or timezone.now()
    today = timezone.localdate(now)
    at = {"facility": facility} if facility is not None else {}

    def may(code: str, scope: str = Scope.FACILITY) -> bool:
        return authorization.has(code, scope)

    result: dict = {
        "as_of": now.isoformat(),
        "facility": facility.name if facility is not None else None,
    }

    if may("encounter.read", Scope.OWN):
        from apps.encounters.models import OPEN_ENCOUNTER_STATUSES, Encounter, EncounterType
        from apps.scheduling.models import Appointment, AppointmentStatus

        seen = Encounter.objects.filter(
            encounter_type=EncounterType.OUTPATIENT, started_at__date=today, **at,
        )
        booked = Appointment.objects.filter(scheduled_for__date=today, **at).exclude(
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
                "arrivals": emergency.filter(started_at__date=today).count(),
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
                "released": orders.filter(released_at__date=today).count(),
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
            "admitted": admissions.filter(admitted_at__date=today).count(),
            "discharged": admissions.filter(discharged_at__date=today).count(),
        }

    if may("invoice.read"):
        from apps.billing.models import Invoice, InvoiceStatus, Payment, PaymentStatus

        collected = Payment.objects.filter(
            status=PaymentStatus.COMPLETED, received_at__date=today, **at,
        ).aggregate(total=Sum("amount"))["total"]
        # Credit notes are issued invoices with negative totals. Summed in,
        # five of them made the demo hospital "owed -NPR 8,800" -- money it
        # owes nobody. They are not debts, so they are not counted; and an
        # overpaid invoice owes nothing rather than a negative amount.
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
            "overdue_invoices": open_invoices.filter(due_date__lt=today).count(),
        }

    if entitlements.has_module("pharmacy") and may("sale.read"):
        from apps.pos.models import Sale, SaleStatus

        sales = Sale.objects.filter(
            status__in=[SaleStatus.COMPLETED, SaleStatus.PARTIALLY_RETURNED],
            sold_at__date=today,
            **at,
        )
        result["pharmacy"] = {
            "takings": _money(sales.aggregate(total=Sum("total"))["total"]),
            "sales": sales.count(),
        }

    return result
