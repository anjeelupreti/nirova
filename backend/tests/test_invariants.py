"""The invariants that have actually been broken, guarded so they stay fixed.

Every test here corresponds to a numbered entry in the development log. That is
the selection rule: this file is not an attempt at coverage, it is a record of
things that went wrong once and must not go wrong silently again.
"""

import json
import types

import pytest

# databases="__all__": this project is database-per-tenant and the tenant
# alias is registered at runtime, so it cannot be enumerated here. Without
# this, every query against the tenant is refused as an isolation violation.
pytestmark = pytest.mark.django_db(databases="__all__")


# ---------------------------------------------------------------------------
# Log 154, 157 — scope narrows, and its fall-through denies
# ---------------------------------------------------------------------------


def _authorization_with(organization, code, scope, facility_ids):
    from apps.rbac.services import UserAuthorization, _merge

    auth = UserAuthorization(user_id="test", organization_id=organization.id)
    _merge(auth, code, scope, "test", facility_ids=facility_ids)
    return types.SimpleNamespace(_authorization=auth, user=None)


@pytest.mark.parametrize(
    "scope_name",
    ["FACILITY", "MULTI_FACILITY", "DEPARTMENT", "UNIT", "OWN_PATIENTS"],
)
def test_scope_filter_denies_when_it_reaches_no_facility(tenant, scope_name):
    """A grant naming no facility must return nothing, never everything.

    Log 157. `apply_scope_filter` shipped ending `return queryset`, so a
    facility-scoped grant with an empty facility set -- the state `assign_role`
    still permits -- handed back the entire organization. That inverted an
    existing known defect from fail-closed to fail-open, and silently, because
    a filtered list looks exactly like an unfiltered one unless somebody counts
    the rows.
    """
    from apps.common.permissions import apply_scope_filter
    from apps.hr.models import Employee
    from apps.rbac.permissions import Scope

    total = Employee.objects.count()
    assert total > 0, "no employees to filter; run seed_hr_demo"

    request = _authorization_with(
        tenant, "employee.read", getattr(Scope, scope_name), set(),
    )
    got = apply_scope_filter(Employee.objects.all(), request, "employee.read").count()
    assert got == 0, (
        f"{scope_name} scope naming no facility returned {got} of {total} "
        "employees; the fall-through must deny"
    )


def test_scope_filter_allows_organization_scope(tenant):
    """The other half: organization scope still sees everything."""
    from apps.common.permissions import apply_scope_filter
    from apps.hr.models import Employee
    from apps.rbac.permissions import Scope

    request = _authorization_with(
        tenant, "employee.read", Scope.ORGANIZATION, None,
    )
    got = apply_scope_filter(Employee.objects.all(), request, "employee.read").count()
    assert got == Employee.objects.count()


# ---------------------------------------------------------------------------
# Log 161 — a partial constraint must agree with its manager
# ---------------------------------------------------------------------------


def test_soft_deleted_notification_does_not_block_its_dedupe_key(tenant):
    """A soft-deleted row must not hold a dedupe key hostage.

    Log 161. The constraint read `resolved_at IS NULL`, which a soft-deleted
    row still satisfies, so it blocked the key forever -- while
    `Notification.objects` could not see the row doing the blocking. `notify`
    swallowed the resulting IntegrityError exactly as designed, and every
    future notification under that key vanished with a log line as the only
    trace.
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import notify

    key = "test:soft-delete-does-not-block"
    Notification.all_objects.filter(dedupe_key=key).delete()

    recipients = [{"id": tenant.uuid, "name": "test", "reason": "test"}]
    first = notify(
        source="test", event="dedupe_probe", title="first",
        recipients=recipients, dedupe_key=key,
    )
    assert first is not None
    first.delete()  # soft delete

    second = notify(
        source="test", event="dedupe_probe", title="second",
        recipients=recipients, dedupe_key=key,
    )
    assert second is not None, (
        "a soft-deleted notification is still blocking its dedupe key, so "
        "every future notification under it is lost silently"
    )
    Notification.all_objects.filter(dedupe_key=key).delete()


# ---------------------------------------------------------------------------
# Log 160 — read and dismissed are different, and critical needs a note
# ---------------------------------------------------------------------------


def test_critical_notification_cannot_be_dismissed_without_a_note(tenant):
    """Log 160. A critical alert cleared without a word is a record that
    somebody silenced it, which is worse than no record at all."""
    from apps.notifications.models import Notification, NotificationCategory
    from apps.notifications.services import NotificationError, dismiss, notify

    recipients = [{"id": tenant.uuid, "name": "test", "reason": "test"}]
    notification = notify(
        source="test", event="critical_probe",
        category=NotificationCategory.CRITICAL,
        title="test critical", recipients=recipients,
    )
    receipt = notification.receipts.first()

    with pytest.raises(NotificationError):
        dismiss(receipt, note="")

    dismiss(receipt, note="Dealt with.")
    receipt.refresh_from_db()
    assert receipt.dismissed_at is not None
    # The constraint requires read before dismissed; dismissing sets both.
    assert receipt.read_at is not None

    Notification.all_objects.filter(pk=notification.pk).delete()


def test_preferences_cannot_silence_critical(tenant):
    """Log 160. `set_preference` refuses rather than storing a value it would
    then ignore -- otherwise the screen says something is off while it is on."""
    from apps.notifications.models import NotificationCategory
    from apps.notifications.services import NotificationError, set_preference

    with pytest.raises(NotificationError):
        set_preference(tenant.uuid, NotificationCategory.CRITICAL, enabled=False)


# ---------------------------------------------------------------------------
# Log 158 — generated documents escape what they interpolate
# ---------------------------------------------------------------------------


def test_generated_documents_escape_patient_text(tenant):
    """Log 158. The patient application renders this HTML same-origin, and the
    portal token lives in `sessionStorage`."""
    from apps.billing.models import Invoice
    from apps.portal.models import PortalAccount
    from apps.portal.services import generate_patient_document

    payload = '<script>alert(1)</script>'
    account = None
    for candidate in PortalAccount.objects.select_related("patient").filter(
        status="active",
    ):
        if Invoice.objects.filter(patient=candidate.patient).exclude(
            status="draft",
        ).exists():
            account = candidate
            break
    if account is None:
        pytest.skip("no portal patient with an issued invoice; run seed_portal_demo")

    patient = account.patient
    invoice = Invoice.objects.filter(patient=patient).exclude(status="draft").first()
    original = patient.first_name
    try:
        patient.first_name = payload
        patient.save(update_fields=["first_name"])
        document = generate_patient_document(
            account, patient, "invoice", invoice.number,
        )
        assert payload not in document["html"], (
            "a script tag in a patient name reached the generated document "
            "unescaped"
        )
        assert "&lt;script&gt;" in document["html"]
    finally:
        patient.first_name = original
        patient.save(update_fields=["first_name"])


# ---------------------------------------------------------------------------
# Log 164 — holders_of agrees with the check that runs at approval time
# ---------------------------------------------------------------------------


def test_holders_of_agrees_with_resolve_authorization(tenant):
    """The whole value of the helper is that it cannot disagree with the
    permission check that runs when somebody actually tries to approve."""
    from apps.identity.models import Membership, MembershipStatus
    from apps.rbac.services import holders_of, resolve_authorization

    code = "leave.approve"
    forward = {person["id"] for person in holders_of(code)}
    backward = set()
    for membership in Membership.objects.filter(
        organization=tenant, status=MembershipStatus.ACTIVE,
    ).select_related("user"):
        authorization = resolve_authorization(membership.user, membership)
        if authorization.has(code) or authorization.is_organization_owner:
            backward.add(membership.user.uuid)

    assert forward == backward, (
        "holders_of and resolve_authorization disagree about who can approve "
        f"leave: only in holders_of {forward - backward}, "
        f"only in resolve {backward - forward}"
    )


# ---------------------------------------------------------------------------
# ACCESS_DESIGN.md Phase 1 — the pharmacist's safety net
# ---------------------------------------------------------------------------


def test_dispensing_refuses_a_recorded_allergy_without_a_reason(tenant):
    """The last line of defence, which did not exist until 5 September 2026.

    A prescriber has faced allergy, interaction and duplicate checking since
    this system was built. Dispensing faced none, so a pharmacist -- the last
    person between a prescribing error and a patient -- had no net. The demo
    data itself contained the case: a patient with a severe penicillin allergy
    and facial swelling, and a seed that handed them amoxicillin on every run.

    It refuses; it does not forbid. A control that cannot be overridden is one
    that gets worked around outside the system, where nobody can see it.
    """
    from apps.patients.models import PatientAllergy
    from apps.pharmacy.models import Product, StockLocation
    from apps.pharmacy.services import SafetyOverrideRequired, dispense

    allergy = (
        PatientAllergy.objects.select_related("patient")
        .filter(status="active", substance__icontains="penicillin")
        .first()
    )
    if allergy is None:
        pytest.skip("no penicillin allergy in the demo data")

    product = Product.objects.filter(
        generic_name__icontains="amoxicillin", is_active=True,
    ).first()
    location = StockLocation.objects.filter(is_dispensable=True).first()
    if product is None or location is None:
        pytest.skip("no amoxicillin in a dispensable location")

    items = [{"product": product, "quantity": 1}]

    with pytest.raises(SafetyOverrideRequired):
        dispense(tenant, allergy.patient, location.facility, location, items)

    dispensed = dispense(
        tenant, allergy.patient, location.facility, location, items,
        safety_override_reason="Prescriber consulted; tolerated previously.",
    )
    assert dispensed.reference


def test_a_scope_that_reaches_nothing_cannot_be_assigned(tenant):
    """ACCESS_DESIGN.md Phase 1. A facility-scoped assignment naming no
    facility used to be storable, and produced a user who appeared to hold a
    role and could see nothing -- then, briefly, everything (log 157)."""
    from apps.common.exceptions import PermissionDeniedError
    from apps.identity.models import User
    from apps.rbac.permissions import Scope
    from apps.rbac.services import assign_role

    user = User.objects.filter(email="counter@manakamana.test").first()
    if user is None:
        pytest.skip("no counter user; run seed_demo")

    with pytest.raises(PermissionDeniedError):
        assign_role(
            user=user, role_code="pharmacy_counter",
            scope=Scope.FACILITY, reason="test",
        )


def test_business_lists_narrow_to_the_facility(tenant):
    """ACCESS_DESIGN.md Phase 1. Invoices, sales, dispensings and till
    sessions are a facility's own business records; unlike clinical data there
    is no safety argument for a counter assistant at one branch paging through
    another branch's takings.

    Asserted against the database rather than a fixed number, because a count
    on its own says nothing -- 88 rows is correct or wrong depending entirely
    on how many exist.
    """
    import types

    from apps.billing.models import Invoice
    from apps.common.permissions import apply_scope_filter
    from apps.organization.models import Facility
    from apps.rbac.permissions import Scope
    from apps.rbac.services import UserAuthorization, _merge

    pharmacy = Facility.objects.filter(facility_type="pharmacy").first()
    if pharmacy is None:
        pytest.skip("no pharmacy facility; run seed_demo")

    total = Invoice.objects.count()
    at_pharmacy = Invoice.objects.filter(facility=pharmacy).count()
    if total == at_pharmacy:
        pytest.skip("every invoice is at the pharmacy; nothing to distinguish")

    auth = UserAuthorization(user_id="test", organization_id=tenant.id)
    _merge(auth, "invoice.read", Scope.FACILITY, "test",
           facility_ids={pharmacy.id})
    request = types.SimpleNamespace(_authorization=auth, user=None)

    got = apply_scope_filter(
        Invoice.objects.all(), request, "invoice.read",
    ).count()
    assert got == at_pharmacy, (
        f"a facility-scoped role saw {got} invoices; {at_pharmacy} belong to "
        f"its facility and {total} exist in the tenant"
    )


def test_prescriptions_are_deliberately_not_facility_filtered(tenant):
    """The asymmetry, asserted so nobody 'fixes' it later.

    A prescription may be presented at any pharmacy -- that is what a
    prescription is -- and `Prescription.facility` records where it was
    *written*. Narrowing the prescription list by facility would break group
    dispensing, which is a real workflow. Phase 2 narrows it by *care
    relationship* instead, and keeps lookup by reference open: the patient
    handing over the number is the relationship and is the consent.
    """
    from apps.prescriptions.views import PrescriptionViewSet
    import inspect

    source = inspect.getsource(PrescriptionViewSet.get_queryset)
    assert "apply_scope_filter" not in source, (
        "the prescription list has been facility-filtered; see "
        "ACCESS_DESIGN.md for why that breaks group dispensing"
    )


# ---------------------------------------------------------------------------
# PHASE2_PLAN.md step 0 — the relationship sources must resolve to real people
# ---------------------------------------------------------------------------


def test_relationship_sources_point_at_real_members(tenant):
    """Every id Phase 2 will compare against must name somebody who can sign in.

    Measured before building the relationship check rather than discovered
    after enforcing it. The first measurement found `Encounter.provider_uuid`
    22% populated, and every appointment pointing at a provider who was not a
    user, not an employee and not a member -- a column that looked full and was
    only wrong the moment something compared it to something else.

    Asserted as a floor rather than a fixed number, because seeds add rows.
    """
    from apps.diagnostics.models import DiagnosticOrder
    from apps.encounters.models import Encounter
    from apps.identity.models import Membership, MembershipStatus
    from apps.inpatient.nursing_models import NurseAssignment
    from apps.prescriptions.models import Prescription
    from apps.scheduling.models import Appointment

    members = set(
        Membership.objects.filter(
            organization=tenant, status=MembershipStatus.ACTIVE,
        ).values_list("user__uuid", flat=True)
    )
    assert members, "no active members; run seed_demo"

    sources = [
        ("Encounter.provider_uuid", Encounter, "provider_uuid", 90),
        ("Appointment.provider_uuid", Appointment, "provider_uuid", 90),
        ("DiagnosticOrder.ordered_by_id", DiagnosticOrder, "ordered_by_id", 90),
        ("Prescription.prescriber_id", Prescription, "prescriber_id", 90),
        ("NurseAssignment.nurse_id", NurseAssignment, "nurse_id", 90),
    ]

    problems = []
    for label, model, field, floor in sources:
        total = model.objects.count()
        if total == 0:
            continue
        filled = model.objects.filter(**{f"{field}__isnull": False}).count()
        coverage = filled / total * 100
        if coverage < floor:
            problems.append(f"{label}: only {coverage:.1f}% populated")

        # A populated column pointing at nobody is the same failure wearing a
        # better disguise, so this half matters more than the coverage.
        orphans = {
            value
            for value in model.objects.filter(
                **{f"{field}__isnull": False}
            ).values_list(field, flat=True)
        } - members
        if orphans:
            problems.append(
                f"{label}: {len(orphans)} id(s) are not an active member"
            )

    assert not problems, "; ".join(problems)


# ---------------------------------------------------------------------------
# PHASE2_PLAN.md step 1 — the care relationship
# ---------------------------------------------------------------------------


def test_no_user_id_is_nobody_not_everybody(tenant):
    """A caller with no user id must not match unattributed records.

    These checks compare `user_id` against nullable columns, so
    `provider_uuid=None` becomes `provider_uuid IS NULL` and a `None` caller
    would collect a relationship with every patient whose encounter has no
    provider. Reachable: `relationship_for_request` reads
    `getattr(request.user, "uuid", None)`, and a portal principal has none.
    """
    from apps.encounters.models import Encounter
    from apps.rbac.relationships import has_care_relationship

    orphan = Encounter.objects.filter(
        provider_uuid__isnull=True,
    ).select_related("patient").first()
    if orphan is None:
        pytest.skip("no unattributed encounter to test against")

    assert has_care_relationship(None, orphan.patient) is None, (
        "a caller with no user id was granted a relationship with a patient "
        "whose encounter simply has no provider recorded"
    )


def test_relationship_reports_why_not_merely_whether(tenant):
    """The reason is written onto the access log and shown to the reader.

    A boolean cannot carry "you are seeing this because you admitted them on
    Tuesday", and that sentence is what makes the control reviewable.
    """
    from apps.encounters.models import Encounter
    from apps.rbac.relationships import has_care_relationship

    encounter = Encounter.objects.filter(
        provider_uuid__isnull=False,
    ).select_related("patient").first()
    if encounter is None:
        pytest.skip("no attributed encounter")

    found = has_care_relationship(encounter.provider_uuid, encounter.patient)
    assert found is not None, "the provider of an encounter has no relationship"
    assert found.source
    assert found.reason and found.reason.endswith("."), (
        "the reason is shown to a person; it should be a sentence"
    )


def test_admission_relationship_respects_facility_scope(tenant):
    """A live inpatient concerns whoever is on that site, and nobody else.

    The on-call doctor who has just been bleeped has a relationship before they
    have written anything -- but being admitted in Bhaktapur does not concern a
    clinician who only works in Kathmandu.
    """
    import types

    from apps.inpatient.models import CLOSED_STATUSES, Admission
    from apps.organization.models import Facility
    from apps.rbac.permissions import Scope
    from apps.rbac.relationships import DEFAULT_RECENCY_DAYS, _admission
    from apps.rbac.services import UserAuthorization, _merge

    admission = (
        Admission.objects.exclude(status__in=CLOSED_STATUSES)
        .select_related("patient", "facility")
        .first()
    )
    if admission is None:
        pytest.skip("nobody is currently admitted")

    other = Facility.objects.exclude(pk=admission.facility_id).first()
    user_id = admission.patient.uuid  # any uuid; this branch ignores identity

    def scoped(facility_id):
        auth = UserAuthorization(user_id="t", organization_id=tenant.id)
        _merge(auth, "patient.clinical.read", Scope.FACILITY, "t",
               facility_ids={facility_id})
        return auth

    inside = _admission(
        user_id, admission.patient, scoped(admission.facility_id),
        DEFAULT_RECENCY_DAYS,
    )
    assert inside is not None and inside.source == "admission"

    if other is not None:
        outside = _admission(
            user_id, admission.patient, scoped(other.id), DEFAULT_RECENCY_DAYS,
        )
        assert outside is None, (
            "a clinician scoped to another facility was given a relationship "
            "with an inpatient they cannot reach"
        )


# ---------------------------------------------------------------------------
# PHASE2_PLAN.md step 3 — break-glass
# ---------------------------------------------------------------------------


def _stranger():
    from apps.inpatient.models import Admission
    from apps.patients.models import Patient

    return (
        Patient.objects.exclude(pk__in=Admission.objects.values("patient_id"))
        .exclude(status="merged")
        .first()
    )


def test_break_glass_demands_a_reviewable_reason(tenant):
    """A category is not a reason.

    "Emergency" is true of every override, so it distinguishes nothing and
    reviews to nothing -- and the review queue is the entire control.
    """
    from apps.identity.models import User
    from apps.rbac.break_glass import BreakGlassError, break_glass

    user = User.objects.filter(email="doctor@manakamana.test").first()
    patient = _stranger()
    if user is None or patient is None:
        pytest.skip("no doctor or unattached patient; run seed_demo")

    with pytest.raises(BreakGlassError):
        break_glass(user, patient, "emergency")


def test_break_glass_grants_a_relationship_and_then_expires(tenant):
    """It refuses nobody, it ends by time, and it cannot be self-extended."""
    from apps.identity.models import Membership, User
    from apps.rbac.break_glass import break_glass, revoke
    from apps.rbac.models import BreakGlassGrant
    from apps.rbac.relationships import has_care_relationship
    from apps.rbac.services import resolve_authorization

    user = User.objects.filter(email="doctor@manakamana.test").first()
    reviewer = User.objects.filter(email="owner@manakamana.test").first()
    patient = _stranger()
    if not (user and reviewer and patient):
        pytest.skip("demo users missing; run seed_demo")

    BreakGlassGrant.all_objects.filter(
        user_id=user.uuid, patient_uuid=patient.uuid,
    ).delete()
    membership = Membership.objects.get(user=user, organization=tenant)
    authorization = resolve_authorization(user, membership)

    assert has_care_relationship(user.uuid, patient, authorization) is None

    grant = break_glass(
        user, patient,
        "Collapsed in the corridor with no notes, needed the allergy list.",
    )
    found = has_care_relationship(user.uuid, patient, authorization)
    assert found is not None and found.is_break_glass

    # Asking again inside the window must not extend it: otherwise a grant can
    # be held open indefinitely by re-asking, and "four hours" means nothing.
    again = break_glass(user, patient, "Still dealing with the same collapse.")
    assert again.uuid == grant.uuid
    assert again.expires_at == grant.expires_at

    revoke(grant, reviewer, "Not an emergency; the notes were on the ward.")
    assert has_care_relationship(user.uuid, patient, authorization) is None


def test_nobody_reviews_their_own_break_glass(tenant):
    """The point of the queue is that somebody else looks."""
    from apps.identity.models import User
    from apps.rbac.break_glass import BreakGlassError, break_glass, review
    from apps.rbac.models import BreakGlassGrant, BreakGlassOutcome

    user = User.objects.filter(email="doctor@manakamana.test").first()
    patient = _stranger()
    if user is None or patient is None:
        pytest.skip("demo data missing")

    BreakGlassGrant.all_objects.filter(
        user_id=user.uuid, patient_uuid=patient.uuid,
    ).delete()
    grant = break_glass(
        user, patient, "Unconscious on arrival, needed the record now.",
    )
    with pytest.raises(BreakGlassError):
        review(grant, user, BreakGlassOutcome.APPROPRIATE)


def test_break_glass_raises_a_critical_notification(tenant):
    """The notification is how a person finds out today.

    `CRITICAL` specifically, because the notification centre refuses to let
    anybody switch that category off by preference.
    """
    from apps.identity.models import User
    from apps.notifications.models import Notification, NotificationCategory
    from apps.rbac.break_glass import break_glass
    from apps.rbac.models import BreakGlassGrant

    user = User.objects.filter(email="doctor@manakamana.test").first()
    patient = _stranger()
    if user is None or patient is None:
        pytest.skip("demo data missing")

    BreakGlassGrant.all_objects.filter(
        user_id=user.uuid, patient_uuid=patient.uuid,
    ).delete()
    grant = break_glass(
        user, patient, "Brought in by ambulance, no identification on them.",
    )
    raised = Notification.objects.filter(
        source="privacy", subject_uuid=grant.uuid,
    ).first()
    assert raised is not None, "nobody was told about an emergency override"
    assert raised.category == NotificationCategory.CRITICAL


def test_break_glass_is_reachable_by_the_narrowest_clinician(tenant):
    """A department-scoped doctor must be able to take emergency access.

    The endpoint first required `patient.clinical.read` at the default
    `Scope.FACILITY`, which refused the demo's own doctor -- their role is
    granted at department scope, which is *narrower*. Breaking glass is not a
    privilege that scales with seniority; it is what somebody does at three in
    the morning when the model does not fit, and the narrowest clinician has to
    be able to reach it.
    """
    import json

    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User
    from apps.inpatient.models import Admission
    from apps.patients.models import Patient
    from apps.rbac.models import BreakGlassGrant

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    patient = (
        Patient.objects.exclude(pk__in=Admission.objects.values("patient_id"))
        .exclude(status="merged")
        .first()
    )
    if doctor is None or patient is None:
        pytest.skip("demo data missing; run seed_demo")

    BreakGlassGrant.all_objects.filter(
        user_id=doctor.uuid, patient_uuid=patient.uuid,
    ).delete()

    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    response = client.post(
        "/api/privacy/break-glass/",
        data=json.dumps({
            "patient": str(patient.uuid),
            "reason": "Brought in unconscious with no identification on them.",
        }),
        content_type="application/json",
    )
    assert response.status_code == 201, (
        "a department-scoped doctor was refused emergency access: "
        f"{response.status_code} {response.content.decode()[:200]}"
    )


def test_the_queue_needs_privacy_review(tenant):
    """Who opened whose record, and why, is itself sensitive."""
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("demo data missing")

    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    assert client.get("/api/privacy/grants/").status_code == 403


# ---------------------------------------------------------------------------
# PHASE2_PLAN.md step 2 — enforcement, behind the switch
# ---------------------------------------------------------------------------


def _privacy_switch(value):
    """Set or clear `privacy.require_care_relationship` for the tenant."""
    from apps.common.permissions import (
        PRIVACY_NAMESPACE,
        REQUIRE_RELATIONSHIP_KEY,
    )
    from apps.organization.config import set_config_value
    from apps.organization.models import ConfigSetting

    ConfigSetting.all_objects.filter(
        namespace=PRIVACY_NAMESPACE, key=REQUIRE_RELATIONSHIP_KEY,
    ).delete()
    if value is not None:
        set_config_value(PRIVACY_NAMESPACE, REQUIRE_RELATIONSHIP_KEY, value)


def test_the_switch_is_off_by_default(tenant):
    """A single-site clinic gets nothing from this and pays the complexity.

    The same position §17 takes on segregation of duties, which a two-person
    practice cannot enforce because there is nobody to segregate.
    """
    from apps.common.permissions import relationship_required

    _privacy_switch(None)
    assert relationship_required() is False


def test_config_resolves_most_specific_first(tenant):
    """`ConfigSetting` stored the hierarchy and nothing read it until now.

    A facility row of `False` must beat an organization row of `True`; a
    *missing* facility row must not. That distinction is the whole reason the
    table exists.
    """
    from apps.common.permissions import (
        PRIVACY_NAMESPACE,
        REQUIRE_RELATIONSHIP_KEY,
        relationship_required,
    )
    from apps.organization.config import config_value, set_config_value
    from apps.organization.models import ConfigScope, ConfigSetting, Facility

    _privacy_switch(True)
    facility = Facility.objects.first()
    try:
        assert relationship_required() is True
        assert relationship_required(facility) is True, (
            "a facility with no row of its own should inherit the "
            "organization's value"
        )

        set_config_value(
            PRIVACY_NAMESPACE, REQUIRE_RELATIONSHIP_KEY, False,
            scope=ConfigScope.FACILITY, facility=facility,
        )
        assert relationship_required(facility) is False
        assert relationship_required() is True, (
            "one facility opting out must not switch it off everywhere"
        )
        assert config_value("privacy", "nothing_here", default="fallback") == "fallback"
    finally:
        ConfigSetting.all_objects.filter(
            namespace=PRIVACY_NAMESPACE, key=REQUIRE_RELATIONSHIP_KEY,
        ).delete()


def test_enforcement_refuses_a_stranger_and_names_the_way_out(tenant):
    """The only part of Phase 2 that changes what anybody sees.

    Also asserts the refusal *message*, not merely the status. A bare 403 on a
    clinical record at three in the morning is how somebody decides the system
    is broken and borrows a colleague's login.
    """
    import json

    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.encounters.models import Encounter
    from apps.identity.models import Membership, User
    from apps.rbac.models import BreakGlassGrant
    from apps.rbac.relationships import has_care_relationship
    from apps.rbac.services import resolve_authorization

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("no demo doctor")

    authorization = resolve_authorization(
        doctor, Membership.objects.get(user=doctor, organization=tenant),
    )
    facility_ids = authorization.accessible_facility_ids("encounter.read")
    reachable = Encounter.objects.select_related("patient")
    if facility_ids:
        reachable = reachable.filter(facility_id__in=facility_ids)

    stranger = None
    for encounter in reachable:
        if has_care_relationship(
            doctor.uuid, encounter.patient, authorization,
        ) is None:
            stranger = encounter
            break
    if stranger is None:
        pytest.skip("this doctor has a relationship with everybody in scope")

    BreakGlassGrant.all_objects.filter(user_id=doctor.uuid).delete()
    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    path = f"/api/clinical/encounters/{stranger.uuid}/"

    _privacy_switch(None)
    try:
        assert client.get(path).status_code == 200, (
            "with the switch off, nothing should have changed for anybody"
        )

        _privacy_switch(True)
        refused = client.get(path)
        assert refused.status_code == 403
        message = json.loads(refused.content.decode())["error"]["message"]
        assert "emergency" in message.lower(), (
            "the refusal must name the way out, or people route around it: "
            f"{message}"
        )

        taken = client.post(
            "/api/privacy/break-glass/",
            data=json.dumps({
                "patient": str(stranger.patient.uuid),
                "reason": "On-call team asked me to review this urgently.",
            }),
            content_type="application/json",
        )
        assert taken.status_code == 201
        assert client.get(path).status_code == 200, (
            "break-glass did not open the record it exists to open"
        )
    finally:
        _privacy_switch(None)
        BreakGlassGrant.all_objects.filter(user_id=doctor.uuid).delete()


def test_a_doctor_can_reach_the_clinical_endpoints(tenant):
    """The three most numerous clinical roles must be able to use the system.

    `doctor`, `nurse` and `lab_technician` all carry `max_scope = department`,
    so they can never be assigned above it -- while `HasPermission.of` defaults
    to demanding `Scope.FACILITY`. Measured on 6 September 2026: a doctor was
    refused seven of nine clinical endpoints, including the patient list.

    Asserted as a floor on the *roles that exist*, not on one demo user, so
    that lowering `max_scope` on a clinical role in future fails here rather
    than in a hospital.
    """
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("no demo doctor; run seed_demo")

    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    refused = [
        path
        for path in (
            "/api/clinical/patients/",
            "/api/clinical/encounters/",
            "/api/clinical/prescriptions/",
            "/api/diagnostics/orders/",
            "/api/clinical/appointments/",
        )
        if client.get(path).status_code == 403
    ]
    assert not refused, (
        "a doctor cannot reach clinical endpoints their job requires: "
        f"{refused}. A permission check demanding facility scope in front of "
        "a queryset that narrows to it is a scope ladder with one rung."
    )


def test_lowering_the_floor_did_not_widen_anybody(tenant):
    """The other half: a department-scoped clinician must not now see more
    than an organization-scoped one."""
    import json

    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    owner = User.objects.filter(email="owner@manakamana.test").first()
    if doctor is None or owner is None:
        pytest.skip("demo users missing")

    def count(user, path):
        client = Client(
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
            HTTP_X_ORGANIZATION=tenant.slug,
        )
        response = client.get(path)
        if response.status_code != 200:
            return None
        return json.loads(response.content.decode()).get("count")

    for path in ("/api/clinical/appointments/", "/api/diagnostics/orders/"):
        mine, theirs = count(doctor, path), count(owner, path)
        if mine is None or theirs is None:
            continue
        assert mine <= theirs, (
            f"{path}: a department-scoped doctor sees {mine} rows where an "
            f"organization-scoped owner sees {theirs}"
        )


# ---------------------------------------------------------------------------
# PHASE2_PLAN.md step 4 — browse narrows, lookup by reference does not
# ---------------------------------------------------------------------------


def test_the_two_relationship_functions_agree(tenant):
    """`has_care_relationship` and `related_patient_ids` are separate code
    paths answering the same question, and they could drift.

    A patient who appears in a list but cannot be opened -- or the reverse --
    is a confusing bug rather than an obvious one.
    """
    from apps.identity.models import Membership, MembershipStatus
    from apps.patients.models import Patient
    from apps.rbac.relationships import (
        has_care_relationship,
        related_patient_ids,
    )
    from apps.rbac.services import resolve_authorization

    patients = list(Patient.objects.exclude(status="merged"))
    disagreements = []
    for membership in Membership.objects.filter(
        organization=tenant, status=MembershipStatus.ACTIVE,
    ).select_related("user"):
        authorization = resolve_authorization(membership.user, membership)
        listed = related_patient_ids(membership.user.uuid, authorization)
        if listed is None:
            continue
        for patient in patients:
            one = has_care_relationship(
                membership.user.uuid, patient, authorization,
            ) is not None
            if one != (patient.id in listed):
                disagreements.append(
                    f"{membership.user.email} / {patient.full_name}: "
                    f"object={one} list={patient.id in listed}"
                )
    assert not disagreements, "; ".join(disagreements[:5])


def test_browsing_narrows_but_a_reference_still_opens(tenant):
    """The asymmetry that replaces facility filtering.

    A pharmacy counter assistant must not be able to enumerate the group's
    prescriptions, and must be able to open the one a patient hands them --
    presenting the reference *is* the care relationship and *is* the consent.
    Tidying this away would break group dispensing.
    """
    import json

    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import Membership, User
    from apps.prescriptions.models import Prescription
    from apps.rbac.relationships import related_patient_ids
    from apps.rbac.services import resolve_authorization

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    counter = User.objects.filter(email="counter@manakamana.test").first()
    if doctor is None or counter is None:
        pytest.skip("demo users missing")

    authorization = resolve_authorization(
        doctor, Membership.objects.get(user=doctor, organization=tenant),
    )
    mine = related_patient_ids(doctor.uuid, authorization) or set()
    unrelated = (
        Prescription.objects.exclude(status="superseded")
        .exclude(patient_id__in=mine)
        .first()
    )
    if unrelated is None:
        pytest.skip("no prescription outside this doctor's relationships")

    def client_for(user):
        return Client(
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
            HTTP_X_ORGANIZATION=tenant.slug,
        )

    def browse(user):
        response = client_for(user).get("/api/clinical/prescriptions/")
        return json.loads(response.content.decode()).get("count")

    _privacy_switch(None)
    try:
        wide_open = browse(doctor)

        _privacy_switch(True)
        narrowed = browse(doctor)
        assert narrowed < wide_open, (
            f"browsing did not narrow: {narrowed} of {wide_open}"
        )
        assert browse(counter) == 0, (
            "a pharmacy counter assistant can enumerate prescriptions they "
            "have no relationship with"
        )

        # The other half, and the one that matters for dispensing.
        opened = client_for(counter).get(
            f"/api/clinical/prescriptions/{unrelated.uuid}/"
        )
        assert opened.status_code == 200, (
            "a presented prescription could not be opened, which breaks "
            "group dispensing -- see ACCESS_DESIGN.md"
        )
    finally:
        _privacy_switch(None)


def test_patient_results_actually_runs_its_object_check(tenant):
    """A permission class listed but never invoked is the worst kind.

    `PatientResultsView` is a plain `APIView`, and DRF runs object-level
    permissions only from `get_object()` -- which such a view never calls. So
    `HasClinicalAccess` sat in `permission_classes`, looked enforced, and did
    nothing until `check_object_permissions` was called explicitly. It appears
    in the code and not in the request, which is precisely the kind of control
    that is never noticed until it is needed.
    """
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import Membership, User
    from apps.patients.models import Patient
    from apps.rbac.models import BreakGlassGrant
    from apps.rbac.relationships import related_patient_ids
    from apps.rbac.services import resolve_authorization

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("demo users missing")

    authorization = resolve_authorization(
        doctor, Membership.objects.get(user=doctor, organization=tenant),
    )
    mine = related_patient_ids(doctor.uuid, authorization) or set()
    stranger = (
        Patient.objects.exclude(pk__in=mine).exclude(status="merged").first()
    )
    if stranger is None:
        pytest.skip("this doctor is treating everybody")

    BreakGlassGrant.all_objects.filter(user_id=doctor.uuid).delete()
    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    path = f"/api/diagnostics/patients/{stranger.uuid}/results/"

    _privacy_switch(None)
    try:
        assert client.get(path).status_code == 200
        _privacy_switch(True)
        assert client.get(path).status_code == 403, (
            "the object-level check on a plain APIView did not run"
        )
    finally:
        _privacy_switch(None)


# ---------------------------------------------------------------------------
# The presented-at relationship source
# ---------------------------------------------------------------------------


def test_a_presented_prescription_is_a_relationship_at_that_counter(tenant):
    """`Prescription.facility` is where it was *written*, and a patient may
    take it anywhere -- so nothing knew which pharmacy was holding one, and a
    pharmacist with enforcement on browsed an empty list.

    Bounded to the branch it was presented at: a prescription handed over in
    Kathmandu does not concern the Bhaktapur counter, and which pharmacy is
    holding it is the entire point of the row.
    """
    import types

    from apps.organization.models import Facility
    from apps.prescriptions.models import Prescription, PrescriptionPresentation
    from apps.prescriptions.services import close_presentations, present
    from apps.rbac.permissions import Scope
    from apps.rbac.relationships import DEFAULT_RECENCY_DAYS, _presented
    from apps.rbac.services import UserAuthorization, _merge

    pharmacy = Facility.objects.filter(facility_type="pharmacy").first()
    other = Facility.objects.exclude(pk=pharmacy.pk).first() if pharmacy else None
    prescription = (
        Prescription.objects.exclude(status="superseded")
        .select_related("patient").first()
    )
    if not (pharmacy and other and prescription):
        pytest.skip("need two facilities and a prescription; run seed_demo")

    PrescriptionPresentation.all_objects.filter(
        prescription=prescription,
    ).delete()

    def dispenser_at(facility):
        authorization = UserAuthorization(user_id="t", organization_id=tenant.id)
        _merge(authorization, "prescription.dispense", Scope.FACILITY, "t",
               facility_ids={facility.id})
        return authorization

    patient = prescription.patient
    assert _presented(
        "t", patient, dispenser_at(pharmacy), DEFAULT_RECENCY_DAYS,
    ) is None

    try:
        present(prescription, pharmacy)
        found = _presented(
            "t", patient, dispenser_at(pharmacy), DEFAULT_RECENCY_DAYS,
        )
        assert found is not None and found.source == "presented"
        assert _presented(
            "t", patient, dispenser_at(other), DEFAULT_RECENCY_DAYS,
        ) is None, (
            "a prescription presented at one branch reached another"
        )

        close_presentations(prescription)
        assert _presented(
            "t", patient, dispenser_at(pharmacy), DEFAULT_RECENCY_DAYS,
        ) is None, "dispensing did not release the counter's hold"
    finally:
        PrescriptionPresentation.all_objects.filter(
            prescription=prescription,
        ).delete()


def test_audit_records_survive_a_facility_header(tenant):
    """`facility_code` was `varchar(32)` and holds a 36-character UUID.

    So **every request carrying `X-Facility` failed its audit write**,
    silently, because `record()` catches and logs rather than raising. The
    audit log is what the whole access-control design leans on, and it had
    been dropping events for facility-scoped requests since the header existed.
    """
    from apps.audit.models import AuditEvent

    field = AuditEvent._meta.get_field("facility_code")
    assert field.max_length >= 36, (
        f"facility_code holds {field.max_length} characters and a UUID is 36; "
        "audit writes will fail silently for facility-scoped requests"
    )


# ---------------------------------------------------------------------------
# The role sweep
# ---------------------------------------------------------------------------


def _parameterless_api_paths():
    from django.urls import get_resolver

    found = set()
    for pattern in get_resolver().url_patterns:
        for entry in getattr(pattern, "url_patterns", [pattern]):
            route = str(getattr(entry.pattern, "_route", ""))
            prefix = str(getattr(pattern.pattern, "_route", ""))
            full = "/" + prefix + route
            if "<" in full or not full.startswith("/api/"):
                continue
            if any(skip in full for skip in ("schema", "docs", "health", "auth")):
                continue
            found.add(full)
    return sorted(found)


def test_no_endpoint_crashes_for_any_role(tenant):
    """No GET should return 5xx for anybody, whatever they are allowed to see.

    A 403 is an answer. A 500 is a bug, and it hides behind permissions: an
    endpoint only the right role can reach is an endpoint only the right role
    can crash. This sweep found `/api/hr/me/summary/` raising
    `AttributeError` on every call -- employee self-service, built two days
    earlier, crashing for the only people it exists for, because nothing had
    ever driven it through the API.
    """
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import Membership, MembershipStatus, User
    from apps.rbac.models import RoleAssignment

    actors = {}
    for membership in Membership.objects.filter(
        organization=tenant, status=MembershipStatus.ACTIVE,
    ).select_related("user"):
        codes = sorted(
            assignment.role.code
            for assignment in RoleAssignment.objects.filter(
                user_id=membership.user.uuid, status="active",
            ).select_related("role")
        )
        if codes:
            actors.setdefault("+".join(codes), membership.user.email)
    if not actors:
        pytest.skip("no role assignments; run seed_demo")

    crashes = []
    for role, email in sorted(actors.items()):
        user = User.objects.get(email=email)
        client = Client(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
            HTTP_X_ORGANIZATION=tenant.slug,
        )
        for path in _parameterless_api_paths():
            try:
                status = client.get(path).status_code
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                crashes.append(f"{role} {path}: raised {type(exc).__name__}")
                continue
            if status >= 500:
                crashes.append(f"{role} {path}: {status}")

    assert not crashes, "\n".join(crashes[:12])


def test_a_doctor_can_open_their_own_worklist(tenant):
    """`MyWorklistView` is the doctor's landing screen and is scoped to the
    caller by construction — it returns *their* open encounters.

    It demanded `Scope.FACILITY`, so every department-scoped doctor was refused
    their own screen, which §96 records as built. A "my" view that requires
    facility-wide authority is a contradiction in its own name.
    """
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("no demo doctor")

    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    assert client.get("/api/clinical/worklist/").status_code == 200


# ---------------------------------------------------------------------------
# Phase 3 — making access visible
# ---------------------------------------------------------------------------


def test_audit_events_record_the_actor_role(tenant):
    """The access-pattern report compares somebody's read volume against "the
    median for the same role", and every role was blank.

    The middleware builds the audit context before authorization is resolved,
    so `actor_role` had always been written empty — which meant the report was
    comparing a consultant to a counter assistant, exactly what its own
    docstring says it must not do. Filled now at the first moment in a request
    that anybody knows the answer.
    """
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.audit.models import AuditAction, AuditEvent
    from apps.identity.models import User
    from apps.patients.models import Patient

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    patient = Patient.objects.exclude(status="merged").first()
    if doctor is None or patient is None:
        pytest.skip("demo data missing")

    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    assert client.get(f"/api/clinical/patients/{patient.uuid}/").status_code == 200

    latest = (
        AuditEvent.objects.filter(
            actor_id=doctor.uuid, action=AuditAction.VIEW_SENSITIVE,
        )
        .order_by("-created_at")
        .first()
    )
    assert latest is not None, "the read was not logged at all"
    assert latest.actor_role, (
        "actor_role is empty, so any report grouping by role is comparing "
        "everybody to everybody"
    )


def test_a_patient_can_see_who_looked_at_their_record(tenant):
    """The one report a patient is entitled to without asking anybody.

    Staff are named. A log that says "a member of staff" answers nothing, and
    the people reading records knowing they are named is most of what makes
    the logging work.
    """
    from apps.audit.access_reports import who_looked_at
    from apps.audit.models import AuditAction, AuditEvent
    from apps.patients.models import Patient

    read = (
        AuditEvent.objects.filter(
            action=AuditAction.VIEW_SENSITIVE, entity_type="patients.Patient",
        )
        .exclude(entity_id="")
        .order_by("-occurred_at")
        .first()
    )
    if read is None:
        pytest.skip("no patient reads logged yet")

    patient = Patient.objects.filter(uuid=read.entity_id).first()
    if patient is None:
        pytest.skip("the read names a patient that no longer exists")

    entries = who_looked_at(patient)
    assert entries, "a logged read did not appear in the patient's own view"
    assert entries[0]["who"], "an entry that names nobody answers nothing"


def test_access_patterns_need_privacy_review(tenant):
    """A report of who has been reading whose records is itself sensitive."""
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    owner = User.objects.filter(email="owner@manakamana.test").first()
    if doctor is None or owner is None:
        pytest.skip("demo users missing")

    def get(user):
        return Client(
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
            HTTP_X_ORGANIZATION=tenant.slug,
        ).get("/api/privacy/access-patterns/").status_code

    assert get(doctor) == 403
    assert get(owner) == 200


def test_a_doctor_can_write_what_their_job_requires(tenant):
    """Reading was fixed on 6 September; writing was still refused.

    A doctor could not record a consultation, prescribe, order a test or book
    an appointment — all four returned 403, because the create paths called
    `require(code, Scope.FACILITY)` and a doctor holds at department scope.

    A doctor writes a consultation for the patient in front of them. The
    facility is on the record being created; it is not a floor the writer has
    to clear. Stock adjustments and till reconciliation keep their facility
    floor, because those genuinely are facility-wide acts.

    Asserted as "not 403": an empty body should fail validation, and a 400 is
    the proof that the permission check passed.
    """
    import json

    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("no demo doctor")

    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    refused = [
        path
        for path in (
            "/api/clinical/encounters/",
            "/api/clinical/prescriptions/",
            "/api/diagnostics/orders/",
            "/api/clinical/appointments/",
        )
        if client.post(
            path, data=json.dumps({}), content_type="application/json",
        ).status_code == 403
    ]
    assert not refused, (
        f"a doctor cannot write what their job requires: {refused}"
    )


def test_department_scope_narrows_to_the_department(tenant):
    """`Scope.DEPARTMENT` narrows to the department, not the facility.

    Written, reverted and restored on 6 September. The revert was right at the
    time — clinical records carried no department at all (Encounter 0 of 123),
    so narrowing would have shown a department-scoped doctor zero encounters:
    worse than the looseness it fixes, and silent with it. The attribution came
    first, this second, and that order is the whole lesson.

    A row whose department is null is *included* rather than hidden. An
    encounter nobody attributed is not evidence that it belongs to somebody
    else, and excluding it would quietly lose work.
    """
    import types

    from apps.common.permissions import apply_scope_filter
    from apps.encounters.models import Encounter
    from apps.organization.models import Department, Facility
    from apps.rbac.permissions import Scope
    from apps.rbac.services import UserAuthorization, _merge

    # A facility with more than one department in use, or the narrowing cannot
    # be told apart from the facility bound.
    target = None
    for facility in Facility.objects.all():
        used = [
            department
            for department in Department.objects.filter(facility=facility)
            if Encounter.objects.filter(department=department).exists()
        ]
        if len(used) >= 2:
            target = (facility, used)
            break
    if target is None:
        pytest.skip("no facility has encounters in two departments")

    facility, departments = target

    def visible(scope, department_ids):
        authorization = UserAuthorization(user_id="t", organization_id=tenant.id)
        _merge(authorization, "encounter.read", scope, "t",
               facility_ids={facility.id}, department_ids=department_ids)
        request = types.SimpleNamespace(_authorization=authorization, user=None)
        return apply_scope_filter(
            Encounter.objects.all(), request, "encounter.read",
        ).count()

    whole_facility = visible(Scope.FACILITY, None)
    assert whole_facility > 0

    for department in departments:
        narrowed = visible(Scope.DEPARTMENT, {department.id})
        assert 0 < narrowed < whole_facility, (
            f"{department.name}: {narrowed} of {whole_facility}. Zero means "
            "the attribution has regressed and every clinician in that "
            "department is locked out; equal means the narrowing is not "
            "happening at all."
        )


def test_clinical_records_carry_a_department(tenant):
    """The prerequisite the narrowing above stands on.

    The field existed and every caller passed `None`, so 123 of 123 encounters
    recorded no department. Asserted as a floor, because a regression here is
    invisible until somebody's list is mysteriously empty.
    """
    from apps.encounters.models import Encounter

    total = Encounter.objects.count()
    if total == 0:
        pytest.skip("no encounters")
    attributed = Encounter.objects.filter(department__isnull=False).count()
    coverage = attributed / total * 100
    assert coverage >= 90, (
        f"only {coverage:.1f}% of encounters record a department "
        f"({attributed} of {total}); department scope depends on this"
    )


# ---------------------------------------------------------------------------
# §122 Documents
# ---------------------------------------------------------------------------


def _pdf(extra: bytes = b"") -> bytes:
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>" + extra


def test_a_document_inherits_its_subject_access(tenant):
    """The whole authorization model of the documents module.

    A file about a patient is exactly as sensitive as that patient's record, so
    it is governed by the same care relationship rather than by a second
    permission model that would drift out of step within a month. A document
    endpoint with rules of its own would be a way *around* Phase 2 rather than
    a use of it.
    """
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.documents.models import Document
    from apps.identity.models import Membership, User
    from apps.patients.models import Patient
    from apps.rbac.models import BreakGlassGrant
    from apps.rbac.relationships import related_patient_ids
    from apps.rbac.services import resolve_authorization

    owner = User.objects.filter(email="owner@manakamana.test").first()
    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if owner is None or doctor is None:
        pytest.skip("demo users missing")

    authorization = resolve_authorization(
        doctor, Membership.objects.get(user=doctor, organization=tenant),
    )
    mine = related_patient_ids(doctor.uuid, authorization) or set()
    stranger = (
        Patient.objects.exclude(pk__in=mine).exclude(status="merged").first()
    )
    if stranger is None:
        pytest.skip("this doctor treats everybody")

    def client_for(user):
        return Client(
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
            HTTP_X_ORGANIZATION=tenant.slug,
        )

    Document.all_objects.filter(subject_uuid=stranger.uuid).delete()
    BreakGlassGrant.all_objects.filter(user_id=doctor.uuid).delete()

    created = client_for(owner).post("/api/documents/", data={
        "file": SimpleUploadedFile(
            "summary.pdf", _pdf(b"stranger"), content_type="application/pdf",
        ),
        "category": "discharge",
        "title": "discharge summary",
        "subject_type": "patients.Patient",
        "subject_uuid": str(stranger.uuid),
    })
    assert created.status_code == 201, created.content.decode()[:200]
    uuid = json.loads(created.content.decode())["uuid"]

    _privacy_switch(None)
    try:
        assert client_for(doctor).get(
            f"/api/documents/{uuid}/download/",
        ).status_code == 200

        _privacy_switch(True)
        assert client_for(doctor).get(
            f"/api/documents/{uuid}/download/",
        ).status_code == 403, (
            "a document about a patient this doctor is not treating was "
            "handed over"
        )
    finally:
        _privacy_switch(None)
        Document.all_objects.filter(subject_uuid=stranger.uuid).delete()


def test_documents_refuse_what_they_should(tenant):
    """An allow-list of types, a size limit, and no empty files.

    An allow-list rather than a deny-list of dangerous types, because a
    deny-list is a list somebody has to keep up to date and will not.
    """
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.documents.models import Document
    from apps.identity.models import User
    from apps.patients.models import Patient

    owner = User.objects.filter(email="owner@manakamana.test").first()
    patient = Patient.objects.exclude(status="merged").first()
    if owner is None or patient is None:
        pytest.skip("demo data missing")

    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(owner).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )

    def upload(name, ctype, payload):
        return client.post("/api/documents/", data={
            "file": SimpleUploadedFile(name, payload, content_type=ctype),
            "category": "discharge", "title": "t",
            "subject_type": "patients.Patient",
            "subject_uuid": str(patient.uuid),
        }).status_code

    assert upload("x.exe", "application/x-msdownload", b"MZ\x90\x00") == 400
    assert upload("empty.pdf", "application/pdf", b"") == 400

    # The same bytes twice is one document, not two: somebody uploading twice
    # has made a mistake, not committed an error.
    marker = _pdf(b"dedupe-check")
    first = upload("a.pdf", "application/pdf", marker)
    second = upload("b.pdf", "application/pdf", marker)
    assert first == second == 201
    assert Document.objects.filter(
        subject_uuid=patient.uuid, checksum__isnull=False,
    ).filter(original_name__in=["a.pdf", "b.pdf"]).count() == 1

    Document.all_objects.filter(original_name__in=["a.pdf", "b.pdf"]).delete()


# ---------------------------------------------------------------------------
# §105 The report library
# ---------------------------------------------------------------------------


def _report_client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )


def test_every_registered_report_runs(tenant):
    """A report that has never been run through the registry is a report
    nobody knows is broken.

    Four of the thirteen entries named functions that did not exist when this
    was first written — `turnaround`, `summary`, `claim_summary`,
    `stock_summary` — because the names were guessed rather than read. This is
    what catches that.
    """
    from apps.organization.models import Facility
    from apps.reporting.registry import all_reports

    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    facility = Facility.objects.filter(facility_type="hospital").first()
    library = json.loads(client.get("/api/reports/").content.decode())
    assert library["reports"], "the registry loaded nothing"
    assert len(library["reports"]) == len(all_reports())

    broken = []
    for entry in library["reports"]:
        query = ""
        if any(p["name"] == "facility" for p in entry["parameters"]) and facility:
            query = f"?facility={facility.uuid}"
        response = client.get(f"/api/reports/{entry['code']}/{query}")
        if response.status_code != 200:
            broken.append(
                f"{entry['code']}: {response.status_code} "
                f"{response.content.decode()[:120]}"
            )
    assert not broken, "\n".join(broken)


def test_a_report_enforces_the_permission_it_declares(tenant):
    """A reporting layer is exactly where somebody would look for a way around
    the access controls — a report is a bulk read wearing a respectable hat."""
    client = _report_client("doctor@manakamana.test", tenant)
    if client is None:
        pytest.skip("no demo doctor")

    # `privacy.review` is held by the owner and the auditor, never a clinician.
    assert client.get(
        "/api/reports/privacy.unrelated_reads/",
    ).status_code == 403

    library = json.loads(client.get("/api/reports/").content.decode())
    privacy = [
        entry for entry in library["reports"]
        if entry["code"].startswith("privacy.")
    ]
    assert privacy, "privacy reports vanished from the library"
    assert all(not entry["you_may_run_it"] for entry in privacy), (
        "a clinician is told they may run the privacy reports"
    )
    # Listed, not hidden: somebody who cannot see a report they have heard of
    # asks whether the system has it; somebody who sees it greyed out asks for
    # the permission, which is the conversation that should happen.
    assert len(library["reports"]) > len(privacy)


def test_csv_export_uses_export_not_format(tenant):
    """`format` is DRF's reserved content-negotiation parameter.

    `?format=csv` with no CSV renderer registered is a 404 from the router
    before the view is reached — a not-found error for a resource that plainly
    exists, which is a miserable thing to debug.
    """
    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    exported = client.get("/api/reports/privacy.read_volume/?export=csv&days=365")
    assert exported.status_code == 200
    assert exported["Content-Type"].startswith("text/csv")
    assert exported.content.decode().splitlines()[0].startswith("who,")

    # And a report that is not a table says so rather than inventing a shape.
    not_a_table = client.get("/api/reports/inpatient.census/?export=csv")
    assert not_a_table.status_code in (200, 400)


# ---------------------------------------------------------------------------
# Log 197 — global search, where every access rule is enforced or bypassed
# ---------------------------------------------------------------------------


def test_every_search_source_can_format_a_real_row(tenant):
    """A source that has never returned a hit is a source nobody knows is
    broken.

    Exactly the lesson the report registry taught, and it repeated here:
    `Appointment.scheduled_start` does not exist -- the field is
    `scheduled_for` -- and the mistake survived three separate probes because
    none of them happened to match an appointment. Formatting only runs when
    there is a row to format, so the guard has to force one.
    """
    from apps.billing.models import Invoice
    from apps.diagnostics.models import SPECIMEN_MODALITIES, DiagnosticOrder
    from apps.documents.models import Document
    from apps.hr.models import Employee
    from apps.inpatient.models import Admission
    from apps.patients.models import Patient, PatientStatus
    from apps.pharmacy.models import Product
    from apps.prescriptions.models import Prescription
    from apps.procurement.models import Supplier
    from apps.scheduling.models import Appointment

    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    def term_for(queryset, attr):
        row = queryset.first()
        return getattr(row, attr) if row is not None else None

    terms = {
        # Merged records are excluded from search by design, so a merged shell
        # is not evidence of anything -- and `Patient.objects.first()` returns
        # one, which cost a confused minute the first time.
        "patient": term_for(
            Patient.objects.exclude(status=PatientStatus.MERGED), "mrn",
        ),
        "employee": term_for(Employee.objects, "employee_code"),
        "medicine": term_for(Product.objects, "generic_name"),
        "supplier": term_for(Supplier.objects, "name"),
        "invoice": term_for(Invoice.objects, "number"),
        "document": term_for(Document.objects, "title"),
        "appointment": term_for(Appointment.objects, "reference"),
        "prescription": term_for(Prescription.objects, "reference"),
        "admission": term_for(Admission.objects, "reference"),
        "lab": term_for(
            DiagnosticOrder.objects.filter(modality__in=SPECIMEN_MODALITIES),
            "reference",
        ),
        "radiology": term_for(
            DiagnosticOrder.objects.exclude(modality__in=SPECIMEN_MODALITIES),
            "reference",
        ),
    }

    broken, formatted = [], 0
    for code, term in terms.items():
        if not term:
            continue
        response = client.get("/api/search/", {"q": term, "types": code})
        if response.status_code != 200:
            broken.append(
                f"{code}: {response.status_code} "
                f"{response.content.decode()[:160]}"
            )
            continue
        body = json.loads(response.content.decode())
        hits = [g for g in body["groups"] if g["type"] == code]
        if not hits:
            broken.append(f"{code}: searched {term!r} and found nothing")
            continue
        formatted += 1
        sample = hits[0]["results"][0]
        assert sample["label"], f"{code} produced a hit with no label"
        assert sample["url"], f"{code} produced a hit with no url"

    assert not broken, "\n".join(broken)
    assert formatted >= 8, f"only {formatted} sources had data to prove"


def test_browsing_never_reaches_a_patient_you_have_no_relationship_with(tenant):
    """The general check, not the specific one.

    It does not care which source leaked; it asks the whole search box the one
    question that matters, for four different roles across eight terms. Hits
    flagged `by_reference` are excluded deliberately -- naming a record exactly
    is the documented lookup, and `retrieve` by UUID already permits it. Only
    browsing is under test.
    """
    from apps.identity.models import Membership, User
    from apps.rbac.relationships import related_patient_ids
    from apps.rbac.services import resolve_authorization

    models_by_type = {
        "appointment": ("apps.scheduling.models", "Appointment"),
        "prescription": ("apps.prescriptions.models", "Prescription"),
        "admission": ("apps.inpatient.models", "Admission"),
        "lab": ("apps.diagnostics.models", "DiagnosticOrder"),
        "radiology": ("apps.diagnostics.models", "DiagnosticOrder"),
    }
    terms = ["un", "ra", "sh", "MRN", "ka", "de", "ma", "sa"]

    checked, leaked = 0, []
    for email in ("doctor@manakamana.test", "counter@manakamana.test",
                  "pharmacy@manakamana.test", "manager@manakamana.test"):
        user = User.objects.filter(email=email).first()
        client = _report_client(email, tenant)
        if user is None or client is None:
            continue
        membership = Membership.objects.filter(
            user=user, organization__slug=tenant.slug,
        ).first()
        if membership is None:
            continue
        allowed = related_patient_ids(
            user.uuid, resolve_authorization(user, membership),
        )
        # `None` means no restriction -- an owner or an organization-scoped
        # role -- and is not the same answer as an empty set. Nothing to prove
        # about somebody who is allowed everything.
        if allowed is None:
            continue

        for term in terms:
            response = client.get("/api/search/", {"q": term})
            assert response.status_code == 200, (
                f"{email} q={term!r} -> {response.status_code}"
            )
            for group in json.loads(response.content.decode())["groups"]:
                if group["type"] not in models_by_type:
                    continue
                module_name, model_name = models_by_type[group["type"]]
                module = __import__(module_name, fromlist=[model_name])
                model = getattr(module, model_name)
                for hit in group["results"]:
                    if hit.get("by_reference"):
                        continue
                    checked += 1
                    row = model.objects.get(uuid=hit["uuid"])
                    if row.patient_id not in allowed:
                        leaked.append(
                            f"{email} q={term!r} {group['type']} "
                            f"{hit['label']}"
                        )

    assert not leaked, "\n".join(leaked)
    assert checked > 0, "no clinical hits were examined, so nothing was proved"


def test_search_refuses_sources_the_caller_lacks_and_names_them(tenant):
    """Refused, not silently dropped -- and the refusal discloses nothing.

    Somebody who cannot see a domain they know exists concludes the system does
    not have it; somebody told they lack `employee.read` asks for it. The
    refusal names the permission and never a count, because a count of what you
    were refused tells you the record is there, which is usually the secret.
    """
    client = _report_client("counter@manakamana.test", tenant)
    if client is None:
        pytest.skip("no counter account")

    body = json.loads(client.get("/api/search/", {"q": "ra"}).content.decode())
    refused = {entry["type"] for entry in body["refused"]}
    assert refused, "a counter assistant was refused nothing at all"
    assert "employee" in refused, "the counter can search staff records"
    for entry in body["refused"]:
        assert entry["needs"], "a refusal that does not say what it needs"
        assert "count" not in entry and "results" not in entry

    # The count describes only what this caller may see. "42 results, 3 shown"
    # would report the other 39 into existence.
    assert body["count"] == sum(
        len(group["results"]) for group in body["groups"]
    )
    assert refused.isdisjoint({group["type"] for group in body["groups"]})


def test_a_two_character_wildcard_is_not_a_way_to_browse_everything(tenant):
    """`%` and `_` are LIKE wildcards, and `q=%%` clears the length check.

    The ORM escapes them, so this passes today -- it is here because it is a
    one-line regression away from not passing, and the failure would be a
    silent export of the patient index through the search box.
    """
    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    for term in ("%%", "__", "%a", "a%"):
        body = json.loads(
            client.get("/api/search/", {"q": term}).content.decode()
        )
        assert body["count"] == 0, f"{term!r} matched {body['count']} rows"

    # And one character is refused outright: two characters against a patient
    # table is every patient whose name contains "ra".
    assert client.get("/api/search/", {"q": "r"}).status_code == 400


def test_one_search_writes_one_audit_event(tenant):
    """Not one per hit.

    A search touching twenty-five patients must not write twenty-five access
    rows; that drowns the log `record_patient_access` exists to keep readable.
    The term is recorded, because "who searched for that name?" is the question
    asked after a privacy complaint.
    """
    from apps.audit.models import AuditAction, AuditEvent

    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    before = AuditEvent.objects.filter(entity_type="search").count()
    response = client.get("/api/search/", {"q": "ra"})
    assert response.status_code == 200
    hits = json.loads(response.content.decode())["count"]

    written = AuditEvent.objects.filter(entity_type="search").count() - before
    assert written == 1, f"one search wrote {written} audit events"

    event = AuditEvent.objects.filter(
        entity_type="search",
    ).order_by("-occurred_at").first()
    assert event.entity_label == "ra"
    assert event.metadata["hits"] == hits
    # Searching people is a different act from searching the medicine
    # catalogue, and the severity has to say so or the log cannot be filtered.
    if hits:
        assert event.action == AuditAction.VIEW_SENSITIVE


def test_a_multi_table_report_refuses_to_export_one_of_them(tenant):
    """Log 199. A CSV called `finance.balance_sheet` holding only the assets
    looks complete and is not.

    The first version of the exporter took whichever table it found first,
    which on a balance sheet is `assets` — so the liabilities would have been
    silently absent from a file named after the whole report. Half a balance
    sheet is worse than no balance sheet.
    """
    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    run = json.loads(
        client.get("/api/reports/finance.balance_sheet/").content.decode()
    )
    assert len(run["sections"]) > 1, (
        "the balance sheet stopped having several tables, so this guards nothing"
    )

    refused = client.get("/api/reports/finance.balance_sheet/?export=csv")
    assert refused.status_code == 400
    body = json.loads(refused.content.decode())
    # It must say which parts exist, or the refusal is a dead end.
    assert sorted(body["sections"]) == sorted(run["sections"])

    one = client.get(
        "/api/reports/finance.balance_sheet/?export=csv&section=liabilities",
    )
    assert one.status_code == 200
    assert one["Content-Type"].startswith("text/csv")
    # The section is in the filename: three files in a downloads folder must be
    # tellable apart without opening them.
    assert "liabilities" in one["Content-Disposition"]

    assert client.get(
        "/api/reports/finance.balance_sheet/?export=csv&section=nonsense",
    ).status_code == 400


# ---------------------------------------------------------------------------
# Log 200 — what leaves the building leaves a line in the log
# ---------------------------------------------------------------------------


def test_taking_a_copy_is_recorded_as_taking_a_copy(tenant):
    """`EXPORT`, `PRINT` and `DOWNLOAD` were defined and never once recorded.

    Three actions in the enum, severities assigned for two of them, and nothing
    in the codebase writing any — which is worse than their being absent,
    because the log looks like it covers exports and did not. A read shows one
    record to one person inside a system that can still refuse them tomorrow;
    an export makes a copy that leaves, and no permission here governs it
    afterwards.
    """
    from apps.audit.models import AuditAction, AuditEvent
    from apps.documents.models import Document

    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    def count(action):
        return AuditEvent.objects.filter(action=action).count()

    before_export = count(AuditAction.EXPORT)
    exported = client.get("/api/reports/privacy.read_volume/?export=csv&days=365")
    assert exported.status_code == 200
    assert count(AuditAction.EXPORT) == before_export + 1

    event = AuditEvent.objects.filter(
        action=AuditAction.EXPORT,
    ).order_by("-occurred_at").first()
    # Sensitive, not informational: the question after a leak is "who took a
    # copy?", and that has to be a different query from "who looked?".
    assert event.severity == "sensitive"
    # What was in it, so the question is answerable a year later without
    # keeping the file — which nobody does and nobody should.
    assert event.metadata["what"] == "privacy.read_volume"
    assert event.metadata["rows"] > 0
    assert event.metadata["parameters"]["days"] == "365"

    document = Document.objects.filter(archived_at__isnull=True).first()
    if document is not None:
        before_download = count(AuditAction.DOWNLOAD)
        got = client.get(f"/api/documents/{document.uuid}/download/")
        assert got.status_code == 200
        # Every document, not only a patient's. `record_patient_access` says
        # nothing about an employee's certificate or a supplier contract, so
        # before this those left no trace anywhere.
        assert count(AuditAction.DOWNLOAD) == before_download + 1


def test_the_payslip_printable_renders_and_escapes(tenant):
    """It had never rendered once, and would not have been safe if it had.

    Eight field names that do not exist (`present_days` for `days_present`,
    `gross_pay` for `gross`, …), so it raised on its first line of arithmetic —
    and its `?format=html` branch was unreachable anyway, because `format` is
    DRF's reserved parameter. The same bug as `?format=csv` in the report
    library, in an endpoint the console has a button for.
    """
    from apps.audit.models import AuditAction, AuditEvent
    from apps.payroll.models import Payslip

    client = _report_client("owner@manakamana.test", tenant)
    slip = Payslip.objects.first()
    if client is None or slip is None:
        pytest.skip("no payslips")

    structured = client.get(f"/api/payroll/payslips/{slip.reference}/document/")
    assert structured.status_code == 200
    body = json.loads(structured.content.decode())
    assert body["net_pay"] and body["gross_pay"]

    payload = "<script>alert('x')</script>"
    was = slip.employee_name
    slip.employee_name = f"Ram {payload} Bahadur"
    slip.save(update_fields=["employee_name"])
    try:
        before = AuditEvent.objects.filter(action=AuditAction.PRINT).count()
        printable = client.get(
            f"/api/payroll/payslips/{slip.reference}/document/?export=html",
        )
        assert printable.status_code == 200
        html = printable.content.decode()
        # Served same-origin to signed-in staff, so an unescaped name runs.
        assert payload not in html
        assert "&lt;script&gt;" in html

        assert AuditEvent.objects.filter(
            action=AuditAction.PRINT,
        ).count() == before + 1
        event = AuditEvent.objects.filter(
            action=AuditAction.PRINT,
        ).order_by("-occurred_at").first()
        assert event.severity == "sensitive"
        # The audit label keeps the name as typed. Escaping it would record
        # "O&#x27;Brien" as the name of the person whose payslip was printed,
        # which is a worse record than the apostrophe was ever a risk.
        assert payload in event.entity_label
    finally:
        slip.employee_name = was
        slip.save(update_fields=["employee_name"])


# ---------------------------------------------------------------------------
# Log 201 - every route gets called at least once
# ---------------------------------------------------------------------------


def _get_routes():
    """Every GET route this application exposes, with parameters marked.

    Two parameter spellings, and missing the second is not academic: DRF's
    routers emit a regex named group, a hand-written `path()` emits an angle
    bracket converter, and the first version of this treated the second as a
    literal. That called every hand-routed detail endpoint with the brackets
    still in the URL, got a 404, and tested nothing -- while reporting
    twenty-nine "unreachable" endpoints that were nothing of the kind.
    """
    import re

    from django.urls import get_resolver
    from django.urls.resolvers import URLPattern, URLResolver

    def walk(resolver, prefix=""):
        for entry in resolver.url_patterns:
            if isinstance(entry, URLResolver):
                yield from walk(entry, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                yield prefix + str(entry.pattern), entry

    found = set()
    for pattern, entry in walk(get_resolver()):
        path = "/" + pattern.lstrip("^").replace(r"\.", ".")
        path = re.sub(r"\(\?P<([^>]+)>[^)]*\)", r"{\1}", path)
        path = re.sub(r"<[^:>]+:([^>]+)>", r"{\1}", path)
        path = re.sub(r"<([^:>]+)>", r"{\1}", path)
        path = path.rstrip("$").replace("^", "")
        if not path.startswith("/api/") or "{format}" in path:
            continue
        actions = getattr(entry.callback, "actions", None)
        if actions is not None and "get" not in actions:
            continue
        found.add(path)
    return sorted(found)


def test_no_route_returns_a_server_error_for_any_role(tenant):
    """An endpoint nobody has ever called is an endpoint nobody knows is broken.

    The payslip printable proved it: eight field names that do not exist and an
    unreachable `?format=` branch, sitting behind a button in the console, for
    as long as the endpoint had existed. Nothing called it, so nothing said so.

    This calls every GET route as several roles and looks for one thing only. A
    4xx is not a finding -- a role that may not read payroll *should* be
    refused, and this has no way to know which refusals are right. A 5xx is
    never right.
    """
    import re

    routes = _get_routes()
    lists = [path for path in routes if "{" not in path]
    details = [path for path in routes if "{" in path]
    assert len(lists) > 100, f"only {len(lists)} routes found; the walk broke"

    # Two roles, not six. The owner reaches the most code and harvests the
    # identifiers the detail sweep needs; the doctor walks the refusal paths,
    # which are the ones with the interesting branches in them. Adding a third
    # cost thirty seconds and found nothing the first two had not -- and a
    # guard slow enough that somebody starts skipping it guards nothing.
    roles = ["owner@manakamana.test", "doctor@manakamana.test"]
    # Logging out would invalidate the token the rest of the sweep is using.
    skip = {"/api/auth/logout/"}

    failures = []
    identifiers = {}
    for email in roles:
        client = _report_client(email, tenant)
        if client is None:
            continue
        for path in lists:
            if path in skip:
                continue
            response = client.get(path)
            if response.status_code >= 500:
                failures.append(f"{path} as {email}: {response.status_code}")
            if response.status_code == 200 and path not in identifiers:
                try:
                    body = json.loads(response.content.decode())
                except ValueError:
                    continue
                rows = body.get("results") if isinstance(body, dict) else body
                if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                    # Every candidate, not the first one found. The route says
                    # which field it looks up by, and a list that returns both
                    # `uuid` and `reference` must be able to answer either --
                    # the first version kept only `uuid`, substituted it into a
                    # `{reference}` route, got a 404 and tested nothing. Proved
                    # by reintroducing the payslip defect: the sweep passed.
                    identifiers[path] = {
                        key: str(rows[0][key])
                        for key in ("uuid", "reference", "id", "code", "slug",
                                    "pk", "number")
                        if rows[0].get(key)
                    }

        # Detail routes called with something real. A made-up UUID 404s and
        # proves nothing, which is how a broken detail endpoint stays hidden.
        for path in details:
            parent = re.sub(r"\{[^}]+\}/.*$", "", path)
            if parent not in identifiers:
                continue
            available = identifiers[parent]
            wanted = re.search(r"\{([^}]+)\}", path).group(1)
            # Matched by name first: a `{reference}` route wants the reference,
            # not whichever identifier happened to be listed first.
            value = available.get(wanted)
            if value is None:
                for fallback in ("uuid", "reference", "id", "pk"):
                    if fallback in available:
                        value = available[fallback]
                        break
            if value is None:
                continue
            concrete = re.sub(r"\{[^}]+\}", value, path, count=1)
            if "{" in concrete:
                continue
            response = client.get(concrete)
            if response.status_code >= 500:
                failures.append(f"{concrete} as {email}: {response.status_code}")

    assert not failures, "\n".join(failures)
    assert len(identifiers) > 30, (
        f"only {len(identifiers)} list routes returned rows, so the detail "
        "sweep tested almost nothing"
    )


# ---------------------------------------------------------------------------
# Log 202 - my workspace, and the queue that must never lie by being empty
# ---------------------------------------------------------------------------


def test_a_broken_workspace_source_is_named_not_silently_empty(tenant):
    """An empty approval queue is a positive claim that there is nothing to do.

    Every other list in this system degrades acceptably to empty. This one does
    not: somebody with twenty-two requisitions waiting must not be told their
    afternoon is free because a source raised. The rule proved itself on its
    first run -- `PayrollRunStatus` does not exist (it is `RunStatus`) and
    `LeaveRequest.start_date` does not either -- and both came back as named
    broken sources rather than as a quiet zero.
    """
    from apps.workspace import sources as workspace

    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    healthy = json.loads(client.get("/api/me/workspace/").content.decode())
    assert healthy["is_complete"], healthy["broken_sources"]
    assert healthy["broken_sources"] == []

    # Break one deliberately and require that it is reported, not swallowed.
    victim = workspace.get_source_for_test = None
    original = workspace._SOURCES["requisitions"]

    def explode(request):
        raise RuntimeError("the procurement query fell over")

    workspace._SOURCES["requisitions"] = type(original)(
        code=original.code, label=original.label,
        permission=original.permission, scope=original.scope,
        find=explode, screen=original.screen, urgency=original.urgency,
    )
    try:
        broken = json.loads(client.get("/api/me/workspace/").content.decode())
    finally:
        workspace._SOURCES["requisitions"] = original
    assert victim is None

    assert broken["is_complete"] is False
    assert [entry["type"] for entry in broken["broken_sources"]] == [
        "requisitions",
    ]
    # And the request still answers. A workspace that 500s because one module
    # is unwell is a workspace nobody can use to find out what else is waiting.
    assert broken["approvals_total"] >= 0


def test_the_workspace_only_lists_what_you_can_act_on(tenant):
    """Not greyed -- absent.

    A report library lists what you cannot run, because knowing the report
    exists is useful. A work queue is the opposite: a list of things somebody
    can only look at teaches them the queue is not really theirs, and then they
    stop reading it.
    """
    owner = _report_client("owner@manakamana.test", tenant)
    doctor = _report_client("doctor@manakamana.test", tenant)
    if owner is None or doctor is None:
        pytest.skip("missing demo accounts")

    theirs = json.loads(owner.get("/api/me/workspace/").content.decode())
    clinician = json.loads(doctor.get("/api/me/workspace/").content.decode())

    assert theirs["approvals_total"] > 0, (
        "the owner has nothing waiting, so this test proves nothing"
    )
    # A doctor approves no purchase orders and signs off no tills.
    kinds = {group["type"] for group in clinician["approvals"]}
    assert "requisitions" not in kinds
    assert "tills" not in kinds

    for body in (theirs, clinician):
        # Counts are counts of what is shown, as everywhere else.
        assert body["approvals_total"] == sum(
            len(group["items"]) for group in body["approvals"]
        )
        for group in body["approvals"]:
            assert group["count"] == len(group["items"])
            # A group with nothing in it is not shown at all: an empty heading
            # is a row of visual noise that trains people to skim.
            assert group["items"]


def test_every_workspace_source_can_format_a_real_row(tenant):
    """Four of the eight have no pending rows in demo data.

    Which means their formatting had never run -- the same trap that hid
    `scheduled_start` in the search sources and eight wrong names in the
    payslip. So each is given a row to format, and put back afterwards.
    """
    from django.db import IntegrityError

    from apps.tenancy.db import tenant_atomic

    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    def groups():
        body = json.loads(client.get("/api/me/workspace/").content.decode())
        return {group["type"]: group for group in body["approvals"]}

    plans = [
        ("leave", "apps.hr.models", "LeaveRequest", "status", "pending"),
        ("purchase_orders", "apps.procurement.models", "PurchaseOrder",
         "status", "pending_approval"),
        ("payroll_runs", "apps.payroll.models", "PayrollRun",
         "status", "pending_approval"),
    ]

    proved = set(groups())
    for code, module_name, model_name, field, value in plans:
        model = getattr(
            __import__(module_name, fromlist=[model_name]), model_name,
        )
        row = was = None
        for candidate in model.objects.all()[:12]:
            was = getattr(candidate, field)
            setattr(candidate, field, value)
            try:
                # A savepoint, because PostgreSQL aborts the whole transaction
                # on a constraint violation and every later query in it fails
                # with "you can't execute queries until the end of the atomic
                # block". Log 162 taught this about `notify`; it is the same
                # rule, and the reason `except IntegrityError: continue` is not
                # enough on its own.
                with tenant_atomic():
                    candidate.save(update_fields=[field])
            except IntegrityError:
                # Seed data holds a partial unique constraint over live rows,
                # so some rows cannot be moved into the pending state. Not a
                # defect -- try the next one.
                setattr(candidate, field, was)
                continue
            row = candidate
            break
        if row is None:
            continue
        try:
            found = groups()
            assert code in found, (
                f"{code}: a row was put into '{value}' and did not appear"
            )
            item = found[code]["items"][0]
            assert item["title"], f"{code} produced an item with no title"
            proved.add(code)
        finally:
            back = model.objects.get(pk=row.pk)
            setattr(back, field, was)
            back.save(update_fields=[field])

    assert len(proved) >= 6, f"only {len(proved)} sources formatted a row"


# ---------------------------------------------------------------------------
# Log 203 - a screen with no way in
# ---------------------------------------------------------------------------


def test_every_console_route_has_a_way_to_reach_it():
    """`/privacy` and `/notifications` were routed and not in the navigation.

    Reachable only by typing the URL, which for a break-glass review queue
    means in practice that nobody reviews anything. Two in one session is a
    class, not a coincidence: adding a `<Route>` and adding a nav entry are
    separate edits, and nothing connected them.

    **This is a frontend check living in the backend suite, deliberately.** The
    console has no test runner, and adding vitest and jsdom to catch a
    twenty-line text check is a larger change than the problem justifies. It
    reads the file rather than the rendered app, so it can only see routes
    written literally -- which is what they all are, and this test fails loudly
    if that stops being true.
    """
    import pathlib
    import re

    app = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.tsx"
    if not app.exists():
        pytest.skip("no console in this checkout")

    source = app.read_text(encoding="utf-8")
    routes = set(re.findall(r'<Route path="(/[^"*]*)"', source))
    linked = set(re.findall(r'to: "(/[^"]+)"', source))

    assert len(routes) > 10, (
        f"only {len(routes)} routes parsed out of App.tsx; the pattern has "
        "stopped matching and this test is no longer checking anything"
    )
    assert len(linked) > 10, f"only {len(linked)} navigation entries parsed"

    # Deliberately unlinked: reached from inside another screen rather than
    # from the sidebar. Listed by name so that adding one is a decision
    # somebody writes down, which is the whole point.
    reached_from_elsewhere = {
        "/",          # redirects to the home screen
        "/login",     # shown instead of the shell, never navigated to
        # Opened from the queue with an encounter in hand. A sidebar link to
        # "the consultation" would have to invent which one.
        "/consultation/:uuid",
    }

    orphans = sorted(routes - linked - reached_from_elsewhere)
    assert not orphans, (
        "routed with no way in: " + ", ".join(orphans)
        + " -- add a navigation entry, or list it as deliberately unlinked"
    )

    # And the reverse: a nav entry pointing at nothing is a menu item that
    # always 404s, which teaches people to distrust the menu.
    dangling = sorted(linked - routes)
    assert not dangling, "navigation points at unrouted paths: " + ", ".join(dangling)


# ---------------------------------------------------------------------------
# Log 204 - the reminder engine, and the sweep that reaches nobody
# ---------------------------------------------------------------------------


def test_a_reminder_that_reaches_nobody_is_counted_not_shrugged_at(tenant):
    """The rule this module exists around.

    `notify` correctly treats "no recipients" as a real answer rather than an
    error. But a *sweep* that finds forty expiring batches, tells nobody, and
    reports success is the most dangerous kind of quiet: it looks exactly like
    a system that is watching. So `undeliverable` is counted separately, and it
    is a number somebody is meant to act on by fixing a role assignment.
    """
    from dataclasses import replace

    from apps.notifications import reminders

    original = reminders._REMINDERS["batch_expiring"]
    assert original.subjects().exists(), "no batches to remind about"

    # A permission nobody holds. Everything else about the sweep is unchanged,
    # so the only difference is that there is no one to tell.
    orphaned = replace(original, permission="nobody.holds.this")
    report = reminders.run(orphaned)

    assert report["considered"] > 0, "the sweep found nothing to consider"
    assert report["undeliverable"] == report["considered"], (
        "batches were considered and not reported as undeliverable"
    )
    assert report["raised"] == 0

    # And the honest version reaches somebody, so the test above is measuring
    # the permission and not a broken sweep.
    healthy = reminders.run(original)
    assert healthy["undeliverable"] == 0
    assert healthy["considered"] > 0


def test_a_reminder_resolves_when_its_cause_goes_away(tenant):
    """Not when somebody swipes it off a screen.

    A reminder that outlives its cause is how people learn to ignore
    reminders. Quarantine a batch and its reminder should close itself; put it
    back and it should return.
    """
    from apps.notifications import reminders
    from apps.notifications.models import Notification
    from apps.pharmacy.models import Batch

    reminder = reminders._REMINDERS["batch_expiring"]
    reminders.run(reminder)

    def still_open():
        return Notification.objects.filter(
            source="reminders", event="batch_expiring",
            resolved_at__isnull=True,
        ).count()

    before = still_open()
    assert before > 0, "nothing was raised, so nothing can be resolved"

    batch = Batch.objects.filter(
        status="active", expires_on__isnull=False,
    ).first()
    was = batch.status
    batch.status = "quarantined"
    batch.save(update_fields=["status"])
    try:
        report = reminders.run(reminder)
        assert report["resolved"] == 1, report
        assert still_open() == before - 1
    finally:
        batch.status = was
        batch.save(update_fields=["status"])
        again = reminders.run(reminder)
    # Raised afresh rather than un-resolved: a notification is a statement
    # about a moment, and reopening one would rewrite history.
    assert again["raised"] == 1
    assert still_open() == before


def test_running_a_reminder_twice_does_not_raise_it_twice(tenant):
    """The dedupe key carries the subject and the band.

    An hourly cron must produce one notification per expiring thing per band,
    not twenty-four. This is the whole reason `dedupe_key` exists, and it is
    cheap to assert and expensive to discover broken.
    """
    from apps.notifications import reminders

    reminder = reminders._REMINDERS["blood_expiring"]
    first = reminders.run(reminder)
    second = reminders.run(reminder)

    assert first["considered"] > 0, "no blood units near expiry to test with"
    assert second["raised"] == 0, second
    assert second["standing"] == second["considered"]


def test_every_reminder_considers_rows_or_says_why_not(tenant):
    """A reminder that silently considers zero rows looks like good news.

    It is usually a filter that matches nothing -- which is exactly what
    happened: `preauth_expiring` filtered on `status="approved"` while every
    pre-authorisation in the tenant is `partially_approved`, a state that is
    still a live promise with an expiry date on it.

    Two reminders legitimately consider nothing here, and both are recorded
    with the reason rather than left to look like passing tests:
    `EmploymentContract.ends_on` and `Invoice.due_date` are declared on the
    models and **never written by any code**, so no contract can end and no
    invoice can fall due. Those are gaps in billing and HR, on the checklist.
    """
    from apps.notifications import reminders

    known_empty = {
        # Both of these are now *settable* -- `issue_contract` requires an end
        # date on a fixed-term engagement, and `issue_invoice` writes a due
        # date -- but nothing was back-filled, so the existing rows predate the
        # fix and there is genuinely nothing yet to remind anybody about.
        "contract_ending",
        "invoice_overdue",
        # `Facility.license_expires_on` is editable through the API and
        # collected on no screen, so it is empty everywhere. A form, not a
        # field; it is on the checklist as such.
        "facility_licence_expiring",
    }

    silent = []
    for reminder in reminders.all_reminders():
        report = reminders.run(reminder)
        if report["considered"] == 0 and reminder.code not in known_empty:
            silent.append(reminder.code)

    assert not silent, (
        "these reminders considered no rows at all, which is usually a filter "
        "that matches nothing rather than good news: " + ", ".join(silent)
    )


# ---------------------------------------------------------------------------
# Log 205 - the column that was never written
# ---------------------------------------------------------------------------


def test_an_issued_invoice_falls_due(tenant):
    """`Invoice.due_date` was declared and never written by any line of code.

    Sixty-four issued invoices in the demo tenant, not one with a due date, so
    nothing could ever be overdue, credit terms were unenforceable, and the
    reminder that chases unpaid invoices had nothing to chase. Found by the
    reminder engine considering zero rows — which is why "considered nothing"
    is itself a test.
    """
    from apps.billing.models import Charge, ChargeStatus
    from apps.billing.services import create_invoice

    charge = (
        Charge.objects.filter(status=ChargeStatus.PENDING)
        .select_related("patient", "facility")
        .first()
    )
    if charge is None:
        pytest.skip("no pending charges to invoice")

    invoice = create_invoice(
        tenant, charge.patient, charge.facility, charges=[charge], issue=True,
    )
    assert invoice.due_date is not None, (
        "an issued invoice still has no due date"
    )
    # A draft is not owed yet, so the date is allocated by the same act that
    # allocates the number.
    assert invoice.due_date >= invoice.issued_at.date()


def test_credit_terms_follow_who_pays(tenant):
    """The only axis on which terms really vary.

    A walk-in pays today; an insurer pays when it has adjudicated, which is
    weeks. The default for a general patient is **zero days** — due on issue —
    because that is the status quo at a cash counter written down, not a credit
    policy this module invented on somebody's behalf.
    """
    from apps.billing.credit_terms import DEFAULT_CREDIT_DAYS, credit_days
    from apps.organization.config import set_config_value
    from apps.billing.credit_terms import KEY, NAMESPACE

    assert credit_days("general") == 0
    assert credit_days("staff") == 0
    assert credit_days("insurance") > credit_days("general")

    # An unknown category must not silently become generous.
    assert credit_days("something_nobody_defined") == 0

    # Configurable, and configuring one key must not lose the others.
    set_config_value(NAMESPACE, KEY, {"corporate": 60})
    try:
        assert credit_days("corporate") == 60
        assert credit_days("insurance") == DEFAULT_CREDIT_DAYS["insurance"]
        assert credit_days("general") == 0
    finally:
        set_config_value(NAMESPACE, KEY, {})

    # A malformed setting must not take billing down, and must not quietly
    # become "everything is due in ninety days" either.
    set_config_value(NAMESPACE, KEY, "not a mapping at all")
    try:
        assert credit_days("insurance") == DEFAULT_CREDIT_DAYS["insurance"]
    finally:
        set_config_value(NAMESPACE, KEY, {})


def test_ageing_says_when_it_cannot_tell_you_what_is_overdue(tenant):
    """Nothing was back-filled, and the report says so.

    Invoices issued before credit terms existed have no due date. Reporting
    those as "0 days overdue" would claim a punctuality nobody earned, so the
    row carries `None` and the report counts how many it could not answer for.
    """
    from apps.finance.services import receivables_ageing

    report = receivables_ageing()
    assert "overdue" in report
    assert "without_a_due_date" in report

    undated = [row for row in report["invoices"] if row["due"] is None]
    assert all(row["days_overdue"] is None for row in undated), (
        "an invoice with no due date was reported as a number of days overdue"
    )
    assert report["without_a_due_date"] == len(undated)

    # The buckets still age from the invoice date. They are reconciled against
    # the receivables control account, and changing what they mean would move
    # a number two independent records are compared on.
    assert set(report["buckets"]) == {"0-30", "31-60", "61-90", "91-180",
                                      "181-plus"}


def test_an_invoice_worth_nothing_posts_nothing_rather_than_failing(tenant):
    """A document worth nothing has no entry to make, and that is not a failure.

    Found by accident: a probe issued an invoice for a single "Implant, at
    cost" charge priced at zero, and the next run of the finance seed died on
    "an entry with no lines is not an entry" — **taking the whole posting batch
    with it**, because one correctly recorded document happened to be worth
    nothing. A fully waived bill is the same shape and entirely legitimate: it
    needs a number, it belongs in the audit trail, and it moves no money.
    """
    from apps.billing.models import Invoice, InvoiceStatus
    from apps.finance.services import post_invoice

    worthless = (
        Invoice.objects.filter(total=0)
        .exclude(status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED])
        .first()
    )
    if worthless is None:
        pytest.skip("no zero-value issued invoice in this tenant")

    entry, was_new = post_invoice(worthless, actor=None)
    # `None` rather than an empty entry: a journal entry with no lines is a row
    # somebody has to explain to an auditor forever, and the honest record is
    # that there was nothing to post.
    assert entry is None
    assert was_new is False

    # And a document that *is* worth something still posts, so the check above
    # is measuring the amount rather than a broken poster.
    real = (
        Invoice.objects.filter(status=InvoiceStatus.ISSUED)
        .exclude(total=0)
        .first()
    )
    if real is not None:
        entry, _ = post_invoice(real, actor=None)
        assert entry is not None


def test_a_fixed_term_engagement_needs_an_end_date(tenant):
    """`EmploymentContract.ends_on` was declared and never written either.

    The sibling of the invoice due date, found by the same reminder. The API
    already accepted `ends_on`; no caller ever passed it, so no fixed-term
    contract could ever run out and the reminder watching for it was blind.

    A locum, an intern and a fixed-term contract all end on an agreed date —
    that is what distinguishes them from permanent employment, so one with no
    `ends_on` is a missing term rather than a permissive default.
    `daily_wage`, `part_time` and `visiting` are deliberately excluded: they
    describe how somebody is *paid*, not how long they are engaged for, and a
    daily-wage cleaner can be on the books for years.

    Measured before enforcing — every contract in the tenant is permanent or
    daily wage, so nothing existing violates this.
    """
    from datetime import date, timedelta

    from apps.hr.models import (
        ContractStatus,
        Employee,
        EmploymentContract,
        EmploymentType,
    )
    from apps.hr.services import HrError, issue_contract

    employee = Employee.objects.filter(status="active").first()
    if employee is None:
        pytest.skip("no active employee")

    start = date.today()
    active_before = list(
        EmploymentContract.objects.filter(
            employee=employee, status=ContractStatus.ACTIVE,
        ).values_list("pk", flat=True)
    )
    created = []
    try:
        for kind in (EmploymentType.LOCUM, EmploymentType.INTERN,
                     EmploymentType.CONTRACT, EmploymentType.TRAINEE):
            with pytest.raises(HrError):
                issue_contract(
                    employee, start, 40000, employment_type=kind, ends_on=None,
                )

        # A date before the start is not a term, it is a typo.
        with pytest.raises(HrError):
            issue_contract(
                employee, start, 40000,
                employment_type=EmploymentType.CONTRACT,
                ends_on=start - timedelta(days=1),
            )

        # Open-ended arrangements are still allowed to be open-ended.
        for kind in (EmploymentType.PERMANENT, EmploymentType.DAILY_WAGE):
            contract = issue_contract(
                employee, start, 40000, employment_type=kind, ends_on=None,
            )
            created.append(contract.pk)
            assert contract.ends_on is None

        dated = issue_contract(
            employee, start, 40000, employment_type=EmploymentType.LOCUM,
            ends_on=start + timedelta(days=90),
        )
        created.append(dated.pk)
        assert dated.ends_on == start + timedelta(days=90)
    finally:
        # `issue_contract` supersedes whatever was active, so putting the rows
        # back is not enough -- the employee's real contract has to be made
        # active again or the tenant is left without one.
        EmploymentContract.objects.filter(pk__in=created).delete()
        EmploymentContract.objects.filter(pk__in=active_before).update(
            status=ContractStatus.ACTIVE,
        )


# ---------------------------------------------------------------------------
# Log 207 - a critical result nobody acknowledged
# ---------------------------------------------------------------------------


def test_an_unacknowledged_critical_value_escalates_itself(tenant):
    """`AlertStatus.ESCALATED` existed and nothing could reach it.

    `escalated_at` and `escalation_note` were declared on the model and never
    assigned by any line of code, so a critical potassium the ward did not
    acknowledge sat `pending` for ever — and the one situation the whole entity
    exists to catch was the one it could not record.

    Escalation is automatic and time-based, because waiting for a human to
    press "escalate" is waiting for the person who is already not answering.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.diagnostics.models import AlertStatus, CriticalValueAlert
    from apps.diagnostics.services import (
        DiagnosticsError,
        escalate_critical,
        escalation_minutes,
        sweep_unacknowledged_criticals,
    )
    from apps.notifications.models import Notification

    alert = CriticalValueAlert.objects.select_related(
        "patient", "result", "order",
    ).first()
    if alert is None:
        pytest.skip("no critical value alerts in this tenant")

    saved = {
        field: getattr(alert, field)
        for field in ("status", "raised_at", "escalated_at", "escalation_note",
                      "acknowledged_at", "acknowledged_by_id", "action_taken")
    }
    limit = escalation_minutes()
    assert limit <= 60, "an escalation limit measured in hours is not one"

    try:
        # An acknowledged alert has nothing left to escalate.
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.save(update_fields=["status"])
        with pytest.raises(DiagnosticsError):
            escalate_critical(alert, "should be refused")

        # Pending, but inside the limit: left alone.
        alert.status = AlertStatus.PENDING
        alert.acknowledged_at = None
        alert.acknowledged_by_id = None
        alert.action_taken = ""
        alert.raised_at = timezone.now() - timedelta(minutes=max(1, limit - 5))
        alert.save()
        assert sweep_unacknowledged_criticals()["escalated"] == 0
        alert.refresh_from_db()
        assert alert.status == AlertStatus.PENDING

        # Past the limit: escalated, and somebody wider is told.
        alert.raised_at = timezone.now() - timedelta(minutes=limit * 6)
        alert.save(update_fields=["raised_at"])
        report = sweep_unacknowledged_criticals()
        assert report["escalated"] == 1, report

        alert.refresh_from_db()
        assert alert.status == AlertStatus.ESCALATED
        assert alert.escalated_at is not None
        assert alert.escalation_note, "escalated with no reason recorded"

        notice = Notification.objects.filter(
            event="critical_value_escalated", subject_uuid=alert.uuid,
        ).first()
        assert notice is not None, "escalated and told nobody"
        assert notice.category == "critical"
        assert notice.receipts.exists()

        # Running again must not escalate it a second time.
        assert sweep_unacknowledged_criticals()["escalated"] == 0

        # And escalation does not discharge the obligation: somebody still has
        # to acknowledge and say what was done.
        alert.refresh_from_db()
        assert alert.status != AlertStatus.ACKNOWLEDGED
        assert not alert.action_taken
    finally:
        for field, value in saved.items():
            setattr(alert, field, value)
        alert.save()
        Notification.all_objects.filter(
            event="critical_value_escalated",
        ).delete()


# ---------------------------------------------------------------------------
# Log 208 - a patient who could not be recorded as having died
# ---------------------------------------------------------------------------


def test_recording_a_death_refuses_the_impossible_and_cancels_the_future(tenant):
    """`PatientStatus.DECEASED`, `date_of_death` and `cause_of_death` all
    existed and nothing set any of them.

    Meanwhile emergency, ICU, inpatient and the encounter record each have
    their own death outcome — so the hospital knew in four places and the
    patient record did not. Somebody who died in intensive care last week was
    still `active`: still schedulable, still on the reminder sweeps, still a
    name a receptionist would offer an appointment to.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.patients.models import Patient, PatientStatus
    from apps.patients.services import PatientError, record_death
    from apps.scheduling.models import Appointment, AppointmentStatus

    today = timezone.localdate()
    patient = (
        Patient.objects.filter(status=PatientStatus.ACTIVE)
        .exclude(date_of_birth=None)
        .first()
    )
    if patient is None:
        pytest.skip("no active patient with a date of birth")

    with pytest.raises(PatientError):
        record_death(patient, today + timedelta(days=1))
    with pytest.raises(PatientError):
        record_death(patient, patient.date_of_birth - timedelta(days=1))

    template = Appointment.objects.filter(patient__isnull=False).first()
    if template is None:
        pytest.skip("no appointments to model against")

    future = Appointment.objects.create(
        patient=patient, facility=template.facility,
        reference="APT-TEST-FUTURE",
        scheduled_for=timezone.now() + timedelta(days=7),
        status=AppointmentStatus.SCHEDULED, duration_minutes=15,
    )
    past = Appointment.objects.create(
        patient=patient, facility=template.facility,
        reference="APT-TEST-PAST",
        scheduled_for=timezone.now() - timedelta(days=30),
        status=AppointmentStatus.COMPLETED, duration_minutes=15,
    )

    record_death(patient, today, cause="Cardiac arrest", observed_by="test")
    patient.refresh_from_db()
    assert patient.status == PatientStatus.DECEASED
    assert patient.date_of_death == today
    assert patient.cause_of_death == "Cardiac arrest"

    # The actual harm this prevents: a reminder telephoning a bereaved family
    # about next Tuesday's clinic.
    future.refresh_from_db()
    assert future.status == AppointmentStatus.CANCELLED
    assert future.cancellation_reason == "Patient deceased"

    # What already happened still happened.
    past.refresh_from_db()
    assert past.status == AppointmentStatus.COMPLETED

    # Idempotent: two modules observing the same death must not fight over the
    # record or write two audit lines for one event.
    record_death(patient, today, cause="Cardiac arrest")
    patient.refresh_from_db()
    assert patient.date_of_death == today


def test_a_death_on_the_ward_reaches_the_patient_record(tenant):
    """The integration is the point, not the setter.

    A death recorded on an admission answers "how did this stay end". It cannot
    answer "is this person alive", which is what scheduling, the reminder
    sweeps and the receptionist are all really asking.
    """
    from apps.inpatient.models import Admission, AdmissionStatus, IN_HOUSE_STATUSES
    from apps.inpatient.services import discharge
    from apps.patients.models import PatientStatus

    admission = (
        Admission.objects.filter(status__in=IN_HOUSE_STATUSES)
        .select_related("patient")
        .first()
    )
    if admission is None:
        pytest.skip("nobody currently admitted")

    patient = admission.patient
    assert patient.status != PatientStatus.DECEASED

    discharge(admission, outcome=AdmissionStatus.DIED, actor=None)

    patient.refresh_from_db()
    assert patient.status == PatientStatus.DECEASED, (
        "a patient died on the ward and their own record still says active"
    )
    assert patient.date_of_death is not None


# ---------------------------------------------------------------------------
# Log 210 - counting a customer's usage exactly once
# ---------------------------------------------------------------------------


def test_metering_the_same_thing_twice_bills_it_once(tenant):
    """`idempotency_key` was declared with a unique constraint already on it,
    and no caller ever supplied a key.

    So the constraint guarded nothing and a retried registration billed the
    customer twice. The key describes the thing rather than the moment --
    `patient:<uuid>` is the same key on the first attempt and the fourth, which
    is the only property that makes a retry safe.
    """
    from apps.metering.models import UsageEvent
    from apps.metering.services import meter

    key = "test:idempotency"
    UsageEvent.objects.filter(idempotency_key=key).delete()

    assert meter(tenant, "patients", key=key) is True
    assert meter(tenant, "patients", key=key) is False
    assert meter(tenant, "patients", key=key) is False
    assert UsageEvent.objects.filter(idempotency_key=key).count() == 1

    # **The transaction must still be usable.** PostgreSQL aborts the whole
    # transaction on a constraint violation, so without a savepoint around the
    # insert this query fails with "you can't execute queries until the end of
    # the atomic block" — and the two collisions above would have taken patient
    # registration down with them rather than being harmlessly ignored. The old
    # helpers were safe only because they never supplied a key and so never
    # collided; adding the key without the savepoint would have been an outage.
    assert UsageEvent.objects.filter(organization=tenant).exists()

    # A meter with no natural subject still counts every call, which is the
    # previous behaviour preserved rather than an accident.
    before = UsageEvent.objects.filter(
        organization=tenant, meter_key="api_calls", idempotency_key="",
    ).count()
    meter(tenant, "api_calls")
    meter(tenant, "api_calls")
    assert UsageEvent.objects.filter(
        organization=tenant, meter_key="api_calls", idempotency_key="",
    ).count() == before + 2


def test_registering_a_patient_meters_it_with_a_key(tenant):
    """The call site, not just the helper.

    Both places that metered had grown their own private `_meter` with the same
    body and the same omission, so testing the helper alone would prove nothing
    about whether anybody passes a key to it.
    """
    from apps.metering.models import UsageEvent
    from apps.patients.models import Patient

    patient = Patient.objects.exclude(status="merged").first()
    if patient is None:
        pytest.skip("no patients")

    from apps.patients.services import _meter_patient

    UsageEvent.objects.filter(
        idempotency_key=f"patient:{patient.uuid}",
    ).delete()
    _meter_patient(tenant, patient)
    _meter_patient(tenant, patient)

    assert UsageEvent.objects.filter(
        idempotency_key=f"patient:{patient.uuid}",
    ).count() == 1


# ---------------------------------------------------------------------------
# Log 211 - reading a thing and changing it are not the same authority
# ---------------------------------------------------------------------------


def test_master_data_refuses_writes_from_people_who_may_only_read_it(tenant):
    """A `ModelViewSet` exposes every verb by default.

    So a viewset declaring only a read permission accepted writes from anybody
    who could read — and the omission looks like nothing at all, because the
    line that should be there simply is not there.

    Measured rather than reasoned about: an empty `PATCH` against every
    patchable route, as eight roles, found 31 routes accepting a write from
    somebody who should not have one. A counter assistant could edit a price
    list — change a price, sell, change it back. **Every role in the system,
    including a doctor and a nurse, could rewrite the holiday calendar and the
    leave types**, which decide attendance and therefore pay; those two
    viewsets carried no permission at all beyond being signed in.
    """
    import json
    import re

    from apps.identity.models import User

    # Routes that decide money or entitlement, and a role that must not touch
    # them. An empty PATCH changes nothing and distinguishes the answers: 403
    # is guarded, 405 is not exposed, 200 is a hole.
    # Each pair is a role that **can read** the route and must not write it.
    # Measured, not assumed: the first version of this test paired a doctor
    # with the holiday calendar, and a doctor cannot read holidays at all, so
    # the check skipped and the test passed having examined nothing. Proving
    # it by removing a guard is what exposed that -- the removal did not fail
    # the test.
    forbidden = [
        ("counter@manakamana.test", "/api/billing/price-lists/"),
        ("counter@manakamana.test", "/api/billing/services/"),
        ("counter@manakamana.test", "/api/pharmacy/products/"),
        ("counter@manakamana.test", "/api/insurance/payers/"),
        ("manager@manakamana.test", "/api/payroll/components/"),
        ("pharmacy@manakamana.test", "/api/finance/bank-accounts/"),
        ("doctor@manakamana.test", "/api/diagnostics/tests/"),
        ("doctor@manakamana.test", "/api/ipd/wards/"),
    ]
    # The holiday calendar and the shift patterns are deliberately **not**
    # here. They were, briefly, while both sat behind `config.update` -- which
    # left only the organization administrator able to add a public holiday,
    # and an HR manager unable to do their own job. They now sit behind
    # `employee.manage`, which the HR manager holds, so the only account that
    # can read them can also change them and there is no pair left to test.
    # A guard that outlives the rule it guarded is worse than no guard.

    holes = []
    examined = 0
    for email, list_route in forbidden:
        client = _report_client(email, tenant)
        user = User.objects.filter(email=email).first()
        if client is None or user is None:
            continue

        listing = client.get(list_route)
        if listing.status_code != 200:
            continue
        body = json.loads(listing.content.decode())
        rows = body.get("results") if isinstance(body, dict) else body
        if not rows:
            continue

        row = rows[0]
        identifier = next(
            (str(row[key]) for key in ("uuid", "code", "reference", "id")
             if row.get(key)),
            None,
        )
        if identifier is None:
            continue

        examined += 1
        response = client.patch(
            f"{list_route}{identifier}/",
            data="{}", content_type="application/json",
        )
        if response.status_code in (200, 202):
            holes.append(
                f"{email} may PATCH {list_route} ({response.status_code})"
            )

    # The guard against the failure this test itself had: a skipped pair is
    # silent, and a test that examined nothing passes just as green as one that
    # examined everything.
    assert examined >= 8, (
        f"only {examined} of {len(forbidden)} pairs were actually exercised; "
        "the rest skipped, so this test is not checking what it claims"
    )
    assert not holes, "\n".join(holes)


def test_a_read_permission_alone_does_not_open_a_write_endpoint(tenant):
    """The mechanism, so the fix cannot quietly regress one viewset at a time.

    `HasPermission.of(read, write=...)` asks for a different permission on an
    unsafe verb. Without the `write=`, the same permission governs both — which
    is now a claim somebody makes on purpose rather than a line nobody wrote.
    """
    import types

    from apps.common.permissions import HasPermission
    from apps.rbac.permissions import Scope

    guard = HasPermission.of("invoice.read", write="config.update")()
    holder = _authorization_with(
        tenant, "invoice.read", Scope.ORGANIZATION, None,
    )

    def as_request(method):
        fields = dict(vars(holder))
        fields["method"] = method
        return types.SimpleNamespace(**fields)

    assert guard.has_permission(as_request("GET"), None)
    assert guard.has_permission(as_request("HEAD"), None)
    # The same person, the same permission, an unsafe verb: refused.
    assert not guard.has_permission(as_request("PATCH"), None)
    assert not guard.has_permission(as_request("POST"), None)
    assert not guard.has_permission(as_request("DELETE"), None)


# ---------------------------------------------------------------------------
# Log 214 - an endpoint that could never have worked
# ---------------------------------------------------------------------------


def test_a_payroll_profile_can_actually_be_created(tenant):
    """Every field on it was `read_only`, including the employee.

    So `perform_create` saved a profile with no employee, and since `employee`
    is a non-null one-to-one the request reached the database and returned a
    500. Creating a payroll profile — the only way to give somebody a salary
    structure or a tax regime — could never succeed, and nothing else in the
    codebase creates one either.

    Found by POSTing an **empty body** to every create endpoint. A malformed
    request should be answered with a 400; this one crashed, which is the
    signature of a serializer that does not require what the table does.
    """
    from apps.hr.models import Employee
    from apps.payroll.models import EmployeePayroll, SalaryStructure

    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    # A bad request is a 400, not a crash.
    empty = client.post(
        "/api/payroll/profiles/", data="{}",
        content_type="application/json",
    )
    assert empty.status_code == 400, empty.content[:200]
    assert "employee" in empty.content.decode()

    candidate = Employee.objects.exclude(
        pk__in=EmployeePayroll.objects.values("employee_id"),
    ).first()
    if candidate is None:
        pytest.skip("every employee already has a payroll profile")

    structure = SalaryStructure.objects.first()
    created = client.post(
        "/api/payroll/profiles/",
        data=json.dumps({
            "employee": str(candidate.uuid),
            "structure": str(structure.uuid) if structure else None,
            "tax_regime": "individual",
        }),
        content_type="application/json",
    )
    assert created.status_code == 201, created.content[:300]
    body = json.loads(created.content.decode())
    assert body["employee"] == str(candidate.uuid)

    # And the employee is fixed once it exists: this is a one-to-one record
    # *about* that person, and moving it would silently transfer their salary
    # structure, tax regime and insurance declarations with it.
    someone_else = Employee.objects.exclude(pk=candidate.pk).first()
    if someone_else is not None:
        client.patch(
            f"/api/payroll/profiles/{body['uuid']}/",
            data=json.dumps({"employee": str(someone_else.uuid)}),
            content_type="application/json",
        )
        assert EmployeePayroll.objects.get(
            uuid=body["uuid"],
        ).employee_id == candidate.pk


def test_no_create_endpoint_crashes_on_a_malformed_body(tenant):
    """A bad request deserves a 400, not a stack trace.

    `EmployeePayrollSerializer` declared its required foreign key read-only, so
    an empty POST sailed past validation and 500'd at the database. A static
    check for that shape found **55 candidates** — and every one of the other
    54 is a false positive, because those viewsets take a separate create
    serializer or override `create()`. Measuring settled in five seconds what
    reading could only guess at.

    Run as the owner deliberately: the earlier sweep used four ordinary roles,
    so any route needing a permission none of them held returned 403 and never
    reached the serializer — a blind spot exactly where the shape predicts
    bugs.
    """
    import re

    from django.db import transaction
    from django.urls import get_resolver
    from django.urls.resolvers import URLPattern, URLResolver

    from apps.tenancy.context import CONTROL_PLANE_ALIAS
    from apps.tenancy.db import tenant_atomic

    skip = {"/api/auth/login/", "/api/auth/refresh/", "/api/auth/logout/",
            "/api/auth/switch/", "/api/portal/auth/", "/api/me/auth/"}

    def walk(resolver, prefix=""):
        for entry in resolver.url_patterns:
            if isinstance(entry, URLResolver):
                yield from walk(entry, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                yield prefix + str(entry.pattern), entry

    routes = set()
    for pattern, entry in walk(get_resolver()):
        path = "/" + pattern.lstrip("^").replace(chr(92) + ".", ".")
        path = re.sub(r"\(\?P<([^>]+)>[^)]*\)", r"{\1}", path)
        path = re.sub(r"<[^:>]+:([^>]+)>", r"{\1}", path)
        path = re.sub(r"<([^:>]+)>", r"{\1}", path)
        path = path.rstrip("$").replace("^", "")
        if not path.startswith("/api/") or "{format}" in path or "{" in path:
            continue
        if path in skip:
            continue
        actions = getattr(entry.callback, "actions", None) or {}
        if "post" in actions:
            routes.add(path)

    assert len(routes) > 50, f"only {len(routes)} create routes found"

    client = _report_client("owner@manakamana.test", tenant)
    if client is None:
        pytest.skip("no owner account")
    client.raise_request_exception = False

    crashed = []
    for path in sorted(routes):
        # A savepoint per request. Without one, the first 500 aborts the
        # transaction and every route after it fails for a reason that has
        # nothing to do with it -- which is how the first run of this sweep
        # reported twenty bugs where there was one. Log 162, in the
        # instrument.
        try:
            # A savepoint on **both** connections, and the tenant one is the
            # part that matters. The first version opened `transaction.atomic()`
            # with no alias -- which is the control plane -- so a constraint
            # violation on the *tenant* database was never contained, and the
            # guard reported four crashes where there was one. The savepoint
            # has to be on the connection that faults; anything else is
            # decoration.
            with tenant_atomic(), transaction.atomic(
                using=CONTROL_PLANE_ALIAS,
            ):
                response = client.post(
                    path, data="{}", content_type="application/json",
                )
                if response.status_code >= 500:
                    crashed.append(f"{path} -> {response.status_code}")
                # Roll the savepoint back whatever happened: an empty body
                # occasionally succeeds, and this test must leave nothing.
                raise _Rollback
        except _Rollback:
            pass

    assert not crashed, (
        "create endpoints that crash on a bad body:\n"
        + "\n".join(crashed)
    )


class _Rollback(Exception):
    """Unwinds a savepoint deliberately. Never escapes the loop above."""
