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
