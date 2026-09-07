"""The reminder engine: everything that goes stale on a date.

§99. `sweeps.py` had the shape already -- one sweep, for professional
registrations, written with the note that "the next three are the same shape
against different tables". This is that generalisation, and it keeps every
argument the original made: dedupe by subject and band, resolve when the
situation stops being true, escalate by raising a *new* notification rather
than editing one somebody has already read.

Three things the engine adds.

**Bands are per subject, not global.** A blood unit expiring in three days is
urgent; an employment contract ending in three days is a catastrophe; a
quotation expiring in three days is a Tuesday. The original module had one set
of thresholds for everything, which is fine when there is one sweep and wrong
as soon as there are seven.

**Recipients are resolved from a permission, and an entry that resolves to
nobody is reported.** This is the important one. `notify` correctly treats "no
recipients" as a real answer rather than an error -- but a *sweep* that finds
forty expiring batches, tells nobody, and reports success is the most dangerous
kind of quiet: it looks exactly like a system that is watching. So the report
counts `undeliverable` separately, and it is a number somebody is meant to act
on by fixing a role assignment.

**Nothing here decides what a problem is.** Each entry names a queryset, a date
field and the permission whose holders should hear about it. The engine does
the banding, the keying, the resolution and the counting -- the same division
the report registry and the search sources keep, for the same reason: one place
that knows the mechanics, and no place that quietly reimplements the domain.
"""

from dataclasses import dataclass, field
from typing import Callable

from django.utils import timezone

from apps.notifications.models import NotificationCategory, Notification
from apps.notifications.services import notify, resolve_by_key
from apps.rbac.services import holders_of

#: Default escalation: expired, then a month out, then three months out.
#: Ordered widest last; the tightest band a subject falls into wins.
DEFAULT_BANDS = (
    (0, NotificationCategory.CRITICAL, "has expired"),
    (30, NotificationCategory.WARNING, "expires within a month"),
    (90, NotificationCategory.REMINDER, "expires within three months"),
)

#: For things with a short shelf life, where three months' notice is noise.
SHORT_BANDS = (
    (0, NotificationCategory.CRITICAL, "has expired"),
    (7, NotificationCategory.WARNING, "expires within a week"),
    (30, NotificationCategory.REMINDER, "expires within a month"),
)

#: For money, where "overdue" is the only band that means anything and the
#: warning is about to become a phone call.
DUE_BANDS = (
    (0, NotificationCategory.WARNING, "is overdue"),
    (7, NotificationCategory.REMINDER, "falls due within a week"),
)


@dataclass(frozen=True)
class Reminder:
    """One thing that goes stale, and who needs telling."""

    code: str
    #: What is going stale, in the words somebody would use.
    noun: str
    #: `() -> queryset`. A callable, not a queryset, because a queryset built
    #: at import time is bound to whatever tenant connection happened to be
    #: active then -- which in a database-per-tenant system is a bug that only
    #: shows up under load.
    subjects: Callable
    #: The attribute holding the date. Read with `getattr`, so a property works
    #: as well as a column.
    date_attr: str
    #: `(row) -> str`, the headline. The engine appends the band phrase.
    describe: Callable
    #: The permission whose holders should hear about it.
    permission: str
    #: `(row) -> facility or None`, so holders are resolved at the right site.
    facility_of: Callable = lambda row: getattr(row, "facility", None)
    #: `(row) -> uuid or None`, somebody personally responsible, told as well
    #: as the permission holders. A nurse hears about their own registration.
    owner_of: Callable = lambda row: None
    bands: tuple = DEFAULT_BANDS
    #: Where to go and deal with it.
    link: str = ""
    #: How far ahead to look at all.
    horizon_days: int = 90
    detail: Callable = lambda row: ""
    extra: dict = field(default_factory=dict)


_REMINDERS: dict = {}


def register(reminder: Reminder) -> Reminder:
    if reminder.code in _REMINDERS:
        raise ValueError(f"'{reminder.code}' is already a reminder")
    _REMINDERS[reminder.code] = reminder
    return reminder


def all_reminders() -> list:
    return sorted(_REMINDERS.values(), key=lambda r: r.code)


def _band(bands, days_left: int):
    """The tightest band this subject falls into, or `None`.

    Iterated tightest-first so a thing expiring tomorrow is `CRITICAL` rather
    than picking up the widest band that also happens to contain it.
    """
    if days_left < 0:
        return bands[0]
    for threshold, category, phrase in bands[1:]:
        if days_left <= threshold:
            return (threshold, category, phrase)
    return None


def run(reminder: Reminder) -> dict:
    """Run one reminder: raise, escalate, resolve, and count honestly.

    Safe to run as often as you like -- the dedupe key carries the subject and
    the band, so an hourly cron produces one notification per expiring thing per
    band, not twenty-four.
    """
    today = timezone.localdate()
    raised = standing = resolved = undeliverable = considered = 0
    seen_keys = set()

    for row in reminder.subjects():
        when = getattr(row, reminder.date_attr, None)
        if when is None:
            continue
        # Dates and datetimes both appear on these models. Comparing a date
        # against a datetime raises rather than filtering, which this project
        # has been bitten by before.
        if hasattr(when, "date"):
            when = timezone.localtime(when).date() if timezone.is_aware(when) \
                else when.date()

        days_left = (when - today).days
        if days_left > reminder.horizon_days:
            continue
        band = _band(reminder.bands, days_left)
        if band is None:
            continue
        considered += 1
        _threshold, category, phrase = band

        # The band is in the key, so crossing a threshold raises a new
        # notification rather than rewriting a sentence somebody has read.
        key = f"{reminder.code}:{row.uuid}:{category}"
        seen_keys.add(key)

        facility = reminder.facility_of(row)
        recipients = []
        owner_id = reminder.owner_of(row)
        if owner_id:
            recipients.append({
                "id": owner_id,
                "name": "",
                "reason": f"It is your {reminder.noun}",
            })
        recipients.extend(
            person
            for person in holders_of(reminder.permission, facility=facility)
            if person["id"] != owner_id
        )
        if not recipients:
            # Counted, not shrugged at. Forty expiring batches and nobody
            # holding `stock.adjust` is a role assignment somebody has to fix,
            # and a sweep that reports success in that state is worse than one
            # that does nothing, because it looks like it is watching.
            undeliverable += 1
            continue

        timing = (
            f"{'expired' if days_left < 0 else 'due'} "
            f"{when:%d %b %Y}"
            if days_left < 0 else
            f"due {when:%d %b %Y}, in {days_left} "
            f"day{'' if days_left == 1 else 's'}"
        )

        # Asked before the call: `notify` returns the *existing* notification
        # on a dedupe hit and there is no way to tell that from its return
        # value. A sweep reporting "raised 40" every hour when nothing changed
        # is a number that teaches people to stop reading the report.
        already_open = Notification.objects.filter(
            dedupe_key=key, resolved_at__isnull=True,
        ).exists()

        result = notify(
            source="reminders",
            event=reminder.code,
            category=category,
            title=f"{reminder.describe(row)} {phrase}",
            body=" · ".join(filter(None, [reminder.detail(row), timing])),
            link=reminder.link,
            recipients=recipients,
            subject_type=reminder.extra.get("subject_type", ""),
            subject_uuid=row.uuid,
            facility=facility,
            dedupe_key=key,
        )
        if result is not None:
            standing += 1 if already_open else 0
            raised += 0 if already_open else 1

    # Anything renewed, cancelled, sold or written off now has an open
    # notification about a situation that has stopped being true. A reminder
    # that outlives its cause is how people learn to ignore reminders.
    stale = Notification.objects.filter(
        source="reminders", event=reminder.code, resolved_at__isnull=True,
    ).exclude(dedupe_key__in=seen_keys)
    for notification in stale:
        resolve_by_key(notification.dedupe_key, reason="No longer due")
        resolved += 1

    return {
        "reminder": reminder.code,
        "considered": considered,
        "raised": raised,
        "standing": standing,
        "resolved": resolved,
        # Deliberately last and deliberately named. This is the number that
        # means the reminder is running and reaching nobody.
        "undeliverable": undeliverable,
    }


def run_all() -> dict:
    """Every registered reminder, with a report per entry.

    A failing reminder is reported and the rest still run -- the same argument
    as the workspace: one module being unwell must not make the whole system
    look quiet.
    """
    import logging

    logger = logging.getLogger("nirova.reminders")
    reports, broken = [], []
    for reminder in all_reminders():
        try:
            reports.append(run(reminder))
        except Exception:                                      # noqa: BLE001
            logger.exception("reminder %s failed", reminder.code)
            broken.append(reminder.code)
    return {
        "reminders": reports,
        "broken": broken,
        "raised": sum(report["raised"] for report in reports),
        "resolved": sum(report["resolved"] for report in reports),
        "undeliverable": sum(report["undeliverable"] for report in reports),
    }


def load() -> None:
    """Register every reminder. Called once from the app's `ready()`."""
    if _REMINDERS:
        return

    def contracts():
        from apps.hr.models import EmploymentContract

        return EmploymentContract.objects.filter(
            status="active", ends_on__isnull=False,
        ).select_related("employee", "employee__facility")

    def probations():
        from apps.hr.models import Employee, EmployeeStatus

        return Employee.objects.filter(
            status=EmployeeStatus.ACTIVE, probation_ends_on__isnull=False,
        ).select_related("facility")

    def batches():
        from apps.pharmacy.models import Batch

        # Only stock that is still sellable. A batch already quarantined or
        # recalled is somebody's open problem, not a new reminder.
        return Batch.objects.filter(
            status="active", expires_on__isnull=False,
        ).select_related("product")

    def blood_units():
        from apps.bloodbank.models import BloodUnit

        return BloodUnit.objects.filter(
            status="available", expires_on__isnull=False,
        ).select_related("facility")

    def unpaid_invoices():
        from apps.billing.models import Invoice

        return Invoice.objects.filter(
            status__in=["issued", "partially_paid"], due_date__isnull=False,
        ).select_related("patient", "facility")

    def supplier_invoices():
        from apps.finance.models import SupplierInvoice

        return SupplierInvoice.objects.filter(
            status__in=["approved", "partially_paid"], due_date__isnull=False,
        ).select_related("facility")

    def supplier_licences():
        from apps.procurement.models import Supplier, SupplierStatus

        # Only suppliers anybody would order from. Chasing a blacklisted
        # vendor's paperwork is noise on somebody's list.
        return Supplier.objects.filter(
            status=SupplierStatus.ACTIVE,
            drug_licence_expires_on__isnull=False,
        )

    def facility_licences():
        from apps.organization.models import Facility

        return Facility.objects.filter(
            status="active", license_expires_on__isnull=False,
        )

    def preauthorisations():
        from apps.insurance.models import PreAuthorisation, PreAuthStatus

        # Both states, not just `approved`. A pre-authorisation approved for
        # less than was asked is still a live promise with an expiry date on
        # it, and filtering to `approved` alone matched nothing at all here --
        # every pre-auth in the tenant is `partially_approved`. A reminder that
        # silently considers zero rows looks exactly like a reminder with
        # nothing to say.
        return PreAuthorisation.objects.filter(
            status__in=[PreAuthStatus.APPROVED,
                        PreAuthStatus.PARTIALLY_APPROVED],
            valid_until__isnull=False,
        ).select_related("patient", "facility")

    for reminder in [
        Reminder(
            code="contract_ending", noun="contract",
            subjects=contracts, date_attr="ends_on",
            describe=lambda row: f"{row.employee.full_name}: contract",
            detail=lambda row: row.reference or "",
            permission="employee.manage",
            facility_of=lambda row: row.employee.facility,
            owner_of=lambda row: row.employee.user_id,
            link="/people",
            extra={"subject_type": "hr.EmploymentContract"},
        ),
        Reminder(
            code="probation_ending", noun="probation",
            subjects=probations, date_attr="probation_ends_on",
            describe=lambda row: f"{row.full_name}: probation",
            detail=lambda row: row.position.title if row.position_id else "",
            permission="employee.manage",
            owner_of=lambda row: row.user_id,
            bands=SHORT_BANDS, horizon_days=30,
            link="/people",
            extra={"subject_type": "hr.Employee"},
        ),
        Reminder(
            code="batch_expiring", noun="batch",
            subjects=batches, date_attr="expires_on",
            describe=lambda row: (
                f"{row.product.brand_name or row.product.generic_name}"
                f" batch {row.batch_number}"
            ),
            detail=lambda row: row.product.code,
            permission="stock.adjust",
            # A batch belongs to a location rather than a facility, so holders
            # are resolved organization-wide. Narrowing it wrongly is worse
            # than not narrowing it: the reminder would reach nobody.
            facility_of=lambda row: None,
            link="/pharmacy",
            extra={"subject_type": "pharmacy.Batch"},
        ),
        Reminder(
            code="blood_expiring", noun="blood unit",
            subjects=blood_units, date_attr="expires_on",
            describe=lambda row: (
                f"{row.blood_group} {row.component} unit {row.unit_number}"
            ),
            detail=lambda row: row.storage_location or "",
            permission="stock.adjust",
            # Short bands: a unit with three months left is not news, and a
            # unit with three days left is scarce, expensive and about to be
            # thrown away.
            bands=SHORT_BANDS, horizon_days=30,
            link="/blood",
            extra={"subject_type": "bloodbank.BloodUnit"},
        ),
        Reminder(
            code="invoice_overdue", noun="invoice",
            subjects=unpaid_invoices, date_attr="due_date",
            describe=lambda row: f"Invoice {row.number}",
            detail=lambda row: " · ".join(filter(None, [
                row.patient.full_name if row.patient_id else "Counter sale",
                f"NPR {row.total - row.amount_paid} outstanding",
            ])),
            permission="payment.record",
            bands=DUE_BANDS, horizon_days=7,
            link="/billing",
            extra={"subject_type": "billing.Invoice"},
        ),
        Reminder(
            code="supplier_invoice_due", noun="supplier invoice",
            subjects=supplier_invoices, date_attr="due_date",
            describe=lambda row: f"Supplier invoice {row.reference}",
            detail=lambda row: " · ".join(filter(None, [
                row.supplier_name,
                f"NPR {row.total - row.paid_amount} outstanding",
            ])),
            permission="payment.record",
            bands=DUE_BANDS, horizon_days=7,
            link="/procurement",
            extra={"subject_type": "finance.SupplierInvoice"},
        ),
        Reminder(
            code="supplier_licence_expiring", noun="drug licence",
            subjects=supplier_licences, date_attr="drug_licence_expires_on",
            describe=lambda row: f"{row.name}: drug licence",
            detail=lambda row: " - ".join(filter(None, [
                row.drug_licence_number, row.contact_person, row.phone,
            ])),
            permission="supplier.manage",
            # A supplier belongs to no facility, so holders are resolved
            # organization-wide. Narrowing it wrongly would be worse than not
            # narrowing it: the reminder would reach nobody.
            facility_of=lambda row: None,
            link="/procurement",
            extra={"subject_type": "procurement.Supplier"},
        ),
        Reminder(
            code="facility_licence_expiring", noun="operating licence",
            subjects=facility_licences, date_attr="license_expires_on",
            describe=lambda row: f"{row.name}: operating licence",
            detail=lambda row: row.code,
            permission="facility.approve_change",
            facility_of=lambda row: row,
            # A hospital operating without a current licence is not a
            # paperwork problem, so this one starts warning six months out
            # rather than three.
            horizon_days=180,
            bands=(
                (0, NotificationCategory.CRITICAL, "has expired"),
                (30, NotificationCategory.CRITICAL, "expires within a month"),
                (90, NotificationCategory.WARNING, "expires within three months"),
                (180, NotificationCategory.REMINDER, "expires within six months"),
            ),
            link="/facilities",
            extra={"subject_type": "organization.Facility"},
        ),
        Reminder(
            code="preauth_expiring", noun="pre-authorisation",
            subjects=preauthorisations, date_attr="valid_until",
            describe=lambda row: f"Pre-authorisation {row.reference}",
            detail=lambda row: " · ".join(filter(None, [
                row.patient.full_name if row.patient_id else "",
                row.planned_treatment,
            ])),
            permission="invoice.create",
            # A pre-authorisation that lapses before the admission means the
            # patient pays or the procedure moves, so a week's notice is the
            # useful signal and three months is noise.
            bands=SHORT_BANDS, horizon_days=30,
            link="/claims",
            extra={"subject_type": "insurance.PreAuthorisation"},
        ),
    ]:
        register(reminder)
