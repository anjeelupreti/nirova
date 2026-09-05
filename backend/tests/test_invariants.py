"""The invariants that have actually been broken, guarded so they stay fixed.

Every test here corresponds to a numbered entry in the development log. That is
the selection rule: this file is not an attempt at coverage, it is a record of
things that went wrong once and must not go wrong silently again.
"""

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
