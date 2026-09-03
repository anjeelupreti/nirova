"""Build a workforce, and exercise the rules that govern one.

Through the real service layer:

1. Positions with budgeted headcount, so vacancies are a real number.
2. Hiring, including linking an employee to an existing login.
3. A promotion and a transfer, and the history they leave behind.
4. Credential verification, refused for the credential's own holder.
5. A doctor whose council registration has lapsed, refused practice.
6. A separation, and what survives it.
7. Headcount, vacancies and what is about to expire.

The seed narrates what it expects beside each number, so the output
contradicts itself when the arithmetic is wrong.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.common.exceptions import SegregationOfDutiesViolation
from apps.hr.models import (
    Credential,
    CredentialType,
    Employee,
    EmployeeStatus,
    EmploymentType,
    EventType,
    Position,
    VerificationStatus,
)
from apps.hr.services import (
    NotPractising,
    assert_may_practise,
    confirm,
    expiring_credentials,
    headcount,
    hire,
    issue_contract,
    practice_blockers,
    provision_login,
    separate,
    transfer,
    verify_credential,
)
from apps.identity.models import User
from apps.organization.models import Department, Facility
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

DEMO_PASSWORD = "NirovaDemo!2026"

#: (code, title, grade, budgeted, clinical, provider, needs a licence)
#:
#: The consultant position is budgeted for two and will be filled by one, so
#: the vacancy count has something real to report.
POSITIONS = [
    ("POS-MED-01", "Consultant Physician", "Level 9", 2, True, True, True),
    ("POS-MED-02", "Medical Officer", "Level 7", 2, True, True, True),
    ("POS-NUR-01", "Staff Nurse", "Level 5", 4, True, False, True),
    ("POS-PHA-01", "Pharmacist", "Level 6", 1, True, False, True),
    ("POS-ADM-01", "Front Desk Officer", "Level 4", 2, False, False, False),
    ("POS-SUP-01", "Ward Attendant", "Level 2", 3, False, False, False),
]

#: (first, last, position code, employment type, probation days, licence offset)
#:
#: A licence offset of None means no registration is recorded at all, which is
#: a different failure from one that has expired -- and both must block.
STAFF = [
    ("Sabina", "Rana", "POS-MED-01", EmploymentType.PERMANENT, 0, 500),
    ("Prakash", "Adhikari", "POS-MED-02", EmploymentType.PROBATION, 180, -20),
    ("Manisha", "Tamang", "POS-NUR-01", EmploymentType.PERMANENT, 0, 700),
    ("Kiran", "Shrestha", "POS-NUR-01", EmploymentType.CONTRACT, 0, None),
    ("Deepa", "Karki", "POS-ADM-01", EmploymentType.PERMANENT, 0, None),
    ("Ram", "Bahadur", "POS-SUP-01", EmploymentType.DAILY_WAGE, 0, None),
]


class Command(BaseCommand):
    help = "Build a workforce and exercise the rules that govern one."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        hr_manager = User.objects.filter(email=f"manager@{slug}.test").first()
        director = User.objects.filter(email=f"owner@{slug}.test").first()
        if not (hr_manager and director):
            raise CommandError("Run `seed_demo` first — users are missing.")

        with tenant_context(context_for_organization(organization)):
            facility = (
                Facility.objects.filter(facility_type="clinic").first()
                or Facility.objects.first()
            )
            if facility is None:
                raise CommandError("No facility. Run `seed_demo` first.")

            self._positions(facility)
            people = self._hire(organization, slug, facility, hr_manager)
            self._credentials(people, hr_manager, director)
            self._practice_check(people)
            self._promote(facility, people, hr_manager)
            self._contracts(people, hr_manager)
            self._separate(people, hr_manager)
            self._report(facility)

    # -- setup -------------------------------------------------------------

    def _positions(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Positions"))
        for code, title, grade, budgeted, clinical, provider, licence in POSITIONS:
            Position.objects.update_or_create(
                code=code,
                defaults={
                    "title": title,
                    "grade": grade,
                    "facility": facility,
                    "budgeted_headcount": budgeted,
                    "is_clinical": clinical,
                    "is_provider": provider,
                    "requires_licence": licence,
                },
            )
        total = sum(row[3] for row in POSITIONS)
        self.stdout.write(
            f"   {len(POSITIONS)} positions budgeted for {total} people — "
            "headcount is planned against the job, not the person, which is "
            "why a vacancy is a number at all"
        )

    def _hire(self, organization, slug, facility, hr_manager):
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Hiring"))
        department = Department.objects.filter(facility=facility).first()
        people = {}

        for first, last, position_code, employment_type, probation, _ in STAFF:
            existing = Employee.objects.filter(
                first_name=first, last_name=last
            ).first()
            if existing:
                people[position_code + first] = existing
                continue

            position = Position.objects.get(code=position_code)
            employee = hire(
                facility=facility,
                first_name=first,
                last_name=last,
                actor=hr_manager,
                position=position,
                department=department,
                employment_type=employment_type,
                probation_days=probation,
                joined_on=timezone.localdate() - timedelta(days=400),
                phone="+977-98-4000000",
            )
            people[position_code + first] = employee
            self.stdout.write(
                f"   {employee.employee_code} {employee.full_name} — "
                f"{position.title} ({employee.get_employment_type_display()})"
                + (
                    f", probation to {employee.probation_ends_on}"
                    if employee.probation_ends_on else ""
                )
            )

        # Onboarding proper: the consultant gets her own login, her seat is
        # checked against the plan, and the doctor role is assigned in one
        # act. Previously this seed borrowed the counter assistant's account,
        # which worked mechanically and said something false about who was
        # prescribing.
        doctor = people["POS-MED-01Sabina"]
        if not doctor.user_id:
            try:
                user = provision_login(
                    organization=organization,
                    employee=doctor,
                    email=f"doctor@{slug}.test",
                    actor=hr_manager,
                    role_code="doctor",
                    scope="department",
                )
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
                self.stdout.write(
                    f"   {doctor.full_name} onboarded: login {user.email}, "
                    "seat checked against the plan, doctor role assigned"
                )
            except Exception as exc:      # noqa: BLE001 - reported, not swallowed
                self.stdout.write(self.style.WARNING(
                    f"   login not provisioned: {exc}"
                ))
        doctor.refresh_from_db()

        resolved = Employee.for_user(doctor.user_id) if doctor.user_id else None
        self.stdout.write(
            f"   login {doctor.work_email or '—'} resolves to "
            f"{resolved.employee_code if resolved else 'nobody'} — this is what "
            "lets a prescription print a prescriber's name and council number"
        )
        return people

    # -- credentials -------------------------------------------------------

    def _credentials(self, people, hr_manager, director):
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. Credentials"))
        today = timezone.localdate()

        for (first, last, position_code, _, _, offset) in STAFF:
            if offset is None:
                continue
            employee = people[position_code + first]
            council = (
                "Nepal Medical Council"
                if position_code.startswith("POS-MED")
                else "Nepal Nursing Council"
            )
            credential, _created = Credential.objects.update_or_create(
                employee=employee,
                credential_type=CredentialType.COUNCIL_REGISTRATION,
                defaults={
                    "name": f"{council} registration",
                    "issuing_body": council,
                    "reference_number": f"NMC-{employee.employee_code[-4:]}",
                    "issued_on": today - timedelta(days=1200),
                    "expires_on": today + timedelta(days=offset),
                },
            )
            state = (
                f"expired {abs(offset)} days ago" if offset < 0
                else f"valid for {offset} more days"
            )
            self.stdout.write(
                f"   {employee.full_name}: {credential.name} — {state}"
            )

        # Verification is a separate act from recording the claim.
        subject = people["POS-MED-01Sabina"]
        credential = subject.credentials.first()

        # The holder cannot attest their own paperwork. Only demonstrable when
        # the employee has a login to compare against.
        if subject.user_id:
            holder = User.objects.filter(uuid=subject.user_id).first()
            try:
                verify_credential(credential, actor=holder)
            except SegregationOfDutiesViolation as exc:
                self.stdout.write(
                    f"   self-verification refused: {exc}"
                )
            else:
                self.stdout.write(self.style.ERROR(
                    "   the holder verified their own registration — which is "
                    "exactly how a forged one survives"
                ))

        verify_credential(
            credential, actor=director,
            notes="Checked against the council register on 2026-09-03.",
        )
        credential.refresh_from_db()
        self.stdout.write(
            f"   {credential.name} for {subject.full_name} is now "
            f"{credential.get_verification_status_display().lower()} "
            f"by {credential.verified_by_name}"
        )

    def _practice_check(self, people):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n4. Who may treat patients")
        )
        for key, employee in people.items():
            if not employee.is_provider:
                continue
            blockers = practice_blockers(employee)
            if blockers:
                self.stdout.write(self.style.WARNING(
                    f"   {employee.full_name} may NOT practise: "
                    + "; ".join(b["message"] for b in blockers)
                ))
                try:
                    assert_may_practise(employee)
                except NotPractising:
                    pass
                else:
                    self.stdout.write(self.style.ERROR(
                        "   ...and yet the hard check let them through"
                    ))
            else:
                self.stdout.write(
                    f"   {employee.full_name} may practise"
                )

        # A nurse is clinical and is not a provider. The distinction matters:
        # she may not be scheduled for consultations, and her registration
        # still has to be current.
        nurse = people["POS-NUR-01Manisha"]
        self.stdout.write(
            f"   {nurse.full_name} is clinical but not a provider — she is "
            "not scheduled for consultations, and her registration is still "
            f"checked ({'clear' if not practice_blockers(nurse) else 'blocked'})"
        )

    # -- movement ----------------------------------------------------------

    def _promote(self, facility, people, hr_manager):
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. A promotion"))
        officer = people["POS-MED-02Prakash"]

        if officer.on_probation or officer.probation_overdue:
            confirm(officer, actor=hr_manager, notes="Probation completed.")
            officer.refresh_from_db()
            self.stdout.write(
                f"   {officer.full_name} confirmed on {officer.confirmed_on}, "
                f"now {officer.get_employment_type_display().lower()}"
            )

        before_department = (
            officer.department.name if officer.department else "—"
        )
        consultant = Position.objects.get(code="POS-MED-01")
        if officer.position_id == consultant.pk:
            # Already promoted by an earlier run. The service correctly
            # refuses a move that changes nothing; the seed should notice
            # rather than crash.
            self.stdout.write(
                f"   {officer.full_name} is already {consultant.title} — "
                "promotion skipped on a re-run"
            )
            self._show_history(officer)
            return
        transfer(
            officer,
            actor=hr_manager,
            reason="Two years' service and completion of specialist training.",
            position=consultant,
        )
        officer.refresh_from_db()

        self._show_history(officer)
        self.stdout.write(
            f"   the old posting survives in the history ({before_department}), "
            "which a mutated row could not have told us"
        )

        latest = history[0]
        if latest.event_type != EventType.PROMOTION:
            self.stdout.write(self.style.ERROR(
                f"   a position change was filed as {latest.event_type} — "
                "internal-mobility reporting would miss it"
            ))

    def _show_history(self, employee):
        history = list(employee.events.all())
        self.stdout.write(
            f"   {employee.full_name} is now {employee.position.title}; "
            f"{len(history)} events on the record"
        )
        for event in history:
            self.stdout.write(
                f"     {event.effective_on} "
                f"{event.get_event_type_display().lower():<24} {event.summary}"
            )

    def _contracts(self, people, hr_manager):
        self.stdout.write(self.style.MIGRATE_HEADING("\n6. Terms"))
        employee = people["POS-MED-01Sabina"]
        first = issue_contract(
            employee=employee,
            starts_on=employee.joined_on,
            basic_salary=Decimal("120000.00"),
            actor=hr_manager,
            allowances={"transport": "5000.00", "communication": "2000.00"},
        )
        self.stdout.write(
            f"   {employee.full_name}: basic {first.basic_salary} + "
            f"allowances = gross {first.gross_monthly}"
        )
        expected = Decimal("127000.00")
        if first.gross_monthly != expected:
            self.stdout.write(self.style.ERROR(
                f"   gross should be {expected} and is {first.gross_monthly}"
            ))

        second = issue_contract(
            employee=employee,
            starts_on=timezone.localdate(),
            basic_salary=Decimal("138000.00"),
            actor=hr_manager,
            allowances={"transport": "5000.00", "communication": "2000.00"},
        )
        first.refresh_from_db()
        self.stdout.write(
            f"   revised to {second.gross_monthly}; the old terms are "
            f"{first.get_status_display().lower()} rather than overwritten, so "
            "last year's payslips are still explicable"
        )

    def _separate(self, people, hr_manager):
        self.stdout.write(self.style.MIGRATE_HEADING("\n7. A departure"))
        leaver = people["POS-NUR-01Kiran"]
        if leaver.status == EmployeeStatus.SEPARATED:
            self.stdout.write(f"   {leaver.full_name} has already left")
            return

        separate(
            leaver,
            actor=hr_manager,
            reason="Resigned to move abroad.",
            event_type=EventType.RESIGNATION,
        )
        leaver.refresh_from_db()
        self.stdout.write(
            f"   {leaver.full_name} left on {leaver.separated_on}; the record "
            "stays, because everything they did still points at it"
        )
        self.stdout.write(
            f"   still findable by code: "
            f"{Employee.objects.filter(employee_code=leaver.employee_code).exists()}"
        )

    # -- reporting ---------------------------------------------------------

    def _report(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n8. Where we stand"))
        stats = headcount(facility)
        self.stdout.write(
            f"   {stats['total']} working; {stats['filled']} of "
            f"{stats['budgeted']} budgeted posts filled, "
            f"{stats['vacancies']} vacant"
        )
        for row in stats["vacant_positions"]:
            self.stdout.write(
                f"     {row['title']}: {row['filled']} of {row['budgeted']} "
                f"— {row['vacancies']} short"
            )
        if stats["probation_overdue"]:
            self.stdout.write(self.style.WARNING(
                f"   {stats['probation_overdue']} past their probation date "
                "with nobody having confirmed or terminated them"
            ))

        expiring = expiring_credentials(facility)
        self.stdout.write(f"   {len(expiring)} credentials expiring or expired:")
        for row in expiring:
            marker = "EXPIRED" if row["is_expired"] else f"{row['days_to_expiry']}d"
            blocking = " — BLOCKS PRACTICE" if row["blocks_practice"] else ""
            self.stdout.write(
                f"     {row['employee_name']:<20} {row['name']:<32} "
                f"{marker}{blocking}"
            )

        unverified = sum(
            1 for row in expiring
            if row["verification_status"] == VerificationStatus.UNVERIFIED
        )
        if unverified:
            self.stdout.write(
                f"   {unverified} of those have never been checked against "
                "the issuing register"
            )

        self.stdout.write(self.style.SUCCESS("\nWorkforce seeded.\n"))
