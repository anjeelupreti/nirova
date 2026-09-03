"""Collecting, grouping, screening, matching and issuing.

This layer refuses rather than warns. Every other guard in this system can be
overridden by somebody with the right permission and a reason, because the
alternative is that people work around the system. Here the alternative to
refusing is a death, so `issue_unit` has no override parameter at all — the
only path to blood without a cross-match is `issue_emergency`, which is a
different function with a different name, demands a consultant and records
that the hospital knowingly accepted the risk.

The rules.

**Two groupings by two people before anything is labelled.** Mislabelling at
grouping is the commonest cause of a fatal transfusion. A donation whose two
groupings disagree is quarantined and nothing is released from it.

**Missing is not negative.** A screening panel with no hepatitis result is not
a negative hepatitis result. `release_units` refuses on untested exactly as
firmly as on reactive, and says which of the two it is.

**A cross-match is between one unit and one patient, and it expires.** The
patient may have been transfused since and developed antibodies.

**Nothing leaves the fridge without the components of the check being
present:** a valid cross-match, a compatible group, an unexpired unit, and the
patient the cross-match was for.

**Every issue and every transfusion is traceable both ways** — donor to
recipients, and recipient back to donors — because that is what a look-back
needs and it cannot be reconstructed afterwards.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: a blood bank is inspected, and every unit's history is evidence. Who
# grouped it, who released it and who issued it are the questions asked after
# a reaction.
from apps.audit.services import record
from apps.bloodbank.models import (
    COMPONENT_SHELF_LIFE,
    CROSSMATCH_VALID_HOURS,
    PERMANENT_DEFERRAL_KEYS,
    PLASMA_COMPATIBILITY,
    RED_CELL_COMPATIBILITY,
    REACTION_TYPE_KEYS,
    SCREENING_KEYS,
    BloodGroup,
    BloodRequest,
    BloodUnit,
    ComponentType,
    CrossMatch,
    CrossMatchResult,
    Donation,
    DonationStatus,
    Donor,
    DonorStatus,
    Grouping,
    InfectionResult,
    PLASMA_COMPONENTS,
    RequestStatus,
    RequestUrgency,
    Screening,
    Transfusion,
    TransfusionOutcome,
    TransfusionReaction,
    UnitStatus,
    validate_reaction_type,
)
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
# tenant_atomic_method: a donation and its units are written together or not
# at all, and the transaction must open on the tenant connection — the router
# refuses to guess, so a bare `transaction.atomic` would protect nothing.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.bloodbank")

ZERO = Decimal("0.00")

#: Minutes a red cell unit may be out of controlled storage and still go back.
#: Beyond this the cold chain is broken and the unit is discarded — a rule
#: that exists because bacteria grow, and one that gets ignored without a
#: clock.
RETURN_WINDOW_MINUTES = 30


class BloodBankError(DomainError):
    """The blood bank will not do that."""


class Incompatible(BloodBankError):
    """The unit and the patient do not match."""


def _next_number(model, field: str, prefix: str) -> str:
    return f"{prefix}-{model.objects.count() + 1:06d}"


# ---------------------------------------------------------------------------
# Donors
# ---------------------------------------------------------------------------


@tenant_atomic_method
def register_donor(organization, actor, **details) -> Donor:
    """Add a donor to the registry."""
    require_module(organization, ModuleCode.BLOOD_BANK)

    if not details.get("full_name", "").strip():
        raise BloodBankError("A donor needs a name.")
    if not details.get("phone", "").strip():
        raise BloodBankError(
            "A donor needs a phone number. A donor who cannot be contacted "
            "cannot be told about a reactive result, and cannot be called "
            "when their group runs out."
        )

    return Donor.objects.create(
        donor_number=_next_number(Donor, "donor_number", "DON"),
        created_by_id=getattr(actor, "uuid", None),
        **details,
    )


@tenant_atomic_method
def defer_donor(
    donor: Donor, reason: str, actor, until=None, permanent: bool = False,
) -> Donor:
    """Stop somebody donating, for a while or for good.

    A reason is required. A deferral nobody can explain is one nobody will
    ever lift, and the donor is simply turned away every time they come.
    """
    if not reason.strip():
        raise BloodBankError("A deferral must say why.")

    donor.status = (
        DonorStatus.PERMANENTLY_DEFERRED if permanent
        else DonorStatus.TEMPORARILY_DEFERRED
    )
    donor.deferral_reason = reason
    donor.deferred_until = None if permanent else until
    donor.deferred_by_name = getattr(actor, "full_name", "") or ""
    donor.save(update_fields=[
        "status", "deferral_reason", "deferred_until", "deferred_by_name",
        "updated_at",
    ])
    record(
        AuditAction.UPDATE,
        entity_type="bloodbank.Donor",
        entity_id=donor.uuid,
        entity_label=f"{donor.donor_number} deferred",
        reason=reason,
        metadata={"permanent": permanent},
    )
    return donor


def rebuild_donation_count(donor: Donor) -> int:
    """Recount from the donations. A cache, never a counter."""
    donations = donor.donations.exclude(status=DonationStatus.DISCARDED)
    donor.donation_count = donations.count()
    latest = donations.order_by("-collected_at").first()
    donor.last_donated_on = latest.collected_at.date() if latest else None
    donor.save(update_fields=[
        "donation_count", "last_donated_on", "updated_at",
    ])
    return donor.donation_count


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


@tenant_atomic_method
def collect_donation(
    organization,
    donor: Donor,
    facility,
    actor,
    volume_ml: int = 450,
    haemoglobin=None,
    donor_weight_kg=None,
    collection_site: str = "",
    is_mobile_drive: bool = False,
    at=None,
) -> Donation:
    """Take a bag of blood, having checked the donor may give it.

    The eligibility check is a refusal. A donor deferred for hepatitis who
    donates anyway produces a unit that will be discarded at screening, having
    consumed a bag, a kit and a nurse's hour — and occasionally one that is
    not discarded because the screening was missed.
    """
    require_module(organization, ModuleCode.BLOOD_BANK)

    at = at or timezone.now()
    eligible, problems = donor.eligible_on(at.date())
    if not eligible:
        raise BloodBankError(
            f"{donor.full_name} cannot donate today.",
            detail={"reasons": problems},
        )

    # Below 12.5 g/dL the donation harms the donor. A threshold in code rather
    # than data because it is a safety floor, not a policy.
    if haemoglobin is not None and Decimal(str(haemoglobin)) < Decimal("12.5"):
        raise BloodBankError(
            f"Haemoglobin of {haemoglobin} g/dL is below the 12.5 minimum. "
            "Donating would harm the donor.",
            detail={"haemoglobin": str(haemoglobin)},
        )
    if donor_weight_kg is not None and Decimal(str(donor_weight_kg)) < Decimal("45"):
        raise BloodBankError(
            f"{donor_weight_kg}kg is below the 45kg minimum for a "
            f"{volume_ml}ml donation."
        )

    donation = Donation.objects.create(
        donation_number=_next_number(Donation, "donation_number", "BD"),
        donor=donor,
        facility=facility,
        collected_at=at,
        collected_by_name=getattr(actor, "full_name", "") or "",
        collection_site=collection_site,
        is_mobile_drive=is_mobile_drive,
        volume_ml=volume_ml,
        haemoglobin=haemoglobin,
        donor_weight_kg=donor_weight_kg,
        created_by_id=getattr(actor, "uuid", None),
    )
    rebuild_donation_count(donor)
    record(
        AuditAction.CREATE,
        entity_type="bloodbank.Donation",
        entity_id=donation.uuid,
        entity_label=f"{donation.donation_number} from {donor.full_name}",
    )
    return donation


@tenant_atomic_method
def record_grouping(
    donation: Donation,
    blood_group: str,
    actor,
    forward: str = "",
    reverse: str = "",
    is_weak_d: bool = False,
    antibody_screen: str = "",
    method: str = "",
) -> Grouping:
    """One person's determination of the group.

    Two are needed, by two different people, before anything is labelled. The
    unique constraint stops the same person entering a second result, because
    one person confirming their own reading is not a second check — it is the
    same check twice with the same error in it.
    """
    name = getattr(actor, "full_name", "") or ""
    if not name:
        raise BloodBankError(
            "A grouping must name who performed it. The second check exists "
            "because the first can be wrong, and an anonymous result cannot "
            "be a second check."
        )
    if Grouping.objects.filter(donation=donation, performed_by_name=name).exists():
        raise BloodBankError(
            f"{name} has already grouped {donation.donation_number}. The "
            "second determination must be by a different person."
        )

    return Grouping.objects.create(
        donation=donation,
        blood_group=blood_group,
        forward_result=forward,
        reverse_result=reverse,
        is_weak_d=is_weak_d,
        antibody_screen=antibody_screen,
        performed_by_id=getattr(actor, "uuid", None),
        performed_by_name=name,
        method=method,
        created_by_id=getattr(actor, "uuid", None),
    )


def confirmed_group(donation: Donation) -> tuple[str, list]:
    """The donation's group, or nothing and the reason why not.

    Returns `("", [problems])` unless two people have grouped it and agreed.
    Deliberately not "the most recent result" and not "the majority": a
    disagreement is a finding that stops the donation, not a vote.
    """
    groupings = list(donation.groupings.all())
    if len(groupings) < 2:
        return "", [
            f"Only {len(groupings)} of the two required groupings has been "
            "done."
        ]

    groups = {row.blood_group for row in groupings}
    if len(groups) > 1:
        return "", [
            "The two groupings disagree: "
            + ", ".join(
                f"{row.performed_by_name} read {row.blood_group}"
                for row in groupings
            )
            + ". Nothing may be released until this is resolved."
        ]
    return groups.pop(), []


@tenant_atomic_method
def record_screening(
    donation: Donation,
    results: dict,
    actor,
    values: dict = None,
    kit_lot_number: str = "",
) -> Screening:
    """Record the infection panel.

    Results are per infection. Anything not given stays untested rather than
    defaulting to negative, and `release_units` treats untested as firmly as
    reactive — because a unit nobody tested and a unit that failed are both
    unsafe, and pretending the first is the second's opposite is how an
    untested unit reaches a patient.
    """
    unknown = set(results) - set(SCREENING_KEYS)
    if unknown:
        raise BloodBankError(
            f"Not screening tests: {', '.join(sorted(unknown))}. The panel is "
            f"{', '.join(SCREENING_KEYS)}."
        )

    screening, _ = Screening.objects.update_or_create(
        donation=donation,
        defaults={
            "results": {**results},
            "values": values or {},
            "performed_at": timezone.now(),
            "performed_by_name": getattr(actor, "full_name", "") or "",
            "kit_lot_number": kit_lot_number,
            "created_by_id": getattr(actor, "uuid", None),
        },
    )

    # A reactive result on one of the permanent-deferral infections both
    # discards the donation and stops the donor for good. Doing one without
    # the other is how a hepatitis-positive donor is invited back next month.
    reactive = [
        key for key in screening.reactive if key in PERMANENT_DEFERRAL_KEYS
    ]
    if reactive:
        discard_donation(
            donation,
            f"Reactive on screening: {', '.join(reactive)}.",
            actor=actor,
        )
        defer_donor(
            donation.donor,
            f"Reactive screening on {donation.donation_number}: "
            f"{', '.join(reactive)}. Requires confirmatory testing and "
            "counselling.",
            actor=actor,
            permanent=True,
        )
        logger.warning(
            "Reactive screening on %s (%s): %s",
            donation.donation_number, donation.donor.donor_number,
            ", ".join(reactive),
        )
    elif screening.reactive:
        discard_donation(
            donation,
            f"Reactive on screening: {', '.join(screening.reactive)}.",
            actor=actor,
        )

    return screening


@tenant_atomic_method
def discard_donation(donation: Donation, reason: str, actor) -> Donation:
    """Throw the whole donation away, and every unit made from it."""
    if not reason.strip():
        raise BloodBankError("A discard must say why.")

    donation.status = DonationStatus.DISCARDED
    donation.discard_reason = reason
    donation.save(update_fields=["status", "discard_reason", "updated_at"])

    for unit in donation.units.exclude(
        status__in=(UnitStatus.TRANSFUSED, UnitStatus.DISCARDED)
    ):
        discard_unit(unit, reason, actor=actor)

    record(
        AuditAction.UPDATE,
        entity_type="bloodbank.Donation",
        entity_id=donation.uuid,
        entity_label=f"{donation.donation_number} discarded",
        reason=reason,
    )
    return donation


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


@tenant_atomic_method
def separate_components(
    donation: Donation, components: list, actor, at=None,
) -> list:
    """Turn one bag into its components, each with its own expiry.

    `components` are (component type, volume) pairs. The expiry and the storage
    range come from `COMPONENT_SHELF_LIFE` and are copied onto the unit, so a
    unit records the rule that applied when it was made rather than whatever
    the table says years later.

    Units are created quarantined. They become available only through
    `release_units`, which is where the grouping and screening checks live.
    """
    at = at or timezone.now()
    if donation.status == DonationStatus.DISCARDED:
        raise BloodBankError(
            f"{donation.donation_number} was discarded: "
            f"{donation.discard_reason}"
        )

    group, problems = confirmed_group(donation)
    if not group:
        raise BloodBankError(
            "The donation's group is not confirmed, so nothing can be "
            "labelled.",
            detail={"reasons": problems},
        )

    made = []
    for component, volume in components:
        if component not in COMPONENT_SHELF_LIFE:
            raise BloodBankError(f"'{component}' is not a component type.")
        days, low, high = COMPONENT_SHELF_LIFE[component]
        made.append(BloodUnit.objects.create(
            unit_number=_next_number(BloodUnit, "unit_number", "BU"),
            donation=donation,
            facility=donation.facility,
            component=component,
            blood_group=group,
            volume_ml=volume,
            prepared_at=at,
            expires_on=(at + timedelta(days=days)).date(),
            storage_min_c=low,
            storage_max_c=high,
            status=UnitStatus.QUARANTINED,
            created_by_id=getattr(actor, "uuid", None),
        ))

    donation.status = DonationStatus.PROCESSED
    donation.save(update_fields=["status", "updated_at"])
    return made


def release_blockers(donation: Donation) -> list:
    """Everything stopping this donation's units from being used.

    Sentences, and they distinguish untested from reactive because the two
    demand opposite responses: one is a laboratory that lost a sample, the
    other is a donor who must be told.
    """
    blockers = []

    group, problems = confirmed_group(donation)
    blockers.extend(problems)

    # Read the screening from the database rather than from the instance's
    # cached relation. A donation object held across a re-screen carries the
    # old result, and this function is the gate between a bag of blood and a
    # patient — the one place where reading a stale row is unacceptable in
    # either direction.
    screening = Screening.objects.filter(donation=donation).first()
    if screening is None:
        blockers.append("No screening has been recorded for this donation.")
    else:
        if screening.untested:
            blockers.append(
                "Not yet tested for "
                + ", ".join(screening.untested)
                + ". Untested is not negative."
            )
        if screening.reactive:
            blockers.append(
                "Reactive for " + ", ".join(screening.reactive) + "."
            )
        if not screening.verified_by_name:
            blockers.append(
                "The screening result has not been verified by a second "
                "person."
            )

    if donation.status == DonationStatus.DISCARDED:
        blockers.append(f"The donation was discarded: {donation.discard_reason}")

    return blockers


@tenant_atomic_method
def verify_screening(screening: Screening, actor) -> Screening:
    """A second person confirms the screening result.

    Separate from performing it for the same reason as the second grouping:
    the check exists because the first reading can be wrong, and the same
    person cannot provide it.
    """
    name = getattr(actor, "full_name", "") or ""
    if name and name == screening.performed_by_name:
        raise BloodBankError(
            f"{name} performed this screening. Verification must be by "
            "somebody else."
        )
    screening.verified_by_name = name
    screening.verified_at = timezone.now()
    screening.save(update_fields=[
        "verified_by_name", "verified_at", "updated_at",
    ])
    return screening


@tenant_atomic_method
def release_units(donation: Donation, actor) -> list:
    """Move a donation's units from quarantine onto the shelf.

    The one gate between a bag of blood and a patient. It refuses on any
    blocker and names them all, because a laboratory told only the first
    problem fixes it and comes back.
    """
    blockers = release_blockers(donation)
    if blockers:
        raise BloodBankError(
            f"{donation.donation_number} cannot be released.",
            detail={"blockers": blockers},
        )

    released = []
    for unit in donation.units.filter(status=UnitStatus.QUARANTINED):
        unit.status = UnitStatus.AVAILABLE
        unit.save(update_fields=["status", "updated_at"])
        released.append(unit)

    record(
        AuditAction.UPDATE,
        entity_type="bloodbank.Donation",
        entity_id=donation.uuid,
        entity_label=f"{donation.donation_number}: {len(released)} units released",
    )
    return released


@tenant_atomic_method
def discard_unit(unit: BloodUnit, reason: str, actor) -> BloodUnit:
    """Take a unit out of circulation permanently."""
    if not reason.strip():
        raise BloodBankError("A discard must say why.")
    if unit.status == UnitStatus.TRANSFUSED:
        raise BloodBankError(
            f"{unit.unit_number} has already been transfused."
        )

    unit.status = UnitStatus.DISCARDED
    unit.discard_reason = reason
    unit.discarded_at = timezone.now()
    unit.save(update_fields=[
        "status", "discard_reason", "discarded_at", "updated_at",
    ])
    return unit


@tenant_atomic_method
def expire_units(facility=None, on_date=None) -> dict:
    """Move everything past its date out of the available pool.

    Idempotent, and safe to run repeatedly: it selects on the date rather than
    on a flag, so running it twice in one day is a no-operation rather than a
    double count.
    """
    on_date = on_date or timezone.localdate()
    units = BloodUnit.objects.filter(
        expires_on__lt=on_date,
        status__in=(
            UnitStatus.QUARANTINED, UnitStatus.AVAILABLE, UnitStatus.RESERVED,
            UnitStatus.CROSSMATCHED,
        ),
    )
    if facility:
        units = units.filter(facility=facility)

    by_component = {}
    for unit in units:
        by_component[unit.component] = by_component.get(unit.component, 0) + 1
    count = units.update(
        status=UnitStatus.EXPIRED, updated_at=timezone.now(),
    )
    if count:
        logger.info("Expired %s blood units on %s", count, on_date)
    return {"expired": count, "by_component": by_component, "on": on_date}


# ---------------------------------------------------------------------------
# Requests, reservation and cross-matching
# ---------------------------------------------------------------------------


@tenant_atomic_method
def request_blood(
    organization,
    patient,
    facility,
    component: str,
    units: int,
    indication: str,
    actor,
    urgency: str = RequestUrgency.ROUTINE,
    encounter=None,
    stated_group: str = "",
    haemoglobin=None,
    required_by=None,
) -> BloodRequest:
    """A clinician asks for blood."""
    require_module(organization, ModuleCode.BLOOD_BANK)

    if units < 1:
        raise BloodBankError("A request must be for at least one unit.")
    if not indication.strip():
        raise BloodBankError(
            "A request must state the indication. Over-transfusion is the "
            "commonest quality finding in a blood bank, and it is invisible "
            "without one."
        )

    return BloodRequest.objects.create(
        reference=_next_number(BloodRequest, "reference", "BR"),
        patient=patient,
        encounter=encounter,
        facility=facility,
        requested_by_name=getattr(actor, "full_name", "") or "",
        required_by=required_by,
        urgency=urgency,
        component=component,
        units_requested=units,
        indication=indication,
        stated_group=stated_group,
        haemoglobin=haemoglobin,
        created_by_id=getattr(actor, "uuid", None),
    )


def compatible_units(
    facility, component: str, patient_group: str, on_date=None,
) -> list:
    """What is on the shelf that this patient could receive.

    Ordered by expiry, so the oldest compatible unit goes first — the same
    first-expiry-first-out rule as the pharmacy, and for the same reason: the
    alternative is a fridge full of units that expire together.
    """
    table = (
        PLASMA_COMPATIBILITY if component in PLASMA_COMPONENTS
        else RED_CELL_COMPATIBILITY
    )
    donor_groups = table.get(patient_group)
    if donor_groups is None:
        raise BloodBankError(f"'{patient_group}' is not a blood group.")

    return list(
        BloodUnit.objects.filter(
            facility=facility,
            component=component,
            blood_group__in=donor_groups,
            status=UnitStatus.AVAILABLE,
            expires_on__gte=on_date or timezone.localdate(),
        ).order_by("expires_on", "unit_number")
    )


def is_compatible(unit: BloodUnit, patient_group: str) -> bool:
    """Whether this unit's group may go to this patient's group.

    Reads the table on the unit, which picks plasma or red cells. A single
    table for both is the classic fatal shortcut: AB plasma suits everyone and
    AB red cells suit almost nobody.
    """
    return unit.blood_group in unit.compatibility_table.get(patient_group, [])


@tenant_atomic_method
def reserve_unit(
    unit: BloodUnit, patient, actor, reason: str = "", until=None,
) -> BloodUnit:
    """Hold a unit for a named patient without cross-matching it yet.

    A distinct state from cross-matched: the unit is off the available pool
    for the theatre list tomorrow, but it has not been tested against this
    patient and cannot be issued. Collapsing the two either double-issues
    units or makes the bank look emptier than it is.
    """
    if unit.status != UnitStatus.AVAILABLE:
        raise BloodBankError(
            f"{unit.unit_number} is {unit.get_status_display().lower()}."
        )
    if unit.is_expired:
        raise BloodBankError(
            f"{unit.unit_number} expired on {unit.expires_on}."
        )

    unit.status = UnitStatus.RESERVED
    unit.reserved_for = patient
    unit.reserved_until = until or (timezone.now() + timedelta(days=1))
    unit.reserved_reason = reason
    unit.save(update_fields=[
        "status", "reserved_for", "reserved_until", "reserved_reason",
        "updated_at",
    ])
    return unit


@tenant_atomic_method
def release_reservation(unit: BloodUnit, actor, reason: str = "") -> BloodUnit:
    """Put a held unit back on the shelf."""
    if unit.status not in (UnitStatus.RESERVED, UnitStatus.CROSSMATCHED):
        raise BloodBankError(
            f"{unit.unit_number} is not being held for anybody."
        )
    unit.status = UnitStatus.AVAILABLE
    unit.reserved_for = None
    unit.reserved_until = None
    unit.reserved_reason = ""
    unit.save(update_fields=[
        "status", "reserved_for", "reserved_until", "reserved_reason",
        "updated_at",
    ])
    return unit


@tenant_atomic_method
def cross_match(
    unit: BloodUnit,
    patient,
    patient_group: str,
    actor,
    request: BloodRequest = None,
    result: str = CrossMatchResult.COMPATIBLE,
    method: str = "",
    antibody_screen: str = "",
    incompatibility_detail: str = "",
    at=None,
) -> CrossMatch:
    """Test one unit against one patient.

    An ABO-incompatible pairing is refused outright rather than recorded as
    incompatible: entering it at all means the wrong unit was pulled, and the
    useful response is to stop and check the label, not to file a result.
    """
    if unit.status not in (
        UnitStatus.AVAILABLE, UnitStatus.RESERVED, UnitStatus.CROSSMATCHED,
    ):
        raise BloodBankError(
            f"{unit.unit_number} is {unit.get_status_display().lower()} and "
            "cannot be cross-matched."
        )
    if unit.is_expired:
        raise BloodBankError(f"{unit.unit_number} expired on {unit.expires_on}.")
    if unit.reserved_for_id and unit.reserved_for_id != patient.id:
        raise BloodBankError(
            f"{unit.unit_number} is being held for another patient."
        )
    if patient_group not in BloodGroup.values:
        raise BloodBankError(f"'{patient_group}' is not a blood group.")

    if result != CrossMatchResult.INCOMPATIBLE and not is_compatible(
        unit, patient_group
    ):
        raise Incompatible(
            f"{unit.unit_number} is {unit.blood_group} "
            f"{unit.get_component_display().lower()} and the patient is "
            f"{patient_group}. That pairing is never compatible — check the "
            "unit label and the patient's group before going further.",
            detail={
                "unit_group": unit.blood_group,
                "patient_group": patient_group,
                "acceptable": unit.compatibility_table.get(patient_group, []),
            },
        )

    at = at or timezone.now()
    match = CrossMatch.objects.create(
        unit=unit,
        patient=patient,
        request=request,
        performed_at=at,
        performed_by_name=getattr(actor, "full_name", "") or "",
        valid_until=at + timedelta(hours=CROSSMATCH_VALID_HOURS),
        result=result,
        method=method,
        patient_group=patient_group,
        antibody_screen=antibody_screen,
        incompatibility_detail=incompatibility_detail,
        created_by_id=getattr(actor, "uuid", None),
    )

    if result == CrossMatchResult.INCOMPATIBLE:
        # An incompatible result frees the unit for somebody else; it is the
        # patient who cannot have it, not the unit that is bad.
        if unit.status == UnitStatus.CROSSMATCHED:
            release_reservation(unit, actor=actor)
    else:
        unit.status = UnitStatus.CROSSMATCHED
        unit.reserved_for = patient
        unit.reserved_until = match.valid_until
        unit.save(update_fields=[
            "status", "reserved_for", "reserved_until", "updated_at",
        ])

    return match


def issue_blockers(unit: BloodUnit, patient) -> list:
    """Everything stopping this unit going to this patient.

    The list `issue_unit` refuses on. Written as its own function so a screen
    can show it before somebody walks to the fridge.
    """
    blockers = []

    if unit.status != UnitStatus.CROSSMATCHED:
        blockers.append(
            f"The unit is {unit.get_status_display().lower()}, not "
            "cross-matched."
        )
    if unit.is_expired:
        blockers.append(f"The unit expired on {unit.expires_on}.")
    if unit.reserved_for_id and unit.reserved_for_id != patient.id:
        blockers.append("The unit is being held for a different patient.")

    match = (
        unit.cross_matches.filter(patient=patient)
        .order_by("-performed_at")
        .first()
    )
    if match is None:
        blockers.append("There is no cross-match against this patient.")
    else:
        if match.result == CrossMatchResult.INCOMPATIBLE:
            blockers.append(
                f"The cross-match was incompatible: "
                f"{match.incompatibility_detail or 'no detail recorded'}."
            )
        elif match.valid_until <= timezone.now():
            blockers.append(
                f"The cross-match expired at "
                f"{match.valid_until:%d %b %H:%M}. The patient may have been "
                "transfused since and developed antibodies; repeat it."
            )
        if match.patient_group and not is_compatible(unit, match.patient_group):
            blockers.append(
                f"The unit is {unit.blood_group} and the patient is "
                f"{match.patient_group}."
            )

    return blockers


@tenant_atomic_method
def issue_unit(
    unit: BloodUnit, patient, actor, issued_to: str = "", at=None,
) -> BloodUnit:
    """Hand a unit over.

    There is no override parameter and there will not be one. Every other
    guard in this system can be overridden by somebody with the right
    permission and a reason, because the alternative is that people work
    around it. Here the alternative to refusing is a death.

    The emergency case is real and is served by `issue_emergency`, which is a
    different function with a different name and a different record.
    """
    blockers = issue_blockers(unit, patient)
    if blockers:
        raise BloodBankError(
            f"{unit.unit_number} cannot be issued to {patient.full_name}.",
            detail={"blockers": blockers},
        )

    at = at or timezone.now()
    unit.status = UnitStatus.ISSUED
    unit.issued_at = at
    unit.issued_to_name = issued_to or (getattr(actor, "full_name", "") or "")
    unit.left_storage_at = at
    unit.save(update_fields=[
        "status", "issued_at", "issued_to_name", "left_storage_at",
        "updated_at",
    ])

    record(
        AuditAction.UPDATE,
        entity_type="bloodbank.BloodUnit",
        entity_id=unit.uuid,
        entity_label=f"{unit.unit_number} issued for {patient.full_name}",
        metadata={"group": unit.blood_group, "component": unit.component},
    )
    return unit


@tenant_atomic_method
def issue_emergency(
    unit: BloodUnit,
    patient,
    actor,
    authorised_by: str,
    reason: str,
    at=None,
) -> BloodUnit:
    """Blood without a cross-match, because there is no time.

    A separate function rather than a flag on `issue_unit`, so that no path
    through the ordinary issue can ever skip the check by passing an argument.
    It still refuses an expired unit and an ABO-incompatible group — those
    take no time to check and kill just as fast — and it demands a named
    authoriser, because this is a risk the hospital accepts rather than a rule
    it waives.
    """
    if not authorised_by.strip() or not reason.strip():
        raise BloodBankError(
            "Uncross-matched blood needs a named authoriser and a reason. "
            "This is a risk the hospital is accepting, not a step being "
            "skipped."
        )
    if unit.is_expired:
        raise BloodBankError(
            f"{unit.unit_number} expired on {unit.expires_on}. An emergency "
            "does not make expired blood safe."
        )
    if unit.status not in (UnitStatus.AVAILABLE, UnitStatus.RESERVED):
        raise BloodBankError(
            f"{unit.unit_number} is {unit.get_status_display().lower()}."
        )

    # O negative for red cells, AB for plasma: the groups that suit anybody.
    # Anything else needs the patient's group, and if that is known there was
    # time to check compatibility.
    universal = (
        {"AB+", "AB-"} if unit.component in PLASMA_COMPONENTS else {"O-"}
    )
    if unit.blood_group not in universal:
        raise BloodBankError(
            f"{unit.unit_number} is {unit.blood_group}. Uncross-matched issue "
            f"is only for {', '.join(sorted(universal))} "
            f"{unit.get_component_display().lower()}, which suits any "
            "recipient. Use a cross-matched unit.",
            detail={"acceptable": sorted(universal)},
        )

    at = at or timezone.now()
    unit.status = UnitStatus.ISSUED
    unit.issued_at = at
    unit.issued_to_name = authorised_by
    unit.left_storage_at = at
    unit.reserved_for = patient
    unit.notes = f"Uncross-matched emergency issue: {reason}"
    unit.save(update_fields=[
        "status", "issued_at", "issued_to_name", "left_storage_at",
        "reserved_for", "notes", "updated_at",
    ])

    logger.warning(
        "Uncross-matched issue of %s (%s) for %s, authorised by %s: %s",
        unit.unit_number, unit.blood_group, patient.full_name,
        authorised_by, reason,
    )
    record(
        AuditAction.UPDATE,
        entity_type="bloodbank.BloodUnit",
        entity_id=unit.uuid,
        entity_label=f"{unit.unit_number} issued UNCROSS-MATCHED",
        reason=reason,
        metadata={"authorised_by": authorised_by, "patient": patient.mrn},
    )
    return unit


def return_unit(unit: BloodUnit, actor, reason: str = "", at=None) -> BloodUnit:
    """Take an issued unit back.

    Only within the cold-chain window. A red cell unit above 10 °C for more
    than thirty minutes grows bacteria and cannot go back on the shelf,
    however much it looks fine — so beyond the window this discards rather
    than returns, and says so.

    Deliberately *not* wrapped in `tenant_atomic_method`. The first version was,
    and the seed caught what that meant: the out-of-window branch discarded the
    unit and then raised, and the raise rolled the discard back. The system told
    the user the unit had been discarded while leaving it issued and reusable —
    the refusal undoing the very record that made it necessary. `discard_unit`
    opens its own transaction and commits before the exception is raised.
    """
    if unit.status != UnitStatus.ISSUED:
        raise BloodBankError(
            f"{unit.unit_number} is {unit.get_status_display().lower()}, not "
            "issued."
        )

    at = at or timezone.now()
    out_for = (
        (at - unit.left_storage_at).total_seconds() / 60
        if unit.left_storage_at else 0
    )
    if out_for > RETURN_WINDOW_MINUTES:
        discard_unit(
            unit,
            f"Out of controlled storage for {int(out_for)} minutes, beyond "
            f"the {RETURN_WINDOW_MINUTES}-minute window. {reason}".strip(),
            actor=actor,
        )
        raise BloodBankError(
            f"{unit.unit_number} was out of storage for {int(out_for)} "
            f"minutes. Beyond {RETURN_WINDOW_MINUTES} minutes the cold chain "
            "is broken and the unit has been discarded rather than returned.",
            detail={"minutes_out": int(out_for)},
        )

    unit.status = UnitStatus.AVAILABLE
    unit.returned_at = at
    unit.issued_at = None
    unit.left_storage_at = None
    unit.reserved_for = None
    unit.reserved_until = None
    unit.save(update_fields=[
        "status", "returned_at", "issued_at", "left_storage_at",
        "reserved_for", "reserved_until", "updated_at",
    ])
    # One row, one write: the successful path needs no transaction of its own.
    return unit


# ---------------------------------------------------------------------------
# Transfusion
# ---------------------------------------------------------------------------


@tenant_atomic_method
def transfuse(
    unit: BloodUnit,
    patient,
    actor,
    checked_by_first: str,
    checked_by_second: str,
    encounter=None,
    request: BloodRequest = None,
    at=None,
) -> Transfusion:
    """Start a transfusion, after the bedside check by two people.

    The bedside check is the last barrier before a fatal error, and one person
    checking alone is not the check — so two different names are required and
    the database refuses them being the same. Everything else about the
    transfusion can be filled in afterwards; this cannot.
    """
    if unit.status != UnitStatus.ISSUED:
        raise BloodBankError(
            f"{unit.unit_number} is {unit.get_status_display().lower()}. Only "
            "an issued unit can be transfused."
        )
    if unit.reserved_for_id and unit.reserved_for_id != patient.id:
        raise BloodBankError(
            f"{unit.unit_number} was issued for a different patient. Stop and "
            "check the identity band against the unit label."
        )
    if not checked_by_first.strip() or not checked_by_second.strip():
        raise BloodBankError(
            "The bedside check needs two named people."
        )
    if checked_by_first.strip() == checked_by_second.strip():
        raise BloodBankError(
            "The bedside check needs two different people. One person "
            "checking alone is not the check."
        )

    at = at or timezone.now()
    match = (
        unit.cross_matches.filter(patient=patient)
        .order_by("-performed_at")
        .first()
    )
    transfusion = Transfusion.objects.create(
        unit=unit,
        patient=patient,
        encounter=encounter,
        request=request,
        cross_match=match,
        started_at=at,
        checked_by_first=checked_by_first.strip(),
        checked_by_second=checked_by_second.strip(),
        identity_confirmed=True,
        created_by_id=getattr(actor, "uuid", None),
    )

    unit.status = UnitStatus.TRANSFUSED
    unit.save(update_fields=["status", "updated_at"])

    if request:
        _refresh_request(request)

    record(
        AuditAction.CREATE,
        entity_type="bloodbank.Transfusion",
        entity_id=transfusion.uuid,
        entity_label=f"{unit.unit_number} to {patient.full_name}",
        metadata={"group": unit.blood_group, "component": unit.component},
    )
    return transfusion


def _refresh_request(request: BloodRequest) -> BloodRequest:
    """Recount a request's fill from the transfusions against it."""
    given = request.transfusions.count()
    request.status = (
        RequestStatus.FILLED if given >= request.units_requested
        else RequestStatus.PART_FILLED if given
        else RequestStatus.PENDING
    )
    request.save(update_fields=["status", "updated_at"])
    return request


@tenant_atomic_method
def finish_transfusion(
    transfusion: Transfusion,
    actor,
    volume_ml=None,
    outcome: str = TransfusionOutcome.COMPLETED,
    at=None,
) -> Transfusion:
    """Close it off."""
    transfusion.finished_at = at or timezone.now()
    transfusion.volume_given_ml = volume_ml or transfusion.unit.volume_ml
    transfusion.outcome = outcome
    transfusion.save(update_fields=[
        "finished_at", "volume_given_ml", "outcome", "updated_at",
    ])
    return transfusion


@tenant_atomic_method
def record_observation(transfusion: Transfusion, actor, **values) -> Transfusion:
    """Append an observation to the transfusion chart.

    Appended, never edited. Observations during a transfusion are the evidence
    for whether a reaction was noticed promptly, and an editable chart is not
    evidence.
    """
    transfusion.observations = [
        *transfusion.observations,
        {
            "at": timezone.now().isoformat(),
            "by": getattr(actor, "full_name", "") or "",
            **{key: str(value) for key, value in values.items()
               if value is not None},
        },
    ]
    transfusion.save(update_fields=["observations", "updated_at"])
    return transfusion


@tenant_atomic_method
def report_reaction(
    transfusion: Transfusion,
    reaction_type: str,
    severity: str,
    symptoms: str,
    actor,
    minutes_in=None,
    stopped: bool = True,
    volume_ml=None,
    treatment: str = "",
) -> TransfusionReaction:
    """Report a reaction, and mark the transfusion as stopped if it was.

    A severe or life-threatening reaction is logged loudly, because an acute
    haemolytic reaction means a unit may have gone to the wrong patient — and
    that makes every other unit cross-matched in the same session suspect.
    """
    # Validated here rather than by the model helper alone, so that callers
    # see one error type from this layer. A service that raises Django's
    # ValidationError for one input and its own error for the next makes every
    # caller catch two things or miss one.
    if reaction_type not in REACTION_TYPE_KEYS:
        raise BloodBankError(
            f"'{reaction_type}' is not a reportable reaction type. The "
            "national return asks for these categories, and free text "
            "produces a year of reports nobody can aggregate. Use one of: "
            f"{', '.join(sorted(REACTION_TYPE_KEYS))}."
        )
    if not symptoms.strip():
        raise BloodBankError("A reaction report must describe what happened.")

    reaction = TransfusionReaction.objects.create(
        transfusion=transfusion,
        reported_by_name=getattr(actor, "full_name", "") or "",
        minutes_into_transfusion=minutes_in,
        reaction_type=reaction_type,
        severity=severity,
        symptoms=symptoms,
        transfusion_stopped=stopped,
        volume_transfused_ml=volume_ml,
        treatment_given=treatment,
        created_by_id=getattr(actor, "uuid", None),
    )

    if stopped and transfusion.outcome == TransfusionOutcome.COMPLETED:
        transfusion.outcome = TransfusionOutcome.STOPPED
        transfusion.volume_given_ml = volume_ml
        transfusion.finished_at = timezone.now()
        transfusion.save(update_fields=[
            "outcome", "volume_given_ml", "finished_at", "updated_at",
        ])

    if severity in ("severe", "life_threatening", "fatal"):
        logger.error(
            "SEVERE transfusion reaction: %s on %s to %s (%s)",
            reaction_type, transfusion.unit.unit_number,
            transfusion.patient.full_name, severity,
        )
    record(
        AuditAction.CREATE,
        entity_type="bloodbank.TransfusionReaction",
        entity_id=reaction.uuid,
        entity_label=(
            f"{reaction_type} on {transfusion.unit.unit_number} "
            f"({severity})"
        ),
        reason=symptoms[:200],
    )
    return reaction


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


def look_back(donor: Donor) -> dict:
    """Every patient who received this donor's blood.

    The question asked when a donor seroconverts, and the reason `Transfusion`
    links a unit to a patient permanently. Without the link the answer is that
    nobody knows, and the hospital has to contact everybody or nobody.
    """
    donations = donor.donations.prefetch_related("units__transfusion")
    rows = []
    for donation in donations:
        for unit in donation.units.all():
            transfusion = getattr(unit, "transfusion", None)
            rows.append({
                "donation": donation.donation_number,
                "collected_on": donation.collected_at.date(),
                "unit": unit.unit_number,
                "component": unit.component,
                "status": unit.status,
                "patient": (
                    transfusion.patient.full_name if transfusion else None
                ),
                "mrn": transfusion.patient.mrn if transfusion else None,
                "phone": (
                    getattr(transfusion.patient, "phone", "")
                    if transfusion else None
                ),
                "transfused_on": (
                    transfusion.started_at.date() if transfusion else None
                ),
            })

    recipients = [row for row in rows if row["patient"]]
    return {
        "donor": donor.full_name,
        "donor_number": donor.donor_number,
        "donations": donations.count(),
        "units": len(rows),
        "recipients": len(recipients),
        "rows": rows,
    }


def trace_patient(patient) -> dict:
    """Every unit this patient has received, and where each came from.

    The other direction: a reaction, or a positive result in a patient with no
    other risk factor, means finding the donors.
    """
    transfusions = (
        patient.transfusions.select_related("unit__donation__donor")
        .order_by("-started_at")
    )
    return {
        "patient": patient.full_name,
        "mrn": patient.mrn,
        "transfusions": [
            {
                "unit": row.unit.unit_number,
                "component": row.unit.component,
                "group": row.unit.blood_group,
                "donation": row.unit.donation.donation_number,
                "donor": row.unit.donation.donor.donor_number,
                "transfused_on": row.started_at.date(),
                "outcome": row.outcome,
                "reactions": row.reactions.count(),
            }
            for row in transfusions
        ],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def stock(facility) -> dict:
    """What is in the fridge, by group and component.

    Includes what expires this week, because a blood bank's real problem is
    not the total but the shape of it: forty units of O positive expiring on
    Thursday and none of A negative is a crisis that a single total hides.
    """
    units = BloodUnit.objects.filter(
        facility=facility,
        status__in=(
            UnitStatus.AVAILABLE, UnitStatus.RESERVED, UnitStatus.CROSSMATCHED,
        ),
        expires_on__gte=timezone.localdate(),
    )

    grid = {}
    soon = timezone.localdate() + timedelta(days=7)
    expiring = 0
    for unit in units:
        row = grid.setdefault(unit.component, {})
        cell = row.setdefault(
            unit.blood_group, {"available": 0, "held": 0, "expiring": 0},
        )
        if unit.status == UnitStatus.AVAILABLE:
            cell["available"] += 1
        else:
            cell["held"] += 1
        if unit.expires_on <= soon:
            cell["expiring"] += 1
            expiring += 1

    return {
        "facility": facility.name,
        "total": units.count(),
        "available": units.filter(status=UnitStatus.AVAILABLE).count(),
        "held": units.exclude(status=UnitStatus.AVAILABLE).count(),
        "expiring_within_7_days": expiring,
        "quarantined": BloodUnit.objects.filter(
            facility=facility, status=UnitStatus.QUARANTINED,
        ).count(),
        "by_component": grid,
    }


def wastage(facility=None, since=None) -> dict:
    """What was thrown away, and why.

    Discard reasons matter more than the total: expiry is a stock-management
    problem, a broken cold chain is a process problem, and a reactive
    screening result is neither — it is the system working.
    """
    since = since or (timezone.localdate() - timedelta(days=90))
    units = BloodUnit.objects.filter(
        status__in=(UnitStatus.DISCARDED, UnitStatus.EXPIRED),
        prepared_at__date__gte=since,
    )
    if facility:
        units = units.filter(facility=facility)

    issued = BloodUnit.objects.filter(
        status__in=(UnitStatus.ISSUED, UnitStatus.TRANSFUSED),
        prepared_at__date__gte=since,
    )
    if facility:
        issued = issued.filter(facility=facility)

    by_reason = {}
    for unit in units:
        key = (
            "expired" if unit.status == UnitStatus.EXPIRED
            else (unit.discard_reason or "unstated").split(":")[0][:60]
        )
        by_reason[key] = by_reason.get(key, 0) + 1

    discarded = units.count()
    total = discarded + issued.count()
    return {
        "since": since,
        "discarded": discarded,
        "issued": issued.count(),
        "wastage_percent": (
            round(discarded * 100 / total, 1) if total else None
        ),
        "by_reason": dict(sorted(by_reason.items(), key=lambda item: -item[1])),
    }


def haemovigilance(facility=None, since=None) -> dict:
    """The reaction return: how many, of what kind, and how severe.

    Reported with the clerical-error count beside it, because a clerical error
    is the one category that is entirely preventable and the one a blood bank
    is judged on.
    """
    since = since or (timezone.localdate() - timedelta(days=365))
    reactions = TransfusionReaction.objects.filter(
        transfusion__started_at__date__gte=since,
    ).select_related("transfusion__unit")
    if facility:
        reactions = reactions.filter(transfusion__unit__facility=facility)

    transfusions = Transfusion.objects.filter(started_at__date__gte=since)
    if facility:
        transfusions = transfusions.filter(unit__facility=facility)

    by_type = {}
    by_severity = {}
    for reaction in reactions:
        by_type[reaction.reaction_type] = by_type.get(reaction.reaction_type, 0) + 1
        by_severity[reaction.severity] = by_severity.get(reaction.severity, 0) + 1

    total_transfusions = transfusions.count()
    return {
        "since": since,
        "transfusions": total_transfusions,
        "reactions": reactions.count(),
        "reaction_rate_percent": (
            round(reactions.count() * 100 / total_transfusions, 2)
            if total_transfusions else None
        ),
        "by_type": dict(sorted(by_type.items(), key=lambda item: -item[1])),
        "by_severity": by_severity,
        "clerical_errors": reactions.filter(is_clerical_error=True).count(),
        "not_reported_to_authority": reactions.filter(
            severity__in=("severe", "life_threatening", "fatal"),
            reported_to_authority=False,
        ).count(),
    }


def donor_call_list(facility, blood_group: str, limit: int = 50) -> list:
    """Donors of a group who could be called, soonest-eligible first.

    The answer to "we are out of A negative". Ordered by when each becomes
    eligible rather than by name, because a donor eligible next week is not
    the same as one eligible today.
    """
    today = timezone.localdate()
    donors = Donor.objects.filter(
        blood_group=blood_group,
        status__in=(DonorStatus.ACTIVE, DonorStatus.TEMPORARILY_DEFERRED),
        is_contactable=True,
    ).order_by("last_donated_on")[: limit * 2]

    rows = []
    for donor in donors:
        eligible, problems = donor.eligible_on(today)
        rows.append({
            "donor_number": donor.donor_number,
            "name": donor.full_name,
            "phone": donor.phone,
            "blood_group": donor.blood_group,
            "donations": donor.donation_count,
            "last_donated": donor.last_donated_on,
            "eligible_now": eligible,
            "problems": problems,
        })

    rows.sort(key=lambda row: (not row["eligible_now"], row["last_donated"] or today))
    return rows[:limit]
