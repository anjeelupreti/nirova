"""The bed board: every ward at a facility, every bed, and who is in it.

**The screen a charge nurse runs a ward from, and it could not be built from
what the API offered.** The ward endpoint returned beds with an occupant's
name and admission reference and nothing else, so the board could say "301-A,
Kamala Adhikari" and not that she is seventy-two, on her fourth night, going
home today, and scoring 6 on NEWS2 at the ten o'clock round. Every one of
those is on the whiteboard of every ward in the world — the thing this screen
replaces — and without them the board was a list of names in boxes.

One request for the whole facility, because a nurse coming on shift opens the
board and wants the hospital at once, and a board that fetched each ward
separately drew itself one ward at a time.

**The access tiers hold here as everywhere else** (`docs/ACCESS_DESIGN.md`).
Who is in which bed is identity — anyone who may see the ward may see that,
and must, or they cannot find their patient. What they are in for and how sick
they are is clinical: the diagnosis and the NEWS2 score are included only for
a reader who holds `patient.clinical.read`, and, where the organization
requires a care relationship, only for patients that reader is treating. A
restricted bed says so rather than showing a blank that looks like "no
observations".
"""

from datetime import timedelta

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission, get_authorization, relationship_required
from apps.encounters.models import VitalSigns
from apps.inpatient.models import (
    AdmissionStatus,
    Bed,
    BedAssignment,
    BedStatus,
    Ward,
)
from apps.inpatient.nursing_services import calculate_news2
from apps.organization.models import Facility
from apps.rbac.permissions import Scope

#: Physical states in which a bed cannot take a patient for a reason other
#: than somebody being in it. Counted apart from "occupied", because a ward
#: with half its beds broken is a maintenance problem, not a full ward.
OUT_OF_SERVICE = {BedStatus.MAINTENANCE, BedStatus.BLOCKED}

#: NEWS2 older than this is shown as stale. Six hours is the longest routine
#: interval the RCP chart allows for a low score; beyond it the number is no
#: longer a statement about the patient now.
STALE_AFTER = timedelta(hours=6)


def _equipment(bed) -> list:
    return [
        label for flag, label in (
            (bed.has_oxygen, "oxygen"), (bed.has_suction, "suction"),
            (bed.has_monitor, "monitor"), (bed.has_ventilator, "ventilator"),
        ) if flag
    ]


def bed_board(facility, request) -> dict:
    now = timezone.now()
    today = timezone.localdate()

    authorization = get_authorization(request)
    clinical = bool(authorization and authorization.has("patient.clinical.read", Scope.OWN))
    per_patient = clinical and relationship_required(facility)

    wards = list(
        Ward.objects.filter(facility=facility, is_active=True)
        .prefetch_related(
            Prefetch(
                "beds",
                queryset=Bed.objects.filter(is_active=True).order_by("code").prefetch_related(
                    Prefetch(
                        "assignments",
                        queryset=BedAssignment.objects.filter(vacated_at__isnull=True)
                        .select_related("admission", "admission__patient"),
                        to_attr="open_assignments",
                    )
                ),
            )
        )
        .order_by("name")
    )

    # Latest observations for every occupant, in one query rather than one
    # per bed: newest first, keep the first seen per encounter.
    encounters = {
        assignment.admission.encounter_id
        for ward in wards for bed in ward.beds.all()
        for assignment in bed.open_assignments
        if assignment.admission.encounter_id
    }
    latest_vitals = {}
    if clinical and encounters:
        for vitals in (
            VitalSigns.objects.filter(encounter_id__in=encounters)
            .order_by("encounter_id", "-recorded_at")
        ):
            latest_vitals.setdefault(vitals.encounter_id, vitals)

    def occupant(assignment):
        if assignment is None:
            return None
        stay = assignment.admission
        patient = stay.patient
        allowed = clinical
        if per_patient:
            from apps.rbac.relationships import relationship_for_request

            allowed = relationship_for_request(request, patient) is not None

        due = None
        if stay.status == AdmissionStatus.DISCHARGE_INITIATED:
            due = "discharging"
        elif stay.expected_discharge:
            if stay.expected_discharge < today:
                due = "overdue"
            elif stay.expected_discharge == today:
                due = "today"
            elif stay.expected_discharge == today + timedelta(days=1):
                due = "tomorrow"

        news2 = None
        vitals = latest_vitals.get(stay.encounter_id) if allowed else None
        if vitals is not None:
            scored = calculate_news2(vitals)
            news2 = {
                "score": scored["score"],
                "risk": scored["risk_level"],
                "recorded_at": vitals.recorded_at,
                "stale": now - vitals.recorded_at > STALE_AFTER,
                "on_oxygen": not vitals.on_room_air,
            }

        return {
            "admission": stay.reference,
            "patient": str(patient.uuid),
            "name": patient.full_name,
            "mrn": patient.mrn,
            "gender": patient.gender,
            "age": patient.age_years,
            "admitted_at": stay.admitted_at,
            "nights": stay.length_of_stay_days,
            "expected_discharge": stay.expected_discharge,
            "due": due,
            "status": stay.status,
            "source": stay.source,
            "consultant": stay.consultant_name,
            "is_mlc": stay.is_mlc,
            "diagnosis": (stay.admitting_diagnosis or stay.provisional_diagnosis) if allowed else None,
            "news2": news2,
            "clinical_restricted": not allowed,
        }

    def counts(beds, occupants):
        return {
            "beds": len(beds),
            "occupied": sum(1 for row in occupants if row),
            "available": sum(1 for bed, row in zip(beds, occupants)
                             if not row and bed.status == BedStatus.AVAILABLE),
            "cleaning": sum(1 for bed in beds if bed.status == BedStatus.CLEANING),
            "reserved": sum(1 for bed in beds if bed.status == BedStatus.RESERVED),
            "out_of_service": sum(1 for bed in beds if bed.status in OUT_OF_SERVICE),
            "due_home_today": sum(1 for row in occupants if row and row["due"] in ("today", "overdue")),
            "discharging": sum(1 for row in occupants if row and row["due"] == "discharging"),
            "high_news2": sum(
                1 for row in occupants
                if row and row["news2"] and row["news2"]["score"] >= 5
            ),
        }

    body = []
    everything_beds, everything_occupants = [], []
    for ward in wards:
        beds = list(ward.beds.all())
        occupants = [
            occupant(bed.open_assignments[0] if bed.open_assignments else None)
            for bed in beds
        ]
        everything_beds += beds
        everything_occupants += occupants
        body.append({
            "uuid": str(ward.uuid),
            "code": ward.code,
            "name": ward.name,
            "ward_type": ward.ward_type,
            "floor": ward.floor,
            "building": ward.building,
            "is_critical_care": ward.is_critical_care,
            "patients_per_nurse": ward.nurse_to_patient_ratio,
            "is_gender_segregated": ward.is_gender_segregated,
            "visiting_hours": ward.visiting_hours,
            "counts": counts(beds, occupants),
            "beds": [
                {
                    "uuid": str(bed.uuid),
                    "code": bed.code,
                    "bay": bed.bay,
                    "status": bed.status,
                    "status_reason": bed.status_reason,
                    "status_changed_at": bed.status_changed_at,
                    "gender_restriction": bed.gender_restriction,
                    "equipment": _equipment(bed),
                    "is_isolation": bed.is_isolation,
                    "occupant": row,
                }
                for bed, row in zip(beds, occupants)
            ],
        })

    return {
        "facility": {"uuid": str(facility.uuid), "name": facility.name},
        "generated_at": now,
        "clinical": clinical,
        "totals": counts(everything_beds, everything_occupants),
        "wards": body,
    }


class BedBoardView(APIView):
    """`GET /api/ipd/board/?facility=<uuid>` — the whole facility's bed board."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]

    def get(self, request):
        facility = get_object_or_404(Facility, uuid=request.query_params.get("facility"))
        return Response(bed_board(facility, request))
