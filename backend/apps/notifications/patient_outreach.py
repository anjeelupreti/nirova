"""Telling the patient, in their language, without telling their phone too much.

The hospital reaches its staff now (`delivery.py`). The patient — who owns the
appointment, the result and the bill — still hears nothing unless they open
the app. A clinic in Nepal loses a fifth of its outpatient slots to people who
simply forgot, and the fix is a text the evening before.

Four rules, and they are the reason this is a module rather than a `send_sms`
call in a view.

**Consent is per channel and already recorded.** `Patient.consent_sms` and
`consent_email` exist and have never been read by anything. A patient who said
no is not messaged, and that refusal is recorded as the reason rather than
looking like a failure.

**A text message is read by whoever is holding the phone.** So a reminder
names the hospital and the time; a result message says a result is ready and
where to see it. Neither carries a value, a test name, a diagnosis or a
department that gives away why somebody attended. This is the difference
between a service and a disclosure.

**In the patient's language.** `preferred_language` defaults to `ne`, which is
the honest default here, and the Nepali is written as Nepali rather than
translated word for word from the English.

**"Tomorrow", not a date.** The console converts dates to Bikram Sambat with a
maintained library; the server has no such table and this codebase refuses to
hand-type one — a wrong month in a hospital message is a missed appointment.
A reminder sent the evening before does not need a calendar at all: "tomorrow
at 11:15" is unambiguous in every calendar anybody reads.
"""

import logging

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.patients.models import Patient

logger = logging.getLogger("nirova.notifications")


class OutreachKind(models.TextChoices):
    APPOINTMENT = "appointment", "Appointment reminder"
    RESULT_READY = "result_ready", "Result ready"
    BILL_DUE = "bill_due", "Bill outstanding"


class OutreachStatus(models.TextChoices):
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    UNREACHABLE = "unreachable", "No way to reach them"
    DECLINED = "declined", "The patient asked not to be contacted"


class PatientMessage(BaseModel):
    """One message to one patient, and what became of it.

    Kept because a hospital is asked "did anybody tell her?" and the answer
    has to be better than "the system usually does". The body is stored as
    sent: a reminder somebody disputes is a reminder somebody has to be able
    to read back.
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="messages",
    )
    kind = models.CharField(max_length=24, choices=OutreachKind.choices)
    channel = models.CharField(max_length=16)
    address = models.CharField(max_length=255, blank=True)
    language = models.CharField(max_length=8, default="ne")
    body = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=OutreachStatus.choices)
    detail = models.CharField(max_length=512, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    #: What this message is about — an appointment reference, an order
    #: reference. Unique, so a sweep that runs twice tells somebody once.
    dedupe_key = models.CharField(max_length=128, db_index=True)

    class Meta:
        db_table = "patient_message"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_patient_message_key",
            ),
        ]
        indexes = [models.Index(fields=["patient", "-created_at"])]

    def __str__(self):
        return f"{self.kind} → {self.address} ({self.status})"


# ---------------------------------------------------------------------------
# What to say
# ---------------------------------------------------------------------------

def _hospital_name() -> str:
    from apps.organization.models import Facility

    facility = Facility.objects.order_by("id").first()
    return facility.organization_name if hasattr(facility, "organization_name") else (
        facility.name if facility else "the hospital"
    )


#: The part of the day a Nepali speaker names before a time. "११ बजे" alone
#: is ambiguous in a way "11:00" is not, and the patient app already makes the
#: same distinction on its appointment chips.
def _part_of_day(hour: int) -> str:
    if hour < 12:
        return "बिहान"
    if hour < 16:
        return "दिउँसो"
    if hour < 19:
        return "साँझ"
    return "राति"


def appointment_text(appointment, language: str) -> str:
    """The evening-before reminder. No department, no reason, no diagnosis.

    The clock stays in 0–9 even in Nepali. Devanagari digits are right on a
    screen the hospital controls and wrong in a text message: it is read on
    whatever handset the patient owns, and a feature phone that cannot render
    the script shows boxes where the time should be.
    """
    local = timezone.localtime(appointment.scheduled_for)
    when = local.strftime("%H:%M")
    place = appointment.facility.name
    if language == "ne":
        return (
            f"सम्झना: भोलि {_part_of_day(local.hour)} {when} बजे {place} मा "
            f"तपाईंको भेटघाट छ। आउन नसक्ने भए फोन गरेर जानकारी दिनुहोला।"
        )
    return (
        f"Reminder: you have an appointment at {place} tomorrow at {when}. "
        f"Please call us if you cannot come."
    )


def result_text(language: str, place: str) -> str:
    """A result is ready — and nothing about what it says.

    Deliberately free of the test name. "Your HIV result is ready" read off a
    lock screen by somebody else is a disclosure the hospital made.
    """
    if language == "ne":
        return (
            f"{place}: तपाईंको जाँचको नतिजा तयार भयो। "
            f"एपमा हेर्न सक्नुहुन्छ वा रिसेप्सनमा सम्पर्क गर्नुहोस्।"
        )
    return (
        f"{place}: your test result is ready. You can see it in the app, or "
        f"ask at reception."
    )


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_to_patient(patient: Patient, kind: str, body_by_language: dict,
                    dedupe_key: str) -> PatientMessage | None:
    """Send one message, once, on a channel the patient agreed to.

    Returns the row, or `None` when one already exists for this key — which
    is how a sweep that runs twice, or a task that retries, tells somebody
    once.
    """
    from apps.notifications.delivery import send_email, send_sms

    if PatientMessage.objects.filter(dedupe_key=dedupe_key).exists():
        return None

    language = (patient.preferred_language or "ne").lower()[:2]
    body = body_by_language.get(language) or body_by_language.get("en") or ""

    channel, address = "", ""
    if patient.phone and patient.consent_sms:
        channel, address = "sms", patient.phone
    elif patient.email and patient.consent_email:
        channel, address = "email", patient.email

    row = PatientMessage(
        patient=patient, kind=kind, channel=channel or "none",
        address=address, language=language, body=body, dedupe_key=dedupe_key,
    )

    if not channel:
        # Two different facts, and the patient's own decision is not a
        # failure of ours: said no, or never gave us a number.
        refused = (patient.phone and not patient.consent_sms) or (
            patient.email and not patient.consent_email
        )
        row.status = OutreachStatus.DECLINED if refused else OutreachStatus.UNREACHABLE
        row.detail = (
            "The patient has not agreed to be contacted on any channel we have."
            if refused else "No phone number or email address on the record."
        )
        row.save()
        return row

    if channel == "sms":
        sent, detail = send_sms(address, body)
    else:
        sent, detail = send_email(address, body.split(".")[0][:120], body)

    row.status = OutreachStatus.SENT if sent else (
        OutreachStatus.UNREACHABLE if "configured" in detail else OutreachStatus.FAILED
    )
    row.detail = (detail or "")[:512]
    row.sent_at = timezone.now() if sent else None
    row.save()
    return row


def remind_tomorrows_appointments(now=None) -> dict:
    """The evening-before sweep. One message per appointment, ever."""
    from datetime import timedelta

    from apps.scheduling.models import OCCUPIES_SLOT, Appointment

    now = now or timezone.localtime()
    tomorrow = (now + timedelta(days=1)).date()
    counts = {"sent": 0, "declined": 0, "unreachable": 0, "failed": 0, "already": 0}

    appointments = (
        Appointment.objects.filter(
            scheduled_for__date=tomorrow, status__in=list(OCCUPIES_SLOT),
        )
        .select_related("patient", "facility")
    )
    for appointment in appointments:
        patient = appointment.patient
        if patient is None:
            continue
        row = send_to_patient(
            patient, OutreachKind.APPOINTMENT,
            {
                "ne": appointment_text(appointment, "ne"),
                "en": appointment_text(appointment, "en"),
            },
            dedupe_key=f"appointment:{appointment.reference}",
        )
        if row is None:
            counts["already"] += 1
        else:
            counts[row.status if row.status in counts else "failed"] += 1
    return counts


def tell_patient_result_ready(order) -> PatientMessage | None:
    """Told that a result exists, never what it says."""
    patient = getattr(order, "patient", None)
    if patient is None:
        return None
    place = order.facility.name if getattr(order, "facility_id", None) else _hospital_name()
    return send_to_patient(
        patient, OutreachKind.RESULT_READY,
        {"ne": result_text("ne", place), "en": result_text("en", place)},
        dedupe_key=f"result:{order.reference}",
    )
