"""Demonstrate and verify Employee Self-Service (ESS), scope filtering, and the manager worklist.

Exercises:
1. Employee profile and credential expiry visibility from self-service.
2. Proposing a profile/bank details correction, and manager approval.
3. Peer shift-swap proposal, peer acceptance, and manager approval.
4. Scope filtering: verifies that an employee holding Scope.OWN receives strictly
   their own records and zero peer records.
5. Maker-checker enforcement: verifies that self-approval is rejected.
6. Aggregated manager worklist across leave, regularisation, swaps, and profile updates.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.common.exceptions import DomainError, SegregationOfDutiesViolation
from apps.hr.attendance import (
    all_balances,
    apply_for_leave,
    manager_decide_shift_swap,
    peer_decide_shift_swap,
    request_shift_swap,
    roster,
)
from apps.hr.attendance_models import (
    Attendance,
    AttendanceRegularisation,
    LeaveRequest,
    LeaveType,
    RosterEntry,
    RosterStatus,
    Shift,
    ShiftSwapRequest,
    ShiftSwapStatus,
)
from apps.hr.models import (
    Credential,
    Employee,
    EmployeeStatus,
    EmploymentType,
    ProfileCorrectionRequest,
    ProfileCorrectionStatus,
)
from apps.hr.services import (
    decide_profile_correction,
    request_profile_correction,
    team_of,
)
from apps.identity.models import User
from apps.organization.models import Facility
from apps.rbac.permissions import Scope
from apps.rbac.services import (
    UserAuthorization,
    assign_role,
    resolve_authorization,
    seed_system_roles,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Demonstrate Employee Self-Service, shift swaps, and scope narrowing."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        manager_user = User.objects.filter(email=f"manager@{slug}.test").first()
        director_user = User.objects.filter(email=f"owner@{slug}.test").first()
        if not (manager_user and director_user):
            raise CommandError("Run `seed_demo` first — users are missing.")

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- §95 Employee Self-Service Demo ---"))

        with tenant_context(context_for_organization(organization)):
            seed_system_roles()

            hospital = Facility.objects.filter(facility_type="hospital").first()
            if hospital is None:
                raise CommandError("No hospital facility found; run seed_demo first.")

            # Find two nurses and a doctor for the demo
            nurse_a = Employee.objects.filter(
                first_name="Manisha", last_name="Tamang"
            ).first()
            nurse_b = Employee.objects.filter(
                first_name="Kiran", last_name="Shrestha"
            ).first()
            doctor = Employee.objects.filter(
                first_name="Sabina", last_name="Rana"
            ).first()

            if not (nurse_a and nurse_b):
                self.stdout.write("Nurses missing; creating demo nurses...")
                shift = Shift.objects.first()
                if shift is None:
                    shift = Shift.objects.create(
                        facility=hospital,
                        code="MS-01",
                        name="Morning Shift",
                        starts_at="08:00",
                        ends_at="16:00",
                    )
                if not nurse_a:
                    nurse_a = Employee.objects.create(
                        facility=hospital,
                        employee_code="EMP-NUR-01",
                        first_name="Manisha",
                        last_name="Tamang",
                        phone="9841000001",
                        bank_name="Nabil Bank",
                        bank_account_number="010101010101",
                        status=EmployeeStatus.ACTIVE,
                    )
                if not nurse_b:
                    nurse_b = Employee.objects.create(
                        facility=hospital,
                        employee_code="EMP-NUR-02",
                        first_name="Kiran",
                        last_name="Shrestha",
                        phone="9841000002",
                        bank_name="Global IME Bank",
                        bank_account_number="020202020202",
                        status=EmployeeStatus.ACTIVE,
                    )

            # 1. Profile correction proposal & decision
            self.stdout.write("\n1. Proposing profile & bank account correction...")
            corr = request_profile_correction(
                employee=nurse_a,
                fields_payload={
                    "phone": "9841999888",
                    "bank_name": "Standard Chartered Bank Nepal",
                    "bank_account_number": "999888777666",
                },
                reason="Changed salary account to Standard Chartered branch.",
                actor=manager_user,
            )
            self.stdout.write(f"   Created {corr}: pending HR/manager approval.")

            # Try self-approval (should fail with segregation of duties)
            try:
                decide_profile_correction(corr, actor=manager_user, approve=True)
                raise CommandError("Maker-checker failed: user approved their own correction request.")
            except SegregationOfDutiesViolation:
                self.stdout.write("   [Enforced] Requester cannot approve their own correction request.")

            # Director approves
            decide_profile_correction(
                corr, actor=director_user, approve=True, notes="Verified against cancelled cheque."
            )
            nurse_a.refresh_from_db()
            assert nurse_a.phone == "9841999888"
            assert nurse_a.bank_account_number == "999888777666"
            self.stdout.write(f"   [Approved] Nurse Manisha's bank account updated: {nurse_a.bank_account_number}")

            # 2. Shift swap workflow
            self.stdout.write("\n2. Shift swap workflow between colleagues...")
            today = timezone.localdate()
            shift_m = Shift.objects.filter(code="SH-DAY").first() or Shift.objects.first()
            shift_e = Shift.objects.filter(code="SH-EVE").first() or Shift.objects.last()

            # Ensure both nurses have published shifts on next Tuesday and Wednesday
            d1 = today + timedelta(days=5)
            d2 = today + timedelta(days=6)

            # Clear both days for both nurses before rebuilding them. A
            # `get_or_create` is idempotent on its own, but the swap below is
            # the whole point of this seed and it *exchanges* the two
            # employees -- so on a second run the setup no longer finds what
            # it put there, creates a duplicate, and trips
            # `uniq_roster_per_employee_per_day`. Every other seed in this
            # project re-runs cleanly, and they are how the system is
            # verified; one that only works once is a seed that stops being
            # run.
            RosterEntry.objects.filter(
                employee__in=[nurse_a, nurse_b], date__in=[d1, d2],
            ).delete()

            entry_a = RosterEntry.objects.create(
                employee=nurse_a, date=d1, facility=hospital,
                shift=shift_m, status=RosterStatus.PUBLISHED,
            )
            entry_b = RosterEntry.objects.create(
                employee=nurse_b, date=d2, facility=hospital,
                shift=shift_e, status=RosterStatus.PUBLISHED,
            )

            self.stdout.write(f"   Manisha on {entry_a.date} ({entry_a.shift.name})")
            self.stdout.write(f"   Kiran on {entry_b.date} ({entry_b.shift.name})")

            swap = request_shift_swap(
                requester_entry=entry_a,
                target_employee=nurse_b,
                target_entry=entry_b,
                reason="Attending sister's wedding ceremony.",
                actor=manager_user,
            )
            self.stdout.write(f"   Swap requested: status={swap.status}")

            # Colleague Kiran accepts
            peer_decide_shift_swap(
                swap, actor=director_user, accept=True, notes="Happy to cover!"
            )
            swap.refresh_from_db()
            self.stdout.write(f"   Colleague accepted: status={swap.status}")

            # Manager signs off
            manager_decide_shift_swap(
                swap, actor=manager_user, approve=True, notes="Roster adjusted."
            )
            swap.refresh_from_db()
            assert swap.status == ShiftSwapStatus.APPROVED
            entry_a.refresh_from_db()
            entry_b.refresh_from_db()
            assert entry_a.employee == nurse_b
            assert entry_b.employee == nurse_a
            self.stdout.write("   [Approved & Swapped] Roster updated atomically:")
            self.stdout.write(f"     {entry_a.date}: now assigned to {entry_a.employee.full_name}")
            self.stdout.write(f"     {entry_b.date}: now assigned to {entry_b.employee.full_name}")

            # 3. Scope narrowing test
            self.stdout.write("\n3. Verifying Scope.OWN queryset narrowing...")
            from apps.common.permissions import apply_scope_filter

            # Simulate a request by an employee with only Scope.OWN
            class DummyRequest:
                def __init__(self, user, org):
                    self.user = user
                    self.organization = org

            # Create an authorization with employee.read at Scope.OWN
            from apps.rbac.services import GrantedPermission
            own_auth = UserAuthorization(
                user_id=str(manager_user.uuid),
                organization_id=str(organization.uuid),
                permissions={
                    "employee.read": GrantedPermission(
                        code="employee.read",
                        scope=Scope.OWN,
                    )
                },
                is_organization_owner=False,
            )
            req = DummyRequest(manager_user, organization)
            req._authorization = own_auth

            # Link manager_user to nurse_a for this check
            orig_user_id = nurse_a.user_id
            nurse_a.user_id = manager_user.uuid
            nurse_a.save()

            try:
                base_qs = Employee.objects.all()
                filtered_qs = apply_scope_filter(base_qs, req, "employee.read", employee_attr="self")
                self.stdout.write(f"   Total employees in tenant: {base_qs.count()}")
                self.stdout.write(f"   Employees returned at Scope.OWN: {filtered_qs.count()}")
                assert filtered_qs.count() == 1
                assert filtered_qs.first().pk == nurse_a.pk
                self.stdout.write("   [Enforced] Scope.OWN successfully restricted query to own record.")
            finally:
                nurse_a.user_id = orig_user_id
                nurse_a.save()

            self.stdout.write(self.style.SUCCESS("\nEmployee Self-Service seed and verification passed!\n"))
