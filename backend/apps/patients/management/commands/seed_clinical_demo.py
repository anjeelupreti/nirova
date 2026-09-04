"""Seed patients, provider schedules, appointments and a live queue.

Like `seed_demo`, this runs the real service functions rather than inserting
rows. Registration goes through duplicate detection and quota checks; booking
goes through slot-capacity checks. A successful run is therefore evidence the
clinical path works, not just that the tables exist.
"""

from datetime import date, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.identity.models import User
from apps.organization.models import Department, Facility
from apps.patients.models import (
    AllergySeverity,
    Patient,
    BloodGroup,
    Gender,
    PatientAllergy,
    PatientCategory,
    PatientCondition,
)
from apps.patients.services import register_patient
from apps.scheduling.models import Appointment, AppointmentSource, ProviderSchedule
from apps.scheduling.services import (
    book_appointment,
    call_next,
    issue_token,
    queue_statistics,
    start_service,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

# Representative of a Kathmandu valley OPD: a spread of ages, districts and
# payer categories, including the awkward cases the model has to handle --
# an estimated age, a patient with no phone, a corporate account.
PATIENTS = [
    {
        "first_name": "Sita", "last_name": "Tamang", "gender": Gender.FEMALE,
        "date_of_birth": date(1988, 4, 12), "phone": "+977-9841234567",
        "district": "Kathmandu", "municipality": "Kathmandu Metropolitan City",
        "ward": "16", "blood_group": BloodGroup.O_POS,
        "category": PatientCategory.GENERAL,
    },
    {
        "first_name": "Ram", "middle_name": "Bahadur", "last_name": "Shrestha",
        "gender": Gender.MALE, "date_of_birth": date(1959, 1, 20),
        "phone": "+977-9851122334", "district": "Lalitpur",
        "municipality": "Lalitpur Metropolitan City", "ward": "7",
        "blood_group": BloodGroup.B_POS, "category": PatientCategory.GENERAL,
        "alerts": "Hard of hearing — speak to the left side.",
    },
    {
        "first_name": "Anjali", "last_name": "Gurung", "gender": Gender.FEMALE,
        "date_of_birth": date(2019, 8, 3), "phone": "+977-9812345678",
        "district": "Bhaktapur", "municipality": "Bhaktapur Municipality",
        "guardian_name": "Kamala Gurung", "guardian_relationship": "Mother",
        "guardian_phone": "+977-9812345678", "is_guardian_required": True,
        "blood_group": BloodGroup.A_POS,
    },
    {
        # No documents, no phone, age estimated on arrival. This is the case
        # a registration form must not refuse.
        "first_name": "Unknown", "last_name": "Male",
        "gender": Gender.MALE, "stated_age_years": 45, "is_dob_estimated": True,
        "district": "Kathmandu", "alerts": "Brought unconscious by passer-by.",
        "category": PatientCategory.CHARITY,
    },
    {
        "first_name": "Bishnu", "last_name": "Maharjan", "gender": Gender.MALE,
        "date_of_birth": date(1975, 11, 30), "phone": "+977-9801122001",
        "district": "Kathmandu", "municipality": "Kirtipur Municipality",
        "blood_group": BloodGroup.AB_NEG, "category": PatientCategory.CORPORATE,
        "corporate_account": "Nepal Telecom",
    },
    {
        "first_name": "Kamala", "last_name": "Adhikari", "gender": Gender.FEMALE,
        "date_of_birth": date(1996, 6, 15), "phone": "+977-9860011223",
        "district": "Kavrepalanchok", "municipality": "Dhulikhel Municipality",
        "blood_group": BloodGroup.O_NEG, "category": PatientCategory.INSURANCE,
        "insurance_policy_number": "NIB-2026-88114",
    },
]

DOCTORS = [
    ("Dr. Prakash Rana", "General Medicine", time(9, 0), time(13, 0), 15, 1, 2),
    ("Dr. Meena Joshi", "Paediatrics", time(10, 0), time(14, 0), 20, 1, 3),
    ("Dr. Suresh Karki", "Orthopaedics", time(14, 0), time(17, 0), 20, 2, 1),
]


class Command(BaseCommand):
    help = "Seed patients, schedules, appointments and a queue for a tenant."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError(
                f"No organization '{options['slug']}'. Run `seed_demo` first."
            )

        actor = User.objects.filter(
            email=f"manager@{options['slug']}.test"
        ).first() or User.objects.filter(is_platform_staff=True).first()

        context = context_for_organization(organization)
        with tenant_context(context):
            facility = Facility.objects.filter(facility_type="clinic").first()
            if facility is None:
                raise CommandError("No clinic facility. Run `seed_demo` first.")

            patients = self._patients(organization, facility, actor)
            self._clinical_history(patients)
            schedules = self._schedules(facility)
            appointments = self._appointments(
                organization, patients, facility, schedules, actor
            )
            self._queue(organization, patients, facility, appointments, actor)
            self._report(facility)

    # -- steps -----------------------------------------------------------

    def _patients(self, organization, facility, actor):
        """Register the demo cohort, skipping anyone already present.

        `force=True` bypasses duplicate detection, because these are six
        known-distinct people and two of them share a district and a surname
        pattern that would otherwise trip it. That makes the seed itself
        responsible for not double-registering on a re-run, so it checks
        first -- otherwise every run would add six more patients.
        """
        created = []
        for spec in PATIENTS:
            existing = Patient.objects.filter(
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                date_of_birth=spec.get("date_of_birth"),
            ).first()
            if existing:
                created.append(existing)
                self.stdout.write(f"  {existing.mrn}  {existing.full_name} (existing)")
                continue

            patient = register_patient(
                organization=organization,
                data=dict(spec),
                actor=actor,
                facility=facility,
                force=True,
            )
            created.append(patient)
            self.stdout.write(f"  {patient.mrn}  {patient.full_name}")
        return created

    def _clinical_history(self, patients):
        """Give a few patients history, so prescribing has something to check."""
        PatientAllergy.objects.get_or_create(
            patient=patients[1],
            substance="Penicillin",
            defaults={
                "category": "medication",
                "reaction": "Urticaria and facial swelling",
                "severity": AllergySeverity.SEVERE,
            },
        )
        PatientAllergy.objects.get_or_create(
            patient=patients[2],
            substance="Peanuts",
            defaults={
                "category": "food",
                "reaction": "Anaphylaxis",
                "severity": AllergySeverity.LIFE_THREATENING,
            },
        )
        PatientCondition.objects.get_or_create(
            patient=patients[1],
            name="Type 2 diabetes mellitus",
            defaults={"icd10_code": "E11", "onset_date": date(2016, 3, 1)},
        )
        PatientCondition.objects.get_or_create(
            patient=patients[4],
            name="Essential hypertension",
            defaults={"icd10_code": "I10", "onset_date": date(2021, 7, 14)},
        )
        self.stdout.write("  clinical history recorded")

    def _schedules(self, facility):
        department = Department.objects.filter(facility=facility, code="OPD").first()
        schedules = []
        for index, (name, speciality, start, end, minutes, capacity, reserve) in enumerate(
            DOCTORS
        ):
            # One schedule per weekday, Sunday to Friday — the Nepali week.
            for weekday in range(0, 6):
                schedule, _ = ProviderSchedule.objects.get_or_create(
                    provider_uuid=_stable_uuid(index),
                    facility=facility,
                    weekday=weekday,
                    start_time=start,
                    defaults={
                        "provider_name": name,
                        "provider_speciality": speciality,
                        "department": department,
                        "room": f"OPD-{index + 1}",
                        "end_time": end,
                        "slot_minutes": minutes,
                        "slot_capacity": capacity,
                        "walk_in_reserve": reserve,
                        "consultation_fee": 800 + index * 200,
                    },
                )
                schedules.append(schedule)
        self.stdout.write(f"  {len(DOCTORS)} providers, {len(schedules)} sessions")
        return schedules

    def _appointments(self, organization, patients, facility, schedules, actor):
        """Book into the next sessions that still have future slots.

        Walks forward day by day rather than assuming today works: the seed
        may be run in the afternoon, when the morning OPD is already over, or
        on a Saturday when nobody is consulting.
        """
        target, sessions = self._next_booking_day(schedules)
        if not sessions:
            self.stdout.write(self.style.WARNING("  no sessions in the next week"))
            return []
        self.stdout.write(f"  booking into {target:%Y-%m-%d}")

        booked = []
        for index, patient in enumerate(patients[:4]):
            schedule = sessions[index % len(sessions)]
            slots = [
                slot for slot in schedule.slot_times(target) if slot > timezone.now()
            ]
            if not slots:
                continue

            # Reuse this patient's booking for the day if the seed has already
            # made one. Booking unconditionally filled the slot on every run
            # until it hit its capacity of two, after which this seed refused
            # itself with "that slot already holds 2 of 2 bookings" and stayed
            # broken. A seed that only works on a clean database stops being
            # run, and these seeds are how the system is verified.
            existing = Appointment.objects.filter(
                patient=patient, scheduled_for__date=target,
            ).first()
            if existing is not None:
                booked.append(existing)
                self.stdout.write(
                    f"  {existing.reference}  {patient.full_name} -> "
                    f"{existing.provider_name} @ {existing.scheduled_for:%H:%M}"
                    "  (already booked)"
                )
                continue

            appointment = book_appointment(
                organization=organization,
                patient=patient,
                facility=facility,
                scheduled_for=slots[index % len(slots)],
                schedule=schedule,
                reason=["Fever and cough", "Diabetes review", "Rash",
                        "Collapse — brought in"][index],
                source=AppointmentSource.COUNTER,
                actor=actor,
            )
            booked.append(appointment)
            self.stdout.write(
                f"  {appointment.reference}  {patient.full_name} -> "
                f"{appointment.provider_name} @ {appointment.scheduled_for:%H:%M}"
            )
        return booked

    @staticmethod
    def _next_booking_day(schedules):
        """First day within a week that has a session with a future slot."""
        for offset in range(0, 8):
            target = timezone.localdate() + timedelta(days=offset)
            sessions = [
                schedule
                for schedule in schedules
                if schedule.applies_on(target)
                and any(slot > timezone.now() for slot in schedule.slot_times(target))
            ]
            if sessions:
                return target, sessions
        return timezone.localdate(), []

    def _queue(self, organization, patients, facility, appointments, actor):
        department = Department.objects.filter(facility=facility, code="OPD").first()

        for appointment in appointments[:3]:
            issue_token(
                organization=organization,
                patient=appointment.patient,
                facility=facility,
                department=department,
                appointment=appointment,
                actor=actor,
            )

        # A walk-in emergency: no appointment, jumps the queue.
        emergency = issue_token(
            organization=organization,
            patient=patients[3],
            facility=facility,
            department=department,
            is_emergency=True,
            actor=actor,
        )
        self.stdout.write(
            self.style.WARNING(
                f"  {emergency.token_number} issued as an emergency "
                f"(priority {emergency.priority})"
            )
        )

        called = call_next(facility, department)
        if called:
            start_service(called)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  called {called.token_number} - {called.patient.full_name}"
                    + ("  [emergency first]" if called.is_emergency else "")
                )
            )

    def _report(self, facility):
        stats = queue_statistics(facility)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Queue today"))
        for key in ("total_tokens", "waiting", "in_service", "emergencies",
                    "average_wait_minutes"):
            self.stdout.write(f"  {key.replace('_', ' '):<22} {stats[key]}")


def _stable_uuid(index: int) -> str:
    """A repeatable provider UUID, so re-running the seed does not duplicate.

    Providers will become HRMS employees with real UUIDs; until then a fixed
    value keeps the seed idempotent.
    """
    return f"00000000-0000-4000-8000-{index:012d}"
