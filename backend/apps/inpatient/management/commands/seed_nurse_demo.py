"""Demonstrate and verify the Nurse Workspace, NEWS2 scoring, eMAR, and SBAR handovers.

Executes a full clinical bedside nursing scenario:
1. Active inpatient admissions on general and surgical wards.
2. Duty nurse assignments for morning and evening shifts.
3. Bedside rounds with automated NEWS2 early warning scores:
   - Stable patient (NEWS2 = 0, Low risk)
   - Moderate febrile patient (NEWS2 = 5, Medium risk)
   - Acutely deteriorating septic patient (NEWS2 = 15, High risk with doctor escalation)
4. Electronic Medication Administration Record (eMAR):
   - Routine IV antibiotic administration
   - Antihypertensive held due to low BP with clinical reason
   - PRN analgesic administered for fever
5. Structured SBAR shift handover note with incoming nurse acknowledgement.
6. Bedside shift tasks created and completed.
7. Aggregated workspace summary verified.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.encounters.models import Encounter, EncounterStatus, EncounterType
from apps.identity.models import User
from apps.inpatient.models import (
    AdministrationStatus,
    Admission,
    AdmissionSource,
    AdmissionStatus,
    Bed,
    BedAssignment,
    BedStatus,
    CodeStatusChoice,
    MedicationAdministration,
    NurseAssignment,
    NurseRole,
    NursingHandover,
    NursingRound,
    NursingTask,
    ShiftChoice,
    TaskCategory,
    TaskStatus,
    Ward,
    WardType,
)
from apps.inpatient.nursing_services import (
    acknowledge_handover,
    administer_medication,
    assign_nurse,
    calculate_news2,
    complete_nursing_task,
    create_nursing_task,
    create_sbar_handover,
    get_nurse_workspace_summary,
    get_patient_emar,
    record_bedside_round,
)
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.prescriptions.models import DoseRoute, Frequency, Prescription, PrescriptionLine, PrescriptionLineStatus
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Demonstrates and verifies Nurse Workspace, NEWS2, eMAR, and SBAR handover."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if not organization:
            organization = Organization.objects.first()
        if not organization:
            raise CommandError("No organization found. Run seed_demo first.")

        self.stdout.write(self.style.MIGRATE_HEADING(f"=== Nirova Nurse & Bedside Clinical Workspace Verification [{organization.display_name}] ==="))

        with tenant_context(context_for_organization(organization)):
            self._run_nursing_verification(organization)

    def _run_nursing_verification(self, organization):
        # 1. Facility
        facility = (
            Facility.objects.filter(status="active").first()
            or Facility.objects.first()
        )
        if not facility:
            raise CommandError("No facility found. Run seed_demo first.")
        self.stdout.write(f"1. Facility: {facility.name} [{facility.code}]")

        # 2. Staff: Duty Nurses
        nurse_maya = (
            User.objects.filter(memberships__organization=organization).first()
            or User.objects.first()
        )
        nurse_pradeep = (
            User.objects.exclude(uuid=nurse_maya.uuid).first()
            or nurse_maya
        )

        self.stdout.write(f"2. Duty Nurses: {nurse_maya.full_name} & {nurse_pradeep.full_name}")

        # 3. Ward & Beds
        ward, _ = Ward.objects.get_or_create(
            facility=facility,
            code="MED-WARD-3",
            defaults={
                "name": "Medical Ward 3",
                "ward_type": WardType.GENERAL,
                "floor": "3rd Floor",
                "building": "Main Block",
                "nurse_to_patient_ratio": Decimal("4.00"),
            },
        )
        bed_01, _ = Bed.objects.get_or_create(
            ward=ward, code="301-A", defaults={"bay": "Bay 1", "status": BedStatus.AVAILABLE}
        )
        bed_02, _ = Bed.objects.get_or_create(
            ward=ward, code="301-B", defaults={"bay": "Bay 1", "status": BedStatus.AVAILABLE}
        )
        bed_03, _ = Bed.objects.get_or_create(
            ward=ward, code="302-A", defaults={"bay": "Bay 2", "status": BedStatus.AVAILABLE}
        )
        self.stdout.write(f"3. Ward: {ward.name} with beds {bed_01.code}, {bed_02.code}, {bed_03.code}")

        # 4. Patients & Inpatient Admissions
        patients = list(Patient.objects.filter(merged_into__isnull=True)[:3])
        if len(patients) < 3:
            p1, _ = Patient.objects.get_or_create(
                mrn="BTH-IPD-001",
                defaults={
                    "first_name": "Hari",
                    "last_name": "Bahadur",
                    "gender": "male",
                    "date_of_birth": date(1968, 5, 14),
                    "primary_phone": "9841000001",
                },
            )
            p2, _ = Patient.objects.get_or_create(
                mrn="BTH-IPD-002",
                defaults={
                    "first_name": "Sita",
                    "last_name": "Devi",
                    "gender": "female",
                    "date_of_birth": date(1982, 9, 21),
                    "primary_phone": "9841000002",
                },
            )
            p3, _ = Patient.objects.get_or_create(
                mrn="BTH-IPD-003",
                defaults={
                    "first_name": "Ram",
                    "last_name": "Kaji",
                    "gender": "male",
                    "date_of_birth": date(1955, 11, 30),
                    "primary_phone": "9841000003",
                },
            )
            patients = [p1, p2, p3]

        today = timezone.localdate()

        def ensure_admission(patient, bed, ref, diag):
            enc, _ = Encounter.objects.get_or_create(
                reference=f"ENC-{ref}",
                defaults={
                    "patient": patient,
                    "facility": facility,
                    "encounter_type": EncounterType.INPATIENT,
                    "status": EncounterStatus.IN_PROGRESS,
                    "started_at": timezone.now() - timedelta(days=2),
                },
            )
            adm = Admission.objects.filter(reference=ref).first()
            if not adm:
                adm = Admission.objects.create(
                    reference=ref,
                    patient=patient,
                    facility=facility,
                    encounter=enc,
                    status=AdmissionStatus.ADMITTED,
                    source=AdmissionSource.OPD,
                    admitted_at=timezone.now() - timedelta(days=2),
                    consultant_name="Dr. Anil Sharma",
                    admitting_diagnosis=diag,
                )
            # Put the admission back into the state this scenario needs. A row
            # existing is not the same fact as a patient still being on the
            # ward: the inpatient seed discharges one of these three, so on a
            # full-suite run the workspace summary found two patients where
            # the scenario asserts three. `get_or_create` guarantees the row,
            # not the state, and the state is what is being demonstrated.
            if adm.status != AdmissionStatus.ADMITTED:
                adm.status = AdmissionStatus.ADMITTED
                adm.discharged_at = None
                adm.save(update_fields=["status", "discharged_at"])

            if not adm.bed_assignments.filter(vacated_at__isnull=True).exists():
                BedAssignment.objects.create(
                    admission=adm,
                    bed=bed,
                    ward=ward,
                    occupied_at=timezone.now() - timedelta(days=2),
                )
                bed.status = BedStatus.OCCUPIED
                bed.save(update_fields=["status"])
            return adm

        adm_stable = ensure_admission(patients[0], bed_01, "ADM-2026-001", "Community Acquired Pneumonia - resolving")
        adm_febrile = ensure_admission(patients[1], bed_02, "ADM-2026-002", "Acute Pyelonephritis")
        adm_septic = ensure_admission(patients[2], bed_03, "ADM-2026-003", "Biliary Sepsis / Cholecystitis")
        self.stdout.write(f"4. Admitted 3 Inpatients across beds {bed_01.code}, {bed_02.code}, {bed_03.code}")

        # 5. Nurse Assignment
        assign_nurse(
            ward=ward,
            admission=adm_stable,
            bed=bed_01,
            nurse_id=nurse_maya.uuid,
            nurse_name=nurse_maya.full_name,
            assigned_date=today,
            shift=ShiftChoice.MORNING,
            role=NurseRole.PRIMARY,
            notes="Primary care for bed 301-A",
            actor=nurse_maya,
        )
        assign_nurse(
            ward=ward,
            admission=adm_febrile,
            bed=bed_02,
            nurse_id=nurse_maya.uuid,
            nurse_name=nurse_maya.full_name,
            assigned_date=today,
            shift=ShiftChoice.MORNING,
            role=NurseRole.PRIMARY,
            notes="Primary care for bed 301-B",
            actor=nurse_maya,
        )
        assign_nurse(
            ward=ward,
            admission=adm_septic,
            bed=bed_03,
            nurse_id=nurse_maya.uuid,
            nurse_name=nurse_maya.full_name,
            assigned_date=today,
            shift=ShiftChoice.MORNING,
            role=NurseRole.PRIMARY,
            notes="High-acuity monitoring bed 302-A",
            actor=nurse_maya,
        )
        self.stdout.write(self.style.SUCCESS(f"5. Nurse Assignment: {nurse_maya.full_name} assigned 3 beds for Morning shift."))

        # 6. Bedside Rounds & NEWS2 Scoring Verification
        # 6a. Stable patient
        r1 = record_bedside_round(
            admission=adm_stable,
            actor=nurse_maya,
            temperature_c=Decimal("36.7"),
            pulse_bpm=72,
            respiratory_rate=16,
            systolic_bp=120,
            diastolic_bp=80,
            spo2_percent=98,
            on_room_air=True,
            pain_score=1,
            gcs_total=15,
            intake_ml=800,
            output_ml=650,
            observations="Patient resting comfortably on room air. Lungs clear.",
        )
        assert r1["news2"]["score"] == 0, f"Expected NEWS2 0, got {r1['news2']['score']}"
        assert r1["news2"]["risk_level"] == "low"
        self.stdout.write(f"   Round 1 (Stable): NEWS2 = {r1['news2']['score']} [{r1['news2']['risk_level'].upper()}] - {r1['news2']['recommendation']}")

        # 6b. Moderate febrile patient
        r2 = record_bedside_round(
            admission=adm_febrile,
            actor=nurse_maya,
            temperature_c=Decimal("38.5"),
            pulse_bpm=106,
            respiratory_rate=22,
            systolic_bp=132,
            diastolic_bp=84,
            spo2_percent=95,
            on_room_air=True,
            pain_score=4,
            gcs_total=15,
            intake_ml=600,
            output_ml=400,
            observations="Flushed, complaining of flank pain and chills.",
        )
        assert r2["news2"]["score"] >= 5, f"Expected NEWS2 >= 5, got {r2['news2']['score']}"
        assert r2["news2"]["risk_level"] == "medium"
        self.stdout.write(f"   Round 2 (Moderate): NEWS2 = {r2['news2']['score']} [{r2['news2']['risk_level'].upper()}] - Triggers: {[t['parameter'] for t in r2['news2']['triggers']]}")

        # 6c. Acutely deteriorating patient
        r3 = record_bedside_round(
            admission=adm_septic,
            actor=nurse_maya,
            temperature_c=Decimal("39.4"),
            pulse_bpm=138,
            respiratory_rate=28,
            systolic_bp=84,
            diastolic_bp=48,
            spo2_percent=90,
            on_room_air=False,
            oxygen_flow_lpm=Decimal("4.0"),
            pain_score=7,
            gcs_total=13,
            intake_ml=1200,
            output_ml=250,
            observations="Rigors, drowsy, hypotensive. Oliguria noted.",
            escalated=True,
            escalation_reason="Severe sepsis alert: Low BP 84/48, tachycardia 138, tachypnea 28",
        )
        assert r3["news2"]["score"] >= 10, f"Expected NEWS2 >= 10, got {r3['news2']['score']}"
        assert r3["news2"]["risk_level"] == "high"
        assert r3["escalated"] is True
        self.stdout.write(self.style.WARNING(f"   Round 3 (Deteriorating): NEWS2 = {r3['news2']['score']} [{r3['news2']['risk_level'].upper()}] - ESCALATED TO DOCTOR: {r3['escalation_reason']}"))

        # 7. eMAR (Electronic Medication Administration Record)
        # An encounter is allowed several prescriptions -- that is the point
        # of superseding rather than overwriting -- so `get_or_create` keyed
        # on the encounter alone raises MultipleObjectsReturned as soon as
        # this runs after the clinical seeds. Reuse whichever already exists
        # and only build one when the encounter has none.
        #
        # Reuse rather than always creating, because this seed writes the row
        # directly instead of going through `create_prescription`, so
        # `reference` comes out blank; a second blank reference collides with
        # `prescription_reference_key`. The bypass is worth noting on its own
        # -- a seed that does not use the service layer is not exercising the
        # code the application runs.
        rx = Prescription.objects.filter(encounter=adm_septic.encounter).first()
        if rx is None:
            rx = Prescription.objects.create(
                encounter=adm_septic.encounter,
                patient=adm_septic.patient,
                facility=facility,
            )
        line_ceftriaxone, _ = PrescriptionLine.objects.get_or_create(
            prescription=rx,
            generic_name="Ceftriaxone",
            defaults={
                "brand_name": "Rocephin",
                "strength": "1 g",
                "dose": "1 g",
                "route": DoseRoute.INTRAVENOUS,
                "frequency": Frequency.BD,
                "instructions": "Slow IV infusion in 100ml NS over 30 mins",
                "status": PrescriptionLineStatus.ACTIVE,
            },
        )
        line_amlodipine, _ = PrescriptionLine.objects.get_or_create(
            prescription=rx,
            generic_name="Amlodipine",
            defaults={
                "strength": "5 mg",
                "dose": "5 mg",
                "route": DoseRoute.ORAL,
                "frequency": Frequency.OD,
                "instructions": "Oral once daily morning",
                "status": PrescriptionLineStatus.ACTIVE,
            },
        )
        line_pcm, _ = PrescriptionLine.objects.get_or_create(
            prescription=rx,
            generic_name="Paracetamol",
            defaults={
                "strength": "1 g",
                "dose": "1 g",
                "route": DoseRoute.INTRAVENOUS,
                "frequency": Frequency.QDS,
                "is_prn": True,
                "prn_indication": "Temp > 38.5°C or severe pain",
                "max_doses_per_day": 4,
                "instructions": "IV infusion over 15 mins",
                "status": PrescriptionLineStatus.ACTIVE,
            },
        )

        # 7a. Administer Ceftriaxone (Given)
        adm_med_1 = administer_medication(
            prescription_line=line_ceftriaxone,
            admission=adm_septic,
            actor=nurse_maya,
            status=AdministrationStatus.GIVEN,
            dose_given="1 g",
            route="IV",
            injection_site="Left forearm peripheral IV",
            notes="Infused over 30 minutes. No adverse reaction.",
        )
        assert adm_med_1.status == AdministrationStatus.GIVEN

        # 7b. Hold Amlodipine (Held for hypotension)
        adm_med_2 = administer_medication(
            prescription_line=line_amlodipine,
            admission=adm_septic,
            actor=nurse_maya,
            status=AdministrationStatus.HELD,
            dose_given="5 mg",
            route="PO",
            reason="Withheld: Systolic BP 84 mmHg < 90 mmHg safety threshold.",
        )
        assert adm_med_2.status == AdministrationStatus.HELD

        # 7c. Administer PRN Paracetamol (Given for high fever with co-signature)
        adm_med_3 = administer_medication(
            prescription_line=line_pcm,
            admission=adm_septic,
            actor=nurse_maya,
            status=AdministrationStatus.GIVEN,
            dose_given="1 g",
            route="IV",
            injection_site="Left forearm peripheral IV",
            witness_id=nurse_pradeep.uuid,
            witness_name=nurse_pradeep.full_name,
            notes="Given for fever spike of 39.4°C. Co-verified with Nurse Pradeep.",
        )
        assert adm_med_3.witness_by_name == nurse_pradeep.full_name

        emar_summary = get_patient_emar(adm_septic)
        self.stdout.write(self.style.SUCCESS(f"7. eMAR: {len(emar_summary['lines'])} active meds, {len(emar_summary['administrations'])} doses logged (Given, Held, PRN with witness)."))

        # 8. SBAR Shift Handover Note
        handover = create_sbar_handover(
            admission=adm_septic,
            outgoing_nurse=nurse_maya,
            shift=ShiftChoice.MORNING,
            shift_date=today,
            code_status=CodeStatusChoice.FULL_CODE,
            situation="Acutely deteriorating with biliary sepsis, high fever, tachypnea and hypotension.",
            background="Admitted 2 days ago for acute cholecystitis. No known drug allergies. Code status: FULL CODE.",
            assessment="NEWS2 score 15 (RED alert). Temp 39.4°C, HR 138, BP 84/48 on 4L O2. Net 24h balance +950 ml. Ceftriaxone given, Amlodipine held.",
            recommendation="Urgent ICU bed request placed with Dr. Anil. Maintain 4L O2. Repeat blood cultures if fever persists. Push IV fluids.",
        )
        assert not handover.is_acknowledged

        # Incoming Nurse Pradeep acknowledges receipt
        ack = acknowledge_handover(handover, incoming_nurse=nurse_pradeep)
        assert ack.is_acknowledged is True
        assert ack.incoming_nurse_name == nurse_pradeep.full_name
        self.stdout.write(self.style.SUCCESS(f"8. SBAR Handover: Created by {nurse_maya.full_name} and acknowledged by incoming nurse {ack.incoming_nurse_name}."))

        # 9. Nursing Tasks
        t1 = create_nursing_task(
            admission=adm_septic,
            title="Check blood pressure and pulse hourly",
            category=TaskCategory.VITALS,
            shift=ShiftChoice.MORNING,
            due_at=timezone.now() + timedelta(hours=1),
            notes="Severe sepsis protocol",
        )
        t2 = create_nursing_task(
            admission=adm_septic,
            title="Check IV cannula patency & site for phlebitis",
            category=TaskCategory.WOUND_CARE,
            shift=ShiftChoice.MORNING,
            due_at=timezone.now() + timedelta(hours=2),
        )
        complete_nursing_task(t2, actor=nurse_maya, notes="Left forearm cannula intact, flushed cleanly, no swelling.")
        assert t2.status == TaskStatus.COMPLETED
        self.stdout.write(self.style.SUCCESS(f"9. Nursing Tasks: Created '{t1.title}' (pending) and '{t2.title}' (completed)."))

        # 10. Nurse Workspace Summary Aggregation
        summary = get_nurse_workspace_summary(
            actor=nurse_maya,
            facility=facility,
            ward_id=str(ward.uuid),
            target_date=today,
            target_shift=ShiftChoice.MORNING,
            scope="mine",
        )
        assert summary["total_patients"] == 3
        assert summary["high_risk_count"] >= 1
        assert summary["total_tasks_pending"] >= 1
        self.stdout.write(self.style.SUCCESS(
            f"10. Nurse Workspace Summary: {summary['total_patients']} assigned patients, "
            f"{summary['high_risk_count']} HIGH risk (NEWS2 >= 7), "
            f"{summary['medium_risk_count']} MEDIUM risk, "
            f"{summary['total_tasks_pending']} pending tasks."
        ))

        self.stdout.write(self.style.MIGRATE_LABEL("\n=== All Nursing & Clinical Bedside checks passed cleanly! ==="))
