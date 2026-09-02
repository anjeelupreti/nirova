"""Seed the test catalogue and run diagnostics end to end.

Exercises, through the real service layer:

1. A test catalogue with panels and age/sex-specific reference ranges.
2. A routine laboratory order: collect, receive, result, verify, release —
   with the encounter parking in `awaiting_results` and coming back when the
   last order lands.
3. A STAT order producing a **critical potassium**, raising an alert, and the
   record of who was told.
4. Verification refused when the person who entered the results tries to
   verify their own.
5. A rejected specimen, and a radiology order with a narrative report.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.billing.models import ServiceItem
from apps.common.exceptions import SegregationOfDutiesViolation
from apps.diagnostics.models import (
    DiagnosticModality,
    OrderPriority,
    ReferenceRange,
    ResultDataType,
    SpecimenType,
    TestDefinition,
)
from apps.diagnostics.services import (
    acknowledge_critical,
    collect_specimen,
    enter_results,
    notify_critical,
    place_order,
    receive_specimen,
    reject_specimen,
    turnaround_report,
    verify_order,
    worklist,
)
from apps.encounters.services import start_encounter
from apps.identity.models import User
from apps.organization.models import Department, Facility
from apps.patients.models import Patient, PatientStatus
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: (code, name, unit, decimals, service code) — the analytes of a CBC and a
#: renal panel, plus standalone tests.
LAB_TESTS = [
    ("HB", "Haemoglobin", "g/dL", 1),
    ("WBC", "White cell count", "×10⁹/L", 1),
    ("PLT", "Platelet count", "×10⁹/L", 0),
    ("NA", "Sodium", "mmol/L", 0),
    ("K", "Potassium", "mmol/L", 1),
    ("CREAT", "Creatinine", "µmol/L", 0),
    ("UREA", "Urea", "mmol/L", 1),
    ("RBS", "Random blood sugar", "mmol/L", 1),
]

#: (test code, sex, min age, max age, normal low, normal high, critical low,
#:  critical high)
#:
#: Haemoglobin is deliberately split by sex, and potassium carries critical
#: thresholds in both directions — those are the two cases the demo turns on.
RANGES = [
    ("HB", "male", 15, None, "13.0", "17.0", "7.0", "20.0"),
    ("HB", "female", 15, None, "11.5", "15.5", "7.0", "20.0"),
    ("HB", "", 0, 14, "11.0", "14.0", "7.0", "20.0"),
    ("WBC", "", None, None, "4.0", "11.0", "1.0", "30.0"),
    ("PLT", "", None, None, "150", "400", "20", "1000"),
    ("NA", "", None, None, "135", "145", "120", "160"),
    ("K", "", None, None, "3.5", "5.1", "2.5", "6.5"),
    ("CREAT", "male", 15, None, "62", "106", None, "500"),
    ("CREAT", "female", 15, None, "44", "80", None, "500"),
    ("UREA", "", None, None, "2.5", "7.8", None, "30.0"),
    ("RBS", "", None, None, "3.9", "7.8", "2.2", "25.0"),
]

PANELS = [
    ("CBC", "Complete blood count", ["HB", "WBC", "PLT"], "LAB-001", 120),
    ("RFT", "Renal function test", ["NA", "K", "CREAT", "UREA"], "LAB-003", 180),
]


class Command(BaseCommand):
    help = "Seed the diagnostics catalogue and run the workflow end to end."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError(f"No organization '{options['slug']}'.")

        doctor = User.objects.filter(email=f"owner@{options['slug']}.test").first()
        technician = User.objects.filter(
            email=f"manager@{options['slug']}.test"
        ).first()

        with tenant_context(context_for_organization(organization)):
            facility = Facility.objects.filter(facility_type="clinic").first()
            if facility is None:
                raise CommandError("No clinic facility. Run `seed_demo` first.")

            self._catalogue(facility)
            self._ensure_radiology(organization)
            self._routine(organization, facility, doctor, technician)
            self._critical(organization, facility, doctor, technician)
            self._rejection(organization, facility, doctor, technician)
            self._radiology(organization, facility, doctor, technician)
            self._report(facility)

    def _ensure_radiology(self, organization):
        """Buy the radiology module if the plan does not include it.

        The Professional plan covers laboratory but not radiology, so ordering
        a chest film is correctly refused by the entitlement engine. Rather
        than skipping that part of the demo, the seed does what a real clinic
        would: attaches the `module_radiology` add-on. That exercises the same
        mechanism the hospital facility request used, and proves the module
        gate is real rather than decorative.
        """
        from apps.catalog.models import AddOn
        from apps.entitlements.resolver import active_subscription, resolve_entitlements
        from apps.catalog.keys import ModuleCode
        from apps.subscriptions.models import SubscriptionAddOn

        if resolve_entitlements(organization).has_module(ModuleCode.RADIOLOGY):
            return

        subscription = active_subscription(organization)
        addon = AddOn.objects.filter(code="module_radiology", is_active=True).first()
        if subscription is None or addon is None:
            self.stdout.write(self.style.WARNING(
                "  radiology module unavailable; the X-ray step will be skipped"))
            return

        SubscriptionAddOn.objects.get_or_create(
            subscription=subscription,
            addon=addon,
            defaults={"quantity": 1, "unit_price": addon.unit_price,
                      "source_reference": "seed_diagnostics_demo"},
        )
        self.stdout.write(
            f"  radiology not in the {subscription.plan.code} plan — "
            f"attached the {addon.code} add-on")

    # -- catalogue -------------------------------------------------------

    def _catalogue(self, facility):
        lab_department = Department.objects.filter(
            facility=facility, code="LAB"
        ).first() or Department.objects.filter(facility=facility).first()

        analytes = {}
        for code, name, unit, decimals in LAB_TESTS:
            analyte, _ = TestDefinition.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "modality": DiagnosticModality.LABORATORY,
                    "department": lab_department,
                    "result_data_type": ResultDataType.NUMERIC,
                    "unit": unit,
                    "decimal_places": decimals,
                    "specimen_type": SpecimenType.BLOOD,
                    "turnaround_minutes": 120,
                    "is_active": True,
                },
            )
            analytes[code] = analyte

        for code, sex, min_age, max_age, low, high, crit_low, crit_high in RANGES:
            ReferenceRange.objects.update_or_create(
                test=analytes[code],
                applies_to_sex=sex,
                min_age_years=min_age,
                max_age_years=max_age,
                defaults={
                    "normal_low": Decimal(low) if low else None,
                    "normal_high": Decimal(high) if high else None,
                    "critical_low": Decimal(crit_low) if crit_low else None,
                    "critical_high": Decimal(crit_high) if crit_high else None,
                },
            )

        for code, name, members, service_code, turnaround in PANELS:
            service = ServiceItem.objects.filter(code=service_code).first()
            panel, _ = TestDefinition.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "modality": DiagnosticModality.LABORATORY,
                    "department": lab_department,
                    "is_panel": True,
                    "result_data_type": ResultDataType.GROUP,
                    "specimen_type": SpecimenType.BLOOD,
                    "turnaround_minutes": turnaround,
                    "service_uuid": service.uuid if service else None,
                    "is_active": True,
                },
            )
            for member in members:
                analytes[member].parent = panel
                analytes[member].save(update_fields=["parent", "updated_at"])

        # A standalone glucose, and a chest film with a narrative report.
        analytes["RBS"].parent = None
        rbs_service = ServiceItem.objects.filter(code="LAB-002").first()
        analytes["RBS"].service_uuid = rbs_service.uuid if rbs_service else None
        analytes["RBS"].turnaround_minutes = 30
        analytes["RBS"].save(
            update_fields=["parent", "service_uuid", "turnaround_minutes", "updated_at"]
        )

        xray_service = ServiceItem.objects.filter(code="RAD-001").first()
        TestDefinition.objects.update_or_create(
            code="CXR",
            defaults={
                "name": "Chest X-ray, PA",
                "modality": DiagnosticModality.XRAY,
                "result_data_type": ResultDataType.TEXT,
                "turnaround_minutes": 60,
                "service_uuid": xray_service.uuid if xray_service else None,
                "patient_preparation": "Remove metal objects above the waist.",
                "is_active": True,
            },
        )

        self.stdout.write(
            f"  {TestDefinition.objects.count()} tests, "
            f"{ReferenceRange.objects.count()} reference ranges"
        )

    # -- 1. routine, and the encounter parking ---------------------------

    def _routine(self, organization, facility, doctor, technician):
        patient = _live("Sita")
        cbc = TestDefinition.objects.get(code="CBC")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n1. Routine CBC - {patient.full_name} ({patient.mrn}, "
            f"{patient.gender}, {patient.age_years})"))

        encounter = start_encounter(
            organization, patient, facility, actor=doctor,
            chief_complaint="Tiredness for several weeks",
        )
        order = place_order(
            organization, patient, facility, cbc, actor=doctor,
            encounter=encounter,
            clinical_indication="Fatigue; query anaemia",
        )
        encounter.refresh_from_db()
        self.stdout.write(
            f"   {order.reference} placed; encounter now {encounter.status}")

        collect_specimen(order, actor=technician)
        order.refresh_from_db()
        self.stdout.write(f"   collected, accession {order.accession_number}")
        receive_specimen(order, actor=technician)

        # Haemoglobin 10.8 is low for an adult woman (11.5-15.5) but would be
        # normal for a child -- the range has to be selected per patient.
        results = enter_results(order, [
            {"analyte_code": "HB", "value": "10.8"},
            {"analyte_code": "WBC", "value": "7.2"},
            {"analyte_code": "PLT", "value": "280"},
        ], actor=technician)
        for result in results:
            marker = "" if not result.is_abnormal else f"  <-- {result.flag}"
            self.stdout.write(
                f"     {result.analyte_name:<20} {result.display_value:>6} "
                f"{result.unit:<10} ref {result.reference_text}{marker}")

        verify_order(order, actor=doctor)
        order.refresh_from_db()
        encounter.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f"   verified and released in {order.turnaround_minutes} min; "
            f"encounter back to {encounter.status}"))

    # -- 2. a critical value ---------------------------------------------

    def _critical(self, organization, facility, doctor, technician):
        patient = _live("Ram")
        rft = TestDefinition.objects.get(code="RFT")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n2. STAT renal panel - {patient.full_name} ({patient.mrn})"))

        order = place_order(
            organization, patient, facility, rft, actor=doctor,
            priority=OrderPriority.STAT,
            clinical_indication="Vomiting, reduced urine output; query acute "
                                "kidney injury",
        )
        collect_specimen(order, actor=technician)
        receive_specimen(order, actor=technician)

        # Potassium 6.9 is above the critical threshold of 6.5.
        results = enter_results(order, [
            {"analyte_code": "NA", "value": "131"},
            {"analyte_code": "K", "value": "6.9"},
            {"analyte_code": "CREAT", "value": "268"},
            {"analyte_code": "UREA", "value": "19.4"},
        ], actor=technician)
        for result in results:
            marker = "" if not result.is_abnormal else f"  <-- {result.flag}"
            self.stdout.write(
                f"     {result.analyte_name:<20} {result.display_value:>6} "
                f"{result.unit:<10} ref {result.reference_text}{marker}")

        alerts = list(order.critical_alerts.all())
        for alert in alerts:
            self.stdout.write(self.style.ERROR(
                f"   CRITICAL: {alert.result.analyte_name} {alert.value} "
                f"({alert.threshold}) — alert raised"))

        # The technician who entered the results must not verify them.
        try:
            verify_order(order, actor=technician)
            self.stdout.write(self.style.ERROR(
                "   BUG: the technician verified their own results"))
        except SegregationOfDutiesViolation:
            self.stdout.write(
                "   self-verification correctly refused")

        verify_order(order, actor=doctor)
        self.stdout.write(self.style.SUCCESS("   verified by the doctor"))

        for alert in alerts:
            notify_critical(alert, person="Dr Prakash Rana, on call",
                            via="telephone", actor=technician)
            acknowledge_critical(
                alert,
                action_taken="Patient reviewed. ECG done, calcium gluconate "
                             "and insulin-dextrose given. Nephrology referral "
                             "made.",
                actor=doctor,
            )
            alert.refresh_from_db()
            self.stdout.write(
                f"   alert {alert.status} after {alert.minutes_outstanding} min; "
                f"told {alert.notified_person}")

    # -- 3. a rejected specimen -------------------------------------------

    def _rejection(self, organization, facility, doctor, technician):
        patient = _live("Kamala")
        cbc = TestDefinition.objects.get(code="CBC")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n3. Rejected specimen - {patient.full_name}"))

        order = place_order(
            organization, patient, facility, cbc, actor=doctor,
            clinical_indication="Routine antenatal screen",
        )
        collect_specimen(order, actor=technician)
        reject_specimen(
            order,
            reason="Sample clotted; EDTA tube underfilled. Recollection "
                   "requested.",
            actor=technician,
        )
        order.refresh_from_db()
        self.stdout.write(self.style.WARNING(
            f"   {order.reference} {order.status}: {order.rejection_reason[:50]}"))
        self.stdout.write("   the clinician is still waiting — the order stays "
                          "visible rather than vanishing")

    # -- 4. radiology, narrative report ------------------------------------

    def _radiology(self, organization, facility, doctor, technician):
        patient = _live("Sita")
        cxr = TestDefinition.objects.get(code="CXR")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n4. Chest X-ray - {patient.full_name}"))

        order = place_order(
            organization, patient, facility, cxr, actor=doctor,
            clinical_indication="Cough and fever; query consolidation",
        )
        self.stdout.write(f"   {order.reference} placed (no specimen — imaging)")

        enter_results(order, [{
            "value": "PA chest radiograph. Patchy consolidation in the right "
                     "lower zone. Cardiomediastinal contours normal. No "
                     "pleural effusion or pneumothorax.\n\nCONCLUSION: "
                     "Right lower lobe pneumonia.",
            "method": "Digital radiography",
        }], actor=technician)
        verify_order(order, actor=doctor)
        order.refresh_from_db()
        report = order.results.first()
        self.stdout.write(self.style.SUCCESS(
            f"   reported and released: "
            f"{report.display_value.splitlines()[-1][:60]}"))

    # -- 5. performance ----------------------------------------------------

    def _report(self, facility):
        stats = turnaround_report(facility)
        pending = worklist(facility)
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Department performance"))
        self.stdout.write(
            f"   released {stats['released']}, "
            f"average total {stats['average_total_minutes']} min, "
            f"laboratory portion {stats['average_lab_minutes']} min")
        self.stdout.write(
            f"   breached {stats['breached']} ({stats['breach_rate_percent']}%), "
            f"rejected {stats['rejected']}, "
            f"open critical alerts {stats['critical_alerts_open']}")
        self.stdout.write(f"   worklist: {len(pending)} outstanding")


def _live(first_name: str):
    """The active record for a demo patient, never a merged tombstone."""
    return (
        Patient.objects.exclude(status=PatientStatus.MERGED)
        .filter(first_name=first_name)
        .order_by("registered_on")
        .first()
    )
