"""Admit, move, charge and discharge an inpatient.

Through the real service layer:

1. Wards and beds, including one out of service and one gender-restricted.
2. An admission that takes a bed, and a second refused for the same patient.
3. A bed placement refused on gender, and refused on a bed being cleaned.
4. A transfer from a general ward to the ICU, and the history it leaves.
5. Daily accrual: run once, run again, and prove the second run charges
   nothing.
6. A stay spanning two wards charged at two different rates, day by day.
7. Discharge blocked by clearances and an unpaid balance, then overridden with
   a stated reason.
8. Census and outcomes, computed rather than stored.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.billing.models import ServiceCategory, ServiceItem, TaxTreatment
from apps.identity.models import User
from apps.inpatient.models import (
    AccrualKind,
    Admission,
    AdmissionStatus,
    Bed,
    BedAssignment,
    BedStatus,
    ClearanceKind,
    DailyAccrual,
    Gender,
    Ward,
    WardType,
)
from apps.inpatient.services import (
    DischargeBlocked,
    InpatientError,
    accrue_all,
    accrue_day,
    admit,
    available_beds,
    backfill_accruals,
    census,
    clear,
    discharge,
    discharge_blockers,
    fluid_balance,
    initiate_discharge,
    outcomes,
    record_round,
    set_bed_status,
    stay_charges,
    transfer_bed,
    ward_occupancy,
)
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: (code, name, type, beds, daily rate, service code)
WARDS = [
    ("GW-A", "General Ward A", WardType.GENERAL, 6, "1500.00", "IPD-BED-GEN"),
    ("PVT", "Private Rooms", WardType.PRIVATE, 3, "4500.00", "IPD-BED-PVT"),
    ("ICU", "Intensive Care", WardType.ICU, 4, "12000.00", "IPD-BED-ICU"),
]

#: (service code, name, category, price)
SERVICES = [
    ("IPD-BED-GEN", "General ward bed, per day", "1500.00"),
    ("IPD-BED-PVT", "Private room, per day", "4500.00"),
    ("IPD-BED-ICU", "Intensive care bed, per day", "12000.00"),
]


class Command(BaseCommand):
    help = "Admit, move, charge and discharge an inpatient."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        clerk = User.objects.filter(email=f"manager@{slug}.test").first()
        consultant = User.objects.filter(email=f"doctor@{slug}.test").first()
        matron = User.objects.filter(email=f"owner@{slug}.test").first()
        if not (clerk and matron):
            raise CommandError("Run `seed_demo` first.")

        with tenant_context(context_for_organization(organization)):
            facility = (
                Facility.objects.filter(facility_type="hospital").first()
                or Facility.objects.filter(facility_type="clinic").first()
            )
            if facility is None:
                raise CommandError("No facility. Run `seed_demo` first.")

            patients = list(
                Patient.objects.filter(merged_into__isnull=True)[:3]
            )
            if not patients:
                raise CommandError("No patients. Run `seed_demo` first.")

            self._services(facility)
            self._wards(facility)
            self._bed_rules(facility, patients[0], clerk)
            admission = self._admit(
                organization, facility, patients[0], clerk, consultant
            )
            self._transfer(facility, admission, clerk)
            self._accrue(organization, facility, admission, clerk)
            self._nursing(admission, matron)
            self._discharge(organization, admission, clerk, matron)
            self._report(facility)

    # -- setup -------------------------------------------------------------

    def _services(self, facility):
        for code, name, price in SERVICES:
            ServiceItem.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": ServiceCategory.BED,
                    "default_price": Decimal(price),
                    "tax_treatment": TaxTreatment.EXEMPT,
                    "is_recurring_daily": True,
                },
            )

    def _wards(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Wards and beds"))
        for code, name, kind, count, rate, service in WARDS:
            ward, _ = Ward.objects.update_or_create(
                facility=facility, code=code,
                defaults={
                    "name": name, "ward_type": kind,
                    "nurse_to_patient_ratio": (
                        Decimal("1.00") if kind == WardType.ICU
                        else Decimal("6.00")
                    ),
                },
            )
            for index in range(1, count + 1):
                Bed.objects.update_or_create(
                    ward=ward, code=f"{code}-{index:02d}",
                    defaults={
                        "daily_rate": Decimal(rate),
                        "service_code": service,
                        "has_oxygen": kind == WardType.ICU,
                        "has_monitor": kind == WardType.ICU,
                        "has_ventilator": kind == WardType.ICU,
                    },
                )

        general = Ward.objects.get(facility=facility, code="GW-A")
        # One bed out of service and one reserved for women, so the placement
        # rules have something real to refuse.
        broken = general.beds.order_by("code").last()
        if broken.status != BedStatus.MAINTENANCE:
            set_bed_status(
                broken, BedStatus.MAINTENANCE,
                reason="Bed rail broken; engineering notified.",
            )
        female_bed = general.beds.order_by("code")[1]
        female_bed.gender_restriction = Gender.FEMALE
        female_bed.save(update_fields=["gender_restriction", "updated_at"])

        occupancy = ward_occupancy(general)
        self.stdout.write(
            f"   {len(WARDS)} wards, "
            f"{Bed.objects.filter(ward__facility=facility).count()} beds"
        )
        self.stdout.write(
            f"   {general.name}: {occupancy['total_beds']} beds — "
            f"{occupancy['available']} available, {occupancy['unusable']} "
            f"unusable ({occupancy['occupancy_percent']}% occupied)"
        )
        self.stdout.write(
            "   occupancy is against total beds, not against usable ones: a "
            "ward with half its beds broken is a maintenance problem, not a "
            "full ward"
        )

    def _bed_rules(self, facility, patient, actor):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n2. What a bed will refuse")
        )
        general = Ward.objects.get(facility=facility, code="GW-A")
        broken = general.beds.filter(status=BedStatus.MAINTENANCE).first()
        if broken:
            self.stdout.write(
                f"   {broken.code} is {broken.status}: {broken.status_reason}"
            )
            free = available_beds(ward=general)
            if broken in free:
                self.stdout.write(self.style.ERROR(
                    "   ...and it still appears as available"
                ))
            else:
                self.stdout.write(
                    "   it does not appear in the available list — a bed being "
                    "unoccupied does not make it usable"
                )

        female_bed = general.beds.filter(
            gender_restriction=Gender.FEMALE
        ).first()
        if female_bed:
            male_beds = available_beds(ward=general, gender="male")
            self.stdout.write(
                f"   {female_bed.code} is reserved for women: "
                f"{len(available_beds(ward=general))} beds free overall, "
                f"{len(male_beds)} of them for a male patient"
            )
            if female_bed in male_beds:
                self.stdout.write(self.style.ERROR(
                    "   ...and it was offered for a male patient anyway"
                ))

    # -- admitting ---------------------------------------------------------

    def _admit(self, organization, facility, patient, clerk, consultant):
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. Admitting"))

        # Close anything left open by an earlier run.
        for stale in Admission.objects.filter(
            patient=patient, status__in=["admitted", "discharge_initiated"]
        ):
            discharge(
                stale, actor=clerk, summary="Closed by a seed re-run.",
                override_reason="Seed re-run.",
            )

        general = Ward.objects.get(facility=facility, code="GW-A")
        admission = admit(
            organization=organization,
            patient=patient,
            facility=facility,
            actor=clerk,
            ward=general,
            source="emergency",
            consultant=consultant,
            consultant_name="Sabina Rana",
            admitting_diagnosis="Community-acquired pneumonia.",
            expected_discharge=timezone.localdate() + timedelta(days=4),
            deposit_expected=Decimal("15000.00"),
            attendant_name="Hari Prasad",
            attendant_phone="+977-98-11111111",
            attendant_relation="Brother",
        )
        bed = admission.current_bed
        self.stdout.write(
            f"   {admission.reference}: {patient.full_name} into "
            f"{bed} at {admission.admitted_at:%H:%M}"
        )
        self.stdout.write(
            f"   {admission.clearances.count()} discharge clearances created "
            "at admission — the list is visible from day one rather than "
            "assembled in a hurry on the morning somebody wants to go home"
        )

        try:
            admit(organization, patient, facility, actor=clerk, ward=general)
        except InpatientError as exc:
            self.stdout.write(f"   second admission refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   the same patient was admitted twice"
            ))
        return admission

    def _transfer(self, facility, admission, actor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. A transfer"))
        icu = Ward.objects.get(facility=facility, code="ICU")
        before = admission.current_bed

        # Move them back a day so the stay spans two rates.
        assignment = admission.bed_assignments.filter(
            vacated_at__isnull=True
        ).first()
        assignment.occupied_at = timezone.now() - timedelta(days=3)
        assignment.save(update_fields=["occupied_at"])
        admission.admitted_at = assignment.occupied_at
        admission.save(update_fields=["admitted_at"])

        icu_bed = available_beds(ward=icu)[0]
        transfer_bed(
            admission, icu_bed, actor=actor,
            reason="Rising oxygen requirement; needs continuous monitoring.",
        )

        # And backdate the ICU move to yesterday, so the accrual has two rates
        # to get right.
        new_assignment = admission.bed_assignments.filter(
            vacated_at__isnull=True
        ).first()
        new_assignment.occupied_at = timezone.now() - timedelta(days=1)
        new_assignment.save(update_fields=["occupied_at"])
        old = admission.bed_assignments.filter(
            vacated_at__isnull=False
        ).order_by("-occupied_at").first()
        old.vacated_at = new_assignment.occupied_at
        old.save(update_fields=["vacated_at"])

        self.stdout.write(
            f"   {before} -> {icu_bed} ({before.daily_rate} -> "
            f"{icu_bed.daily_rate} a day)"
        )
        for row in admission.bed_assignments.order_by("occupied_at"):
            until = (
                f"{row.vacated_at:%d %b %H:%M}" if row.vacated_at else "still there"
            )
            self.stdout.write(
                f"     {row.bed} from {row.occupied_at:%d %b %H:%M} to {until} "
                f"at {row.daily_rate}/day"
            )
        self.stdout.write(
            "   the old bed is not overwritten — which is what answers "
            "'who was in that bed on the night of the 14th?'"
        )
        if before.status != BedStatus.CLEANING:
            before.refresh_from_db()
        self.stdout.write(
            f"   {before} is now {before.status} — a bed somebody has just "
            "left is not ready for the next patient"
        )

    # -- money -------------------------------------------------------------

    def _accrue(self, organization, facility, admission, actor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Daily accrual"))

        result = backfill_accruals(organization, admission, actor=actor)
        self.stdout.write(
            f"   backfilled {result['accrued']} days of the stay"
        )

        rows = list(admission.accruals.order_by("accrual_date"))
        expected = Decimal("0")
        for row in rows:
            self.stdout.write(
                f"     {row.accrual_date}  {row.description:<34} "
                f"{row.amount:>10}"
            )
            expected += row.amount
        self.stdout.write(
            f"   {len(rows)} days totalling {expected} — two rates, because "
            "the patient moved wards mid-stay"
        )

        rates = {row.unit_rate for row in rows}
        if len(rates) < 2:
            self.stdout.write(self.style.ERROR(
                f"   every day accrued at the same rate ({rates}) — the "
                "transfer was not reflected in the charges"
            ))

        # The whole point: run it again.
        before_count = DailyAccrual.objects.filter(admission=admission).count()
        before_total = sum(
            row.amount for row in DailyAccrual.objects.filter(admission=admission)
        )
        again = backfill_accruals(organization, admission, actor=actor)
        after_count = DailyAccrual.objects.filter(admission=admission).count()
        after_total = sum(
            row.amount for row in DailyAccrual.objects.filter(admission=admission)
        )
        self.stdout.write(
            f"   run again: {again['accrued']} new accruals, "
            f"{before_count} -> {after_count} rows, "
            f"{before_total} -> {after_total}"
        )
        if after_count != before_count or after_total != before_total:
            self.stdout.write(self.style.ERROR(
                "   the second run charged again — a nightly job that ran "
                "twice would double every patient's bill"
            ))
        else:
            self.stdout.write(
                "   nothing changed, which is the point: the job can be "
                "re-run for a missed night without double-charging anybody"
            )

        nightly = accrue_all(organization, facility, actor=actor)
        self.stdout.write(
            f"   nightly job across the facility: {nightly['admissions']} "
            f"in-house, {nightly['accrued']} accrued, "
            f"{nightly['already_done_or_skipped']} already done"
        )
        if nightly["admissions_without_a_bed_rate"]:
            self.stdout.write(self.style.WARNING(
                "   no bed rate for: "
                + ", ".join(nightly["admissions_without_a_bed_rate"])
            ))

        charges = stay_charges(admission)
        self.stdout.write(
            f"   the bill so far: {charges['nights']} nights, accrued "
            f"{charges['accrued_total']}, charged {charges['charge_total']}, "
            f"of which {charges['uninvoiced']} is not yet invoiced"
        )
        if charges["unbilled_accruals"]:
            self.stdout.write(self.style.WARNING(
                f"   {charges['unbilled_accruals']} accruals produced no "
                "charge — a day that happened and was never billed"
            ))

    def _nursing(self, admission, actor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n6. Nursing"))
        record_round(
            admission, actor=actor, shift="morning",
            intake_ml=900, output_ml=650, pain_score=4,
            observations="Alert, oriented. Sats 94% on 2L.",
            interventions="Nebulised salbutamol given.",
        )
        record_round(
            admission, actor=actor, shift="evening",
            intake_ml=750, output_ml=1100, pain_score=6,
            observations="More breathless on exertion. Sats 90% on 2L.",
            interventions="Oxygen increased to 4L; doctor informed.",
            escalate=True,
            escalation_reason="Falling saturations despite increased oxygen.",
        )
        balance = fluid_balance(admission)
        self.stdout.write(
            f"   {balance['rounds']} rounds in 24h: in {balance['intake_ml']}ml, "
            f"out {balance['output_ml']}ml, balance "
            f"{balance['balance_ml']:+}ml"
        )
        expected = 1650 - 1750
        if balance["balance_ml"] != expected:
            self.stdout.write(self.style.ERROR(
                f"   expected {expected:+}ml, got {balance['balance_ml']:+}ml"
            ))
        if balance["escalations"]:
            self.stdout.write(self.style.WARNING(
                f"   {balance['escalations']} escalation to a doctor"
            ))

    # -- leaving -----------------------------------------------------------

    def _discharge(self, organization, admission, clerk, matron):
        self.stdout.write(self.style.MIGRATE_HEADING("\n7. Discharge"))
        initiate_discharge(
            admission, actor=matron, notes="Consultant says home today."
        )
        admission.refresh_from_db()
        self.stdout.write(
            f"   {admission.reference} is {admission.status} — a separate "
            "state from discharged, because the hours between the two are "
            "where bed-turnaround time is lost"
        )

        blockers = discharge_blockers(admission)
        self.stdout.write(f"   {len(blockers)} things standing in the way:")
        for blocker in blockers:
            self.stdout.write(f"     {blocker['code']:<22} {blocker['message']}")

        try:
            discharge(admission, actor=clerk, summary="Recovered.")
        except DischargeBlocked as exc:
            self.stdout.write(f"   discharge refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   the patient left with the bill unreconciled"
            ))

        for kind in (
            ClearanceKind.CLINICAL, ClearanceKind.NURSING,
            ClearanceKind.PHARMACY, ClearanceKind.RECORDS,
        ):
            clear(admission, kind, actor=matron)
        clear(
            admission, ClearanceKind.BILLING, actor=clerk, cleared=False,
            reason="Deposit taken but the final bill is not settled.",
        )
        remaining = discharge_blockers(admission)
        self.stdout.write(
            f"   after four sign-offs, {len(remaining)} remain:"
        )
        for blocker in remaining:
            self.stdout.write(f"     {blocker['code']:<22} {blocker['message']}")

        bed_before = admission.current_bed
        discharge(
            admission, actor=matron,
            summary=(
                "Community-acquired pneumonia, treated with IV antibiotics "
                "and oxygen. Afebrile 48 hours, saturations 96% on air."
            ),
            advice="Complete the oral antibiotic course. Return if breathless.",
            follow_up_on=timezone.localdate() + timedelta(days=7),
            final_diagnosis="Community-acquired pneumonia, resolved.",
            override_reason=(
                "Family settling the balance by bank transfer tomorrow; "
                "authorised by the medical director."
            ),
        )
        admission.refresh_from_db()
        bed_before.refresh_from_db()
        self.stdout.write(
            f"   discharged after {admission.length_of_stay_days} nights; "
            f"{bed_before} released to {bed_before.status}"
        )

        final = stay_charges(admission)
        days = admission.accruals.count()
        self.stdout.write(
            f"   final bill: {days} bed-days against "
            f"{admission.length_of_stay_days} nights, {final['charge_total']} "
            "charged"
        )
        if days != admission.length_of_stay_days:
            self.stdout.write(self.style.ERROR(
                f"   {days} days charged for a "
                f"{admission.length_of_stay_days}-night stay — the discharge "
                "day was billed even though the bed was free that night"
            ))
        else:
            self.stdout.write(
                "   the discharge day was reversed: the bed was free that "
                "night, and a day charged on every discharge is an overcharge "
                "that survives for years because each bill looks plausible"
            )
        self.stdout.write(
            "   the override is a named, reasoned, audited act — not a silent "
            "bypass"
        )
        if admission.encounter:
            admission.encounter.refresh_from_db()
            self.stdout.write(
                f"   the encounter is now {admission.encounter.status}"
            )

    # -- reporting ---------------------------------------------------------

    def _report(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n8. The hospital today"))
        today = census(facility)
        self.stdout.write(
            f"   {today['in_house']} in house, {today['awaiting_a_bed']} "
            f"waiting for a bed; {today['occupied']} of {today['total_beds']} "
            f"beds occupied ({today['occupancy_percent']}%), "
            f"{today['unusable']} unusable"
        )
        self.stdout.write(
            f"   {today['admitted_today']} admitted today, "
            f"{today['discharged_today']} discharged"
        )
        for ward in today["by_ward"]:
            nurses = ward["nurses_needed"]
            self.stdout.write(
                f"     {ward['ward_name']:<20} {ward['occupied']}/"
                f"{ward['total_beds']} occupied"
                + (f", {nurses} nurses needed" if nurses else "")
            )
        for row in today["overstaying"]:
            self.stdout.write(self.style.WARNING(
                f"   OVERSTAYING {row['patient']} — expected out "
                f"{row['expected']}, {row['nights']} nights so far"
            ))

        result = outcomes(facility)
        self.stdout.write(
            f"   last 90 days: {result['total']} stays ended, average "
            f"{result['average_nights']} nights, mortality "
            f"{result['mortality_percent']}%, LAMA {result['lama_percent']}%"
        )
        for status, count in sorted(result["by_outcome"].items()):
            self.stdout.write(f"     {status:<18} {count}")

        self.stdout.write(self.style.SUCCESS("\nInpatient stay complete.\n"))
