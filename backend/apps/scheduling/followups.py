"""Follow-ups: the loop this system opened and never closed.

A follow-up date is written twice a day in this product -- on a consultation
("review in two weeks") and on a discharge -- and **nothing has ever looked at
one afterwards**. No list of who is due, no chase for who did not come, no
report of what lapsed. The clinician does their part, the date is stored, and
then the patient either remembers or does not.

**Status is derived, never stored.** A follow-up is *booked* when the patient
has an appointment on or around the date, *attended* when they have actually
been seen since, *due* when the date is ahead, and *overdue* when it has
passed and neither of the first two is true. Storing a status would mean
updating it from four places -- booking, attending, cancelling, rescheduling --
and the day one of those forgets, a patient who came back is chased anyway.

**A recall says nothing clinical.** The message is that a follow-up visit is
due and the hospital would like them to call; the reason they are coming back
is in the record, not in a text message somebody else may read. Same rule as
every other message to a patient (`apps/notifications/patient_outreach.py`),
and the same consent and deduplication.
"""

from datetime import timedelta

from django.utils import timezone

#: How far ahead "due" reaches, and how far back a lapse is still worth chasing.
AHEAD_DAYS = 14
BEHIND_DAYS = 90
#: Coming a few days early still counts as coming.
GRACE_DAYS = 3


def _rows(facility, start, end):
    """Every follow-up somebody wrote, from both places they are written."""
    from apps.encounters.models import Encounter
    from apps.inpatient.models import Admission

    at = {"facility": facility} if facility is not None else {}

    encounters = (
        Encounter.objects.filter(
            follow_up_date__isnull=False, follow_up_date__gte=start, follow_up_date__lte=end, **at,
        )
        .select_related("patient")
    )
    admissions = (
        Admission.objects.filter(
            follow_up_on__isnull=False, follow_up_on__gte=start, follow_up_on__lte=end, **at,
        )
        .select_related("patient")
    )

    for encounter in encounters:
        yield {
            "patient_uuid": str(encounter.patient.uuid),
            "patient_id": encounter.patient_id,
            "patient": encounter.patient.full_name,
            "mrn": encounter.patient.mrn,
            "phone": encounter.patient.phone,
            "due_on": encounter.follow_up_date,
            "source": "consultation",
            "reference": encounter.reference,
            "instructions": encounter.follow_up_instructions,
            "clinician": encounter.provider_name,
        }
    for admission in admissions:
        yield {
            "patient_uuid": str(admission.patient.uuid),
            "patient_id": admission.patient_id,
            "patient": admission.patient.full_name,
            "mrn": admission.patient.mrn,
            "phone": admission.patient.phone,
            "due_on": admission.follow_up_on,
            "source": "discharge",
            "reference": admission.reference,
            "instructions": admission.discharge_advice[:200],
            "clinician": admission.consultant_name,
        }


def register(facility=None, ahead: int = AHEAD_DAYS, behind: int = BEHIND_DAYS, today=None) -> dict:
    """Who is due back, who did not come, and who already has."""
    from apps.encounters.models import Encounter
    from apps.scheduling.models import OCCUPIES_SLOT, Appointment

    today = today or timezone.localdate()
    start, end = today - timedelta(days=behind), today + timedelta(days=ahead)
    rows = list(_rows(facility, start, end))
    patient_ids = {row["patient_id"] for row in rows}

    # Two bulk reads rather than two per row: a busy month is a few hundred
    # follow-ups, and this list is opened at the front desk all day.
    booked: dict = {}
    for appointment in Appointment.objects.filter(
        patient_id__in=patient_ids,
        status__in=list(OCCUPIES_SLOT),
        scheduled_for__date__gte=start - timedelta(days=GRACE_DAYS),
    ).values("patient_id", "scheduled_for"):
        seen = booked.setdefault(appointment["patient_id"], [])
        seen.append(timezone.localtime(appointment["scheduled_for"]).date())

    attended: dict = {}
    for encounter in Encounter.objects.filter(
        patient_id__in=patient_ids,
        started_at__date__gte=start - timedelta(days=GRACE_DAYS),
    ).values("patient_id", "started_at", "reference"):
        seen = attended.setdefault(encounter["patient_id"], [])
        seen.append((timezone.localtime(encounter["started_at"]).date(), encounter["reference"]))

    counts = {"due": 0, "overdue": 0, "booked": 0, "attended": 0}
    out = []
    for row in rows:
        due_on = row["due_on"]
        came = any(
            when >= due_on - timedelta(days=GRACE_DAYS) and reference != row["reference"]
            for when, reference in attended.get(row["patient_id"], [])
        )
        has_appointment = any(
            when >= due_on - timedelta(days=GRACE_DAYS)
            for when in booked.get(row["patient_id"], [])
        )
        if came:
            status = "attended"
        elif has_appointment:
            status = "booked"
        elif due_on < today:
            status = "overdue"
        else:
            status = "due"
        counts[status] += 1
        out.append({
            **{key: value for key, value in row.items() if key != "patient_id"},
            "due_on": due_on.isoformat(),
            "status": status,
            "days_overdue": (today - due_on).days if status == "overdue" else 0,
        })

    out.sort(key=lambda row: (row["status"] != "overdue", row["due_on"]))
    return {
        "as_of": today.isoformat(),
        "facility": getattr(facility, "name", None),
        "counts": counts,
        "results": out,
    }


def recall(patient, due_on, reference: str, overdue: bool = False):
    """Ask one patient to come back. Says nothing about why."""
    from apps.notifications.patient_outreach import OutreachKind, send_to_patient

    english = (
        "Namaste. Your follow-up visit is overdue. Please call us to arrange a time."
        if overdue
        else "Namaste. Your follow-up visit is due soon. Please call us to arrange a time."
    )
    nepali = (
        "नमस्ते। तपाईंको फलोअप जाँचको समय नाघिसक्यो। कृपया समय मिलाउन हामीलाई फोन गर्नुहोस्।"
        if overdue
        else "नमस्ते। तपाईंको फलोअप जाँचको समय नजिकिँदै छ। कृपया समय मिलाउन हामीलाई फोन गर्नुहोस्।"
    )
    return send_to_patient(
        patient,
        OutreachKind.FOLLOW_UP,
        {"en": english, "ne": nepali},
        dedupe_key=f"followup:{reference}:{due_on}",
    )


def recall_due(now=None) -> dict:
    """The evening-before sweep for tomorrow's follow-ups, and last week's lapses.

    One message per follow-up, ever: the dedupe key is the source reference
    and its date, so a patient whose review was booked and missed is asked
    once, not every night until they come.
    """
    from apps.patients.models import Patient

    now = now or timezone.localtime()
    today = now.date()
    counts = {"reminded": 0, "chased": 0, "skipped": 0}

    listing = register(today=today)
    for row in listing["results"]:
        due_on = row["due_on"]
        if row["status"] == "due" and due_on == (today + timedelta(days=1)).isoformat():
            overdue = False
        elif row["status"] == "overdue" and 1 <= row["days_overdue"] <= 7:
            overdue = True
        else:
            continue
        patient = Patient.objects.filter(uuid=row["patient_uuid"]).first()
        if patient is None:
            continue
        sent = recall(patient, due_on, row["reference"], overdue=overdue)
        if sent is None:
            counts["skipped"] += 1
        elif overdue:
            counts["chased"] += 1
        else:
            counts["reminded"] += 1
    return counts


def lapsed_report(since=None, facility=None) -> dict:
    """Follow-ups that passed with nothing booked and nobody seen.

    The report a medical director asks for once and then asks for monthly:
    it is the clearest measure of whether the hospital's own advice is
    followed, and until now nothing in the product could answer it.
    """
    today = timezone.localdate()
    behind = (today - (since if hasattr(since, "year") else today - timedelta(days=BEHIND_DAYS))).days
    listing = register(facility=facility, ahead=0, behind=max(behind, 1), today=today)
    lapsed = [row for row in listing["results"] if row["status"] == "overdue"]
    total = listing["counts"]["overdue"] + listing["counts"]["attended"] + listing["counts"]["booked"]
    return {
        "as_of": listing["as_of"],
        "facility": listing["facility"],
        "lapsed": len(lapsed),
        "kept_or_booked": listing["counts"]["attended"] + listing["counts"]["booked"],
        "kept_percent": round(
            (listing["counts"]["attended"] + listing["counts"]["booked"]) * 100 / total, 1,
        ) if total else None,
        "rows": lapsed,
    }
