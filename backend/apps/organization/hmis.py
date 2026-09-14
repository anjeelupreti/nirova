"""The monthly return, from the records rather than from a notebook.

Every hospital and clinic in Nepal files a monthly return to the ministry.
Today they do it by counting: a clerk with the outpatient register, a
calculator, and an evening. The numbers are in this system already -- who
attended, how old they were, what they were diagnosed with, who was admitted
and how their stay ended -- and nothing assembled them.

**This assembles what the records actually support, and says what they do
not.** Three rules:

1. **Nothing is inferred.** A count here is a count of rows somebody wrote
   during care. Where the system has no record of something the return asks
   for -- immunisation, family planning, nutrition programmes, the TB and HIV
   registers -- it appears in `not_collected` with the reason, rather than as
   a zero. A zero filed to a ministry is a claim that nothing happened.
2. **Age is age at the visit**, not age today. A return filed in Poush about
   Mangsir must band a child by how old they were then.
3. **New means new to this hospital**, decided by whether the patient had any
   earlier encounter, not by a flag somebody remembered to tick.

The clerk still reads it, checks it and signs it. This removes the counting,
not the responsibility.
"""

from datetime import date, timedelta

from django.db.models import Count, Min
from django.utils import timezone

#: The bands the ministry's forms use.
AGE_BANDS = (
    ("<1", 0, 1),
    ("1-4", 1, 5),
    ("5-14", 5, 15),
    ("15-19", 15, 20),
    ("20-59", 20, 60),
    ("60+", 60, 200),
)

#: Institutional delivery, by the codes a delivery is recorded under.
DELIVERY_CODES = ("O80", "O82", "O60.1", "O42.9")

#: What the ministry asks for that this system does not record at all. Listed
#: rather than silently omitted: a form with a blank section is a question
#: somebody has to answer, and a wrong zero is worse than a blank.
NOT_COLLECTED = (
    ("Immunisation", "No immunisation register: vaccines are stock items, not doses against a child."),
    ("Family planning", "No family planning register: methods, clients and follow-up are not recorded."),
    ("Nutrition", "No growth monitoring or supplementation records."),
    ("TB and HIV programme", "Cases are diagnosed and coded, but the programme registers (DOTS, ART) are not kept here."),
    ("Community and outreach", "Only what happened in the facility is recorded."),
)


def _band(born, on) -> str:
    if born is None:
        return "unknown"
    years = on.year - born.year - ((on.month, on.day) < (born.month, born.day))
    for label, low, high in AGE_BANDS:
        if low <= years < high:
            return label
    return "60+"


def _period(since, until):
    today = timezone.localdate()
    if since is None:
        since = today.replace(day=1)
    elif isinstance(since, str):
        since = date.fromisoformat(since)
    if until is None:
        until = today
    elif isinstance(until, str):
        until = date.fromisoformat(until)
    return since, until + timedelta(days=1)


def monthly_return(since=None, until=None, facility=None) -> dict:
    """The month's figures, as the ministry's sections.

    `since`/`until` are dates; the default is this month so far. `facility`
    narrows to one building, which is how the return is filed.
    """
    from apps.encounters.models import Diagnosis, Encounter, EncounterType
    from apps.inpatient.models import Admission, AdmissionStatus
    from apps.diagnostics.models import DiagnosticOrder
    from apps.referrals.models import Referral

    start, end = _period(since, until)
    at = {"facility": facility} if facility is not None else {}

    encounters = (
        Encounter.objects.filter(started_at__date__gte=start, started_at__date__lt=end, **at)
        .select_related("patient", "department")
    )

    # New to this hospital: no encounter before this period. One query for
    # every patient seen, rather than one per encounter.
    patient_ids = {row.patient_id for row in encounters}
    first_seen = dict(
        Encounter.objects.filter(patient_id__in=patient_ids)
        .values("patient_id")
        .annotate(first=Min("started_at"))
        .values_list("patient_id", "first")
    )

    attendance: dict = {}
    by_department: dict = {}
    emergency = 0
    for encounter in encounters:
        on = timezone.localtime(encounter.started_at).date()
        band = _band(encounter.patient.date_of_birth, on)
        sex = (encounter.patient.gender or "unknown").lower()
        earliest = first_seen.get(encounter.patient_id)
        is_new = earliest is not None and timezone.localtime(earliest).date() >= start

        row = attendance.setdefault((band, sex), {"age_band": band, "sex": sex, "new": 0, "repeat": 0})
        row["new" if is_new else "repeat"] += 1

        if encounter.encounter_type == EncounterType.EMERGENCY:
            emergency += 1
        name = encounter.department.name if encounter.department_id else "Not recorded"
        by_department[name] = by_department.get(name, 0) + 1

    attendance_rows = sorted(
        ({**row, "total": row["new"] + row["repeat"]} for row in attendance.values()),
        key=lambda row: ([band for band, *_ in AGE_BANDS].index(row["age_band"])
                         if row["age_band"] in [band for band, *_ in AGE_BANDS] else 99, row["sex"]),
    )

    diagnoses = Diagnosis.objects.filter(created_at__date__gte=start, created_at__date__lt=end)
    if facility is not None:
        diagnoses = diagnoses.filter(encounter__facility=facility)
    morbidity = list(
        diagnoses.exclude(icd10_code="")
        .values("icd10_code", "name")
        .annotate(count=Count("id"))
        .order_by("-count")[:20]
    )
    uncoded = diagnoses.filter(icd10_code="").count()
    coded = diagnoses.exclude(icd10_code="").count()

    admissions = Admission.objects.filter(**at) if facility is not None else Admission.objects.all()
    admitted = admissions.filter(admitted_at__date__gte=start, admitted_at__date__lt=end)
    left = admissions.filter(discharged_at__date__gte=start, discharged_at__date__lt=end)
    nights = [row.length_of_stay_days for row in left if row.length_of_stay_days is not None]

    deliveries = diagnoses.filter(icd10_code__in=DELIVERY_CODES).count()

    inpatient_rows = [
        {"measure": "Admissions", "count": admitted.count()},
        {"measure": "Discharges", "count": left.filter(status=AdmissionStatus.DISCHARGED).count()},
        {"measure": "Deaths", "count": left.filter(status=AdmissionStatus.DIED).count()},
        {"measure": "Left against medical advice", "count": left.filter(status=AdmissionStatus.LAMA).count()},
        {"measure": "Absconded", "count": left.filter(status=AdmissionStatus.ABSCONDED).count()},
        {"measure": "Transferred to another hospital", "count": left.filter(status=AdmissionStatus.TRANSFERRED_OUT).count()},
        {"measure": "Institutional deliveries (by code)", "count": deliveries},
        {"measure": "Average length of stay (nights)", "count": round(sum(nights) / len(nights), 1) if nights else 0},
    ]

    orders = DiagnosticOrder.objects.filter(ordered_at__date__gte=start, ordered_at__date__lt=end, **at)
    diagnostics_rows = [
        {
            "modality": row["modality"],
            "ordered": row["count"],
        }
        for row in orders.values("modality").annotate(count=Count("id")).order_by("-count")
    ]

    referrals = Referral.objects.filter(created_at__date__gte=start, created_at__date__lt=end)
    referral_rows = [
        {"direction": row["direction"], "count": row["count"]}
        for row in referrals.values("direction").annotate(count=Count("id")).order_by("-count")
    ]

    total_visits = sum(row["total"] for row in attendance_rows)
    return {
        "since": str(start),
        "until": str(end - timedelta(days=1)),
        "facility": getattr(facility, "name", None),
        "total_visits": total_visits,
        "new_patients": sum(row["new"] for row in attendance_rows),
        "emergency_visits": emergency,
        "coded_percent": round(coded * 100 / (coded + uncoded), 1) if (coded + uncoded) else None,
        "uncoded_diagnoses": uncoded,
        "attendance": attendance_rows,
        "by_department": [
            {"department": name, "visits": count}
            for name, count in sorted(by_department.items(), key=lambda pair: -pair[1])
        ],
        "morbidity": [
            {"code": row["icd10_code"], "diagnosis": row["name"], "count": row["count"]}
            for row in morbidity
        ],
        "inpatient": inpatient_rows,
        "diagnostics": diagnostics_rows,
        "referrals": referral_rows,
        "not_collected": [{"section": section, "why": why} for section, why in NOT_COLLECTED],
    }
