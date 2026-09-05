"""Care relationships: whether a clinician is treating a particular patient.

Phase 2 of `docs/ACCESS_DESIGN.md`. This module answers one question and does
not enforce anything — nothing calls it yet, deliberately, so that it can be
measured and argued with before it starts refusing people.

**The idea.** Clinical access follows a care relationship rather than a
facility. A relationship is not administered: nobody maintains a list of who is
treating whom. It falls out of records the system already keeps — admissions,
appointments, orders, prescriptions, ward assignments — which is the only kind
of access control that stays accurate, because it is a by-product of doing the
work rather than a second job somebody has to remember.

**It returns why, not whether.** A boolean cannot be written onto an access
log, and it cannot be shown to the person reading the record. "You are seeing
this because you admitted them on Tuesday" is a different thing from a silent
success, and it is what makes the control reviewable afterwards.

**What it deliberately does not do.**

*It does not check permissions.* Whether somebody may read clinical data at all
is `patient.clinical.read`, resolved by `apps.rbac.services`. This module
answers the second question only — for *this* patient — and keeping them apart
means neither can quietly stand in for the other.

*It does not consider identity or safety data.* Those stay organization-wide.
Phase 1 exists to make that safe: a pharmacist who cannot see an allergy list
is more dangerous than one who can see too much.

*It does not decide about the past.* A doctor who saw somebody in 2019 is not
treating them today. Every source carries a recency window, and "ever touched
this record" is not a relationship.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.rbac.permissions import Scope

#: How long a completed contact keeps its relationship alive. A guess, and
#: recorded as one: a patient on annual review has a twelve-month cycle, so
#: this will probably become per-speciality. Ninety days covers an outpatient
#: episode, a course of treatment and the writing-up afterwards.
DEFAULT_RECENCY_DAYS = 90

#: An appointment creates a relationship slightly before and well after it. The
#: day before, so a clinician can read up the night before a clinic; a week
#: after, so they can write it up, chase a result and answer a query. Somebody
#: who fails to attend still had a relationship -- the clinic prepared for them.
APPOINTMENT_LOOKAHEAD_DAYS = 1
APPOINTMENT_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class Relationship:
    """Why this person may read this record.

    `source` is stable and machine-readable, for reporting on how access is
    actually being obtained. `reason` is the sentence a human reads, on the
    access log and on the screen.
    """

    source: str
    reason: str
    #: Set for break-glass, so a reviewer can find the grant it came from.
    reference: str = ""

    @property
    def is_break_glass(self) -> bool:
        return self.source == "break_glass"


def _cutoff(recency_days: int):
    return timezone.now() - timedelta(days=recency_days)


def has_care_relationship(
    user_id,
    patient,
    authorization=None,
    recency_days: int = DEFAULT_RECENCY_DAYS,
) -> Relationship | None:
    """Is this user treating this patient? Returns the reason, or `None`.

    Checks are ordered cheapest and most likely first, and short-circuit. The
    overwhelmingly common call is a clinician opening a patient they admitted
    an hour ago, which the first check answers with one indexed query.

    `authorization` is optional so the function can be used from a job or a
    shell with no request. When given, it grants the two exemptions below.
    """
    if patient is None:
        return None

    # A caller with no user id is not "everybody" -- they are nobody, and the
    # difference matters because these checks compare `user_id` against a
    # nullable column. `provider_uuid=None` becomes `provider_uuid IS NULL` in
    # SQL, so a `None` here would match every unattributed encounter and hand
    # back a relationship with each of those patients. Measured against the
    # demo tenant while writing this: three records, three strangers.
    #
    # Reachable in practice, not theoretical: `relationship_for_request` reads
    # `getattr(request.user, "uuid", None)`, and a portal principal -- the
    # patient-facing half of the application -- has no `uuid` at all.
    if user_id is None:
        return None

    # Resolve through any merge chain. A patient merged into another record is
    # a tombstone, and a relationship with the tombstone is a relationship with
    # the person -- refusing here would lock a clinician out of a record their
    # own patient was merged into.
    patient = patient.resolve() if hasattr(patient, "resolve") else patient

    exemption = _exemption(authorization)
    if exemption is not None:
        return exemption

    for check in (
        _open_encounter,
        _admission,
        _own_orders,
        _appointment,
        _nursing,
        _presented,
        _break_glass,
    ):
        found = check(user_id, patient, authorization, recency_days)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# Exemptions -- stated explicitly rather than falling out of something else
# ---------------------------------------------------------------------------


def _exemption(authorization) -> Relationship | None:
    """Roles for which the relationship question does not apply.

    Written as an explicit branch rather than allowed to emerge from a scope
    comparison somewhere, because an exemption that is a side effect is one
    nobody knows exists until it is abused.
    """
    if authorization is None:
        return None

    if getattr(authorization, "is_organization_owner", False):
        return Relationship(
            "owner", "You are an administrator of this organization.",
        )

    # Oversight is the job. An auditor who had to break glass to read a record
    # would generate an alert every time they did the thing they are for.
    if authorization.has("audit.read"):
        return Relationship("oversight", "You hold audit access.")

    # A clinical role held at organization scope is a deliberate grant of
    # everything -- a medical director, a group clinical lead. Narrowing it
    # again here would make that grant mean nothing.
    if authorization.scope_for("patient.clinical.read") == Scope.ORGANIZATION:
        return Relationship(
            "organization_scope",
            "You hold clinical access across the whole organization.",
        )
    return None


# ---------------------------------------------------------------------------
# The sources, cheapest first
# ---------------------------------------------------------------------------


def _open_encounter(user_id, patient, authorization, recency_days):
    """An encounter this person is the provider on.

    First because it is the commonest by a wide margin and it is one indexed
    lookup on `(provider_uuid, -started_at)`.
    """
    from apps.encounters.models import OPEN_ENCOUNTER_STATUSES, Encounter

    encounter = (
        Encounter.objects.filter(patient=patient, provider_uuid=user_id)
        .filter(
            Q(status__in=OPEN_ENCOUNTER_STATUSES)
            | Q(started_at__gte=_cutoff(recency_days))
        )
        .order_by("-started_at")
        .first()
    )
    if encounter is None:
        return None
    if encounter.is_open:
        return Relationship(
            "encounter",
            f"You have an open encounter with this patient "
            f"({encounter.reference}).",
        )
    return Relationship(
        "recent_encounter",
        f"You saw this patient on {encounter.started_at:%d %b %Y} "
        f"({encounter.reference}).",
    )


def _admission(user_id, patient, authorization, recency_days):
    """The patient is on a ward this person's scope reaches.

    Deliberately *not* "any admission anywhere". A live inpatient is being
    cared for by whoever is on that site, including people who have not yet
    touched the record -- the on-call doctor who has just been bleeped has a
    relationship before they have written anything. But it is bounded by the
    caller's facility scope, because being admitted in Bhaktapur does not
    concern a clinician who only works in Kathmandu.
    """
    from apps.inpatient.models import CLOSED_STATUSES, Admission

    if authorization is None:
        return None
    facility_ids = authorization.accessible_facility_ids("patient.clinical.read")
    if facility_ids == set():
        return None

    admissions = Admission.objects.filter(patient=patient).exclude(
        status__in=CLOSED_STATUSES
    )
    if facility_ids is not None:
        admissions = admissions.filter(facility_id__in=facility_ids)

    admission = admissions.select_related("facility").first()
    if admission is None:
        return None
    return Relationship(
        "admission",
        f"This patient is currently admitted at "
        f"{admission.facility.name} ({admission.reference}).",
    )


def _own_orders(user_id, patient, authorization, recency_days):
    """This person prescribed for them, or ordered a test on them.

    Ordering a test creates a duty to look at the result, which is the whole
    point of the diagnostics module's critical-value alerts. A clinician who
    could order a test and then not read it would be a strange thing to build.
    """
    from apps.diagnostics.models import DiagnosticOrder
    from apps.prescriptions.models import Prescription

    cutoff = _cutoff(recency_days)

    prescription = (
        Prescription.objects.filter(
            patient=patient, prescriber_id=user_id, prescribed_at__gte=cutoff,
        )
        .order_by("-prescribed_at")
        .first()
    )
    if prescription is not None:
        return Relationship(
            "prescriber",
            f"You prescribed for this patient on "
            f"{prescription.prescribed_at:%d %b %Y} ({prescription.reference}).",
        )

    order = (
        DiagnosticOrder.objects.filter(
            patient=patient, ordered_by_id=user_id, ordered_at__gte=cutoff,
        )
        .order_by("-ordered_at")
        .first()
    )
    if order is not None:
        return Relationship(
            "orderer",
            f"You ordered a test for this patient on "
            f"{order.ordered_at:%d %b %Y} ({order.reference}).",
        )
    return None


def _appointment(user_id, patient, authorization, recency_days):
    """Booked to see them, recently or shortly.

    A cancelled appointment is excluded; a missed one is not. The clinic
    prepared for somebody who did not arrive, and following that up is part of
    the job.
    """
    from apps.scheduling.models import AppointmentStatus, Appointment

    now = timezone.now()
    appointment = (
        Appointment.objects.filter(
            patient=patient,
            provider_uuid=user_id,
            scheduled_for__gte=now - timedelta(days=APPOINTMENT_LOOKBACK_DAYS),
            scheduled_for__lte=now + timedelta(days=APPOINTMENT_LOOKAHEAD_DAYS),
        )
        .exclude(status=AppointmentStatus.CANCELLED)
        .order_by("scheduled_for")
        .first()
    )
    if appointment is None:
        return None
    return Relationship(
        "appointment",
        f"You have an appointment with this patient on "
        f"{appointment.scheduled_for:%d %b %Y at %H:%M} "
        f"({appointment.reference}).",
    )


def _nursing(user_id, patient, authorization, recency_days):
    """Assigned to their bed on a shift.

    Nurses reach patients through the bed rather than through an encounter,
    and a check built only from clinician-shaped records would refuse every
    nurse on every ward.
    """
    from apps.inpatient.nursing_models import NurseAssignment

    assignment = (
        NurseAssignment.objects.filter(
            nurse_id=user_id,
            is_active=True,
            admission__patient=patient,
        )
        .select_related("admission")
        .first()
    )
    if assignment is None:
        return None
    return Relationship(
        "nursing",
        f"You are assigned to this patient's bed for the "
        f"{assignment.shift} shift.",
    )


def _presented(user_id, patient, authorization, recency_days):
    """A prescription for this patient is being held at the caller's counter.

    The source `ACCESS_DESIGN.md` named and Phase 2 shipped without, because
    there was nothing to read: `Prescription.facility` is where a prescription
    was *written*, and a patient may take it anywhere. Recording the act of
    presenting gave it something to stand on.

    Bounded by the caller's facility scope. A prescription presented in
    Kathmandu does not concern the Bhaktapur counter, and the whole point of
    the row is *which* pharmacy is holding it.
    """
    from apps.prescriptions.models import PrescriptionPresentation

    if authorization is None:
        return None
    facility_ids = authorization.accessible_facility_ids("prescription.dispense")
    if facility_ids == set():
        return None

    presentations = PrescriptionPresentation.objects.filter(
        prescription__patient=patient, is_active=True,
    )
    if facility_ids is not None:
        presentations = presentations.filter(facility_id__in=facility_ids)

    presentation = (
        presentations.select_related("prescription", "facility").first()
    )
    if presentation is None:
        return None
    return Relationship(
        "presented",
        f"{presentation.prescription.reference} was presented at "
        f"{presentation.facility.name}.",
    )


def _break_glass(user_id, patient, authorization, recency_days):
    """An emergency override, if one is live.

    Last because it is the rarest, and because everything above must be tried
    first: a clinician who has a real relationship must never be pushed into
    breaking glass, or the review queue fills with noise and stops being read.

    Counting the use here rather than at the point of granting is deliberate.
    A grant taken and never used is a different fact from one used forty times
    -- the first usually means somebody clicked through a warning, the second
    is worth a conversation -- and only a check at the moment of reading can
    tell them apart.
    """
    from apps.rbac.break_glass import live_grant, note_use

    grant = live_grant(user_id, patient)
    if grant is None:
        return None
    note_use(grant)
    return Relationship(
        "break_glass",
        f"Emergency access, opened {grant.granted_at:%d %b %Y at %H:%M} and "
        f"valid until {grant.expires_at:%H:%M}.",
        reference=str(grant.uuid),
    )


# ---------------------------------------------------------------------------
# Request-scoped caching
# ---------------------------------------------------------------------------


def relationship_for_request(request, patient) -> Relationship | None:
    """`has_care_relationship`, resolved once per request per patient.

    The same pattern `get_authorization` already uses, and for the same reason:
    a single view asks several times -- once in the permission class, again
    while filtering, again when deciding what to advertise in the response --
    and this touches six tables.
    """
    from apps.common.permissions import get_authorization

    if patient is None:
        return None
    cache = getattr(request, "_care_relationships", None)
    if cache is None:
        cache = {}
        request._care_relationships = cache

    key = str(getattr(patient, "uuid", patient))
    if key in cache:
        return cache[key]

    found = has_care_relationship(
        getattr(request.user, "uuid", None),
        patient,
        get_authorization(request),
    )
    cache[key] = found
    return found


# ---------------------------------------------------------------------------
# The list case: which patients, rather than whether this one
# ---------------------------------------------------------------------------


def related_patient_ids(user_id, authorization=None,
                        recency_days: int = DEFAULT_RECENCY_DAYS) -> set | None:
    """Every patient this user has a care relationship with.

    The list-shaped counterpart to `has_care_relationship`, and deliberately a
    separate function rather than the same one in a loop. Calling the
    object-level check once per row would be six queries per patient on a page
    of fifty; this is six queries for the whole page, because it asks each
    source "which patients" instead of asking "is it this one" repeatedly.

    Returns `None` for "no restriction" -- an owner, an auditor, an
    organization-scoped clinical role -- which mirrors
    `accessible_facility_ids` so that callers handle the two the same way. An
    empty set means the honest answer of nobody, and is not the same value.

    The two functions must agree, and the risk that they drift is real: a
    patient that appears in a list but cannot be opened, or the reverse, is a
    confusing bug rather than an obvious one. A test asserts they agree.
    """
    if user_id is None:
        return set()

    if authorization is not None and _exemption(authorization) is not None:
        return None

    from apps.diagnostics.models import DiagnosticOrder
    from apps.encounters.models import OPEN_ENCOUNTER_STATUSES, Encounter
    from apps.inpatient.models import CLOSED_STATUSES, Admission
    from apps.inpatient.nursing_models import NurseAssignment
    from apps.prescriptions.models import Prescription
    from apps.rbac.models import BreakGlassGrant
    from apps.scheduling.models import AppointmentStatus, Appointment

    cutoff = _cutoff(recency_days)
    now = timezone.now()
    ids: set = set()

    ids.update(
        Encounter.objects.filter(provider_uuid=user_id)
        .filter(
            Q(status__in=OPEN_ENCOUNTER_STATUSES) | Q(started_at__gte=cutoff)
        )
        .values_list("patient_id", flat=True)
    )

    if authorization is not None:
        facility_ids = authorization.accessible_facility_ids(
            "patient.clinical.read"
        )
        if facility_ids != set():
            admissions = Admission.objects.exclude(status__in=CLOSED_STATUSES)
            if facility_ids is not None:
                admissions = admissions.filter(facility_id__in=facility_ids)
            ids.update(admissions.values_list("patient_id", flat=True))

    ids.update(
        Prescription.objects.filter(
            prescriber_id=user_id, prescribed_at__gte=cutoff,
        ).values_list("patient_id", flat=True)
    )
    ids.update(
        DiagnosticOrder.objects.filter(
            ordered_by_id=user_id, ordered_at__gte=cutoff,
        ).values_list("patient_id", flat=True)
    )
    ids.update(
        Appointment.objects.filter(
            provider_uuid=user_id,
            scheduled_for__gte=now - timedelta(days=APPOINTMENT_LOOKBACK_DAYS),
            scheduled_for__lte=now + timedelta(days=APPOINTMENT_LOOKAHEAD_DAYS),
        )
        .exclude(status=AppointmentStatus.CANCELLED)
        .values_list("patient_id", flat=True)
    )
    ids.update(
        NurseAssignment.objects.filter(nurse_id=user_id, is_active=True)
        .exclude(admission__isnull=True)
        .values_list("admission__patient_id", flat=True)
    )

    presented_facilities = (
        authorization.accessible_facility_ids("prescription.dispense")
        if authorization is not None else set()
    )
    if presented_facilities != set():
        from apps.prescriptions.models import PrescriptionPresentation

        presentations = PrescriptionPresentation.objects.filter(is_active=True)
        if presented_facilities is not None:
            presentations = presentations.filter(
                facility_id__in=presented_facilities
            )
        ids.update(
            presentations.values_list("prescription__patient_id", flat=True)
        )

    # Break-glass is deliberately *not* counted towards uses here. A list is
    # not a read of a record: counting it would make one page view look like
    # forty accesses and drown the number that tells a reviewer whether the
    # override was actually needed.
    live_glass = BreakGlassGrant.objects.filter(
        user_id=user_id, expires_at__gt=now,
    ).values_list("patient_uuid", flat=True)
    if live_glass:
        from apps.patients.models import Patient

        ids.update(
            Patient.objects.filter(uuid__in=list(live_glass))
            .values_list("id", flat=True)
        )

    return ids


def related_patient_ids_for_request(request) -> set | None:
    """`related_patient_ids`, resolved once per request."""
    from apps.common.permissions import get_authorization

    cached = getattr(request, "_related_patient_ids", "unset")
    if cached != "unset":
        return cached

    found = related_patient_ids(
        getattr(request.user, "uuid", None), get_authorization(request),
    )
    request._related_patient_ids = found
    return found
