"""Run three consultations end to end through the real service layer.

Each one is chosen to exercise a different branch:

1. A routine consultation that produces vitals, a SOAP note, a diagnosis and
   a clean prescription.
2. A consultation where the prescriber writes a drug the patient is allergic
   to — the warning fires, the override is captured, and the record keeps
   both.
3. A consultation that raises a drug-interaction warning, and a diagnosis
   promoted into the patient's ongoing condition list.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.encounters.models import EncounterType
from apps.encounters.services import (
    add_diagnosis,
    close_encounter,
    record_vitals,
    start_encounter,
    write_note,
)
from apps.encounters.services import promote_to_condition
from apps.identity.models import User
from apps.organization.models import Facility
from apps.patients.models import Patient, PatientStatus
from apps.prescriptions.services import (
    OverrideRequired,
    active_medications,
    create_prescription,
    preview_prescription,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


def _live_patient(first_name: str):
    """The active record for a demo patient, never a merged tombstone.

    Ordering is by registration date descending elsewhere, which meant the
    seed picked up a record that had been merged away -- and merged records
    have no allergies, because those moved to the survivor.
    """
    return (
        Patient.objects.exclude(status=PatientStatus.MERGED)
        .filter(first_name=first_name)
        .order_by("registered_on")
        .first()
    )


class Command(BaseCommand):
    help = "Run three consultations end to end for a tenant."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError(f"No organization '{options['slug']}'.")

        actor = User.objects.filter(
            email=f"owner@{options['slug']}.test"
        ).first()

        with tenant_context(context_for_organization(organization)):
            facility = Facility.objects.filter(facility_type="clinic").first()
            if facility is None:
                raise CommandError("No clinic facility. Run `seed_demo` first.")

            self._routine(organization, facility, actor)
            self._allergy_override(organization, facility, actor)
            self._interaction(organization, facility, actor)

    # -- 1. routine ------------------------------------------------------

    def _routine(self, organization, facility, actor):
        patient = _live_patient("Sita")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n1. Routine consultation - {patient.full_name} ({patient.mrn})"))

        encounter = start_encounter(
            organization, patient, facility, actor=actor,
            encounter_type=EncounterType.OUTPATIENT,
            chief_complaint="Fever and cough for three days",
        )
        self.stdout.write(f"   {encounter.reference} opened")

        vitals = record_vitals(encounter, {
            "temperature_c": "38.6", "pulse_bpm": 104, "respiratory_rate": 20,
            "systolic_bp": 118, "diastolic_bp": 76, "spo2_percent": 97,
            "weight_kg": "58.40", "height_cm": "156.0",
        }, actor=actor)
        flags = vitals.abnormal_flags()
        self.stdout.write(
            f"   vitals: {vitals.temperature_c}C, {vitals.pulse_bpm}bpm, "
            f"BP {vitals.blood_pressure}, BMI {vitals.bmi}"
        )
        for flag in flags:
            self.stdout.write(self.style.WARNING(
                f"     flagged {flag['field']}: {flag['note']}"))

        write_note(encounter, {
            "subjective": "Three days of fever, productive cough, mild "
                          "pleuritic chest pain. No breathlessness at rest.",
            "objective": "Alert, febrile. Chest: coarse crackles right base. "
                         "No respiratory distress.",
            "assessment": "Community-acquired pneumonia, right lower lobe. "
                          "CURB-65 low risk; suitable for outpatient care.",
            "plan": "Oral amoxicillin. Paracetamol as needed. Review in 48 "
                    "hours or sooner if breathless.",
        }, actor=actor, sign=True)
        self.stdout.write("   SOAP note written and signed")

        add_diagnosis(encounter, {
            "name": "Community-acquired pneumonia",
            "icd10_code": "J18.9", "certainty": "working", "is_primary": True,
        }, actor=actor)
        self.stdout.write("   diagnosis: J18.9 (primary)")

        prescription = create_prescription(
            organization=organization, patient=patient, facility=facility,
            encounter=encounter, actor=actor,
            lines=[
                {"generic_name": "Amoxicillin", "strength": "500 mg",
                 "dosage_form": "Capsule", "dose": "1 capsule",
                 "route": "PO", "frequency": "TDS", "duration_days": 5},
                {"generic_name": "Paracetamol", "strength": "500 mg",
                 "dosage_form": "Tablet", "dose": "1 tablet", "route": "PO",
                 "frequency": "PRN", "is_prn": True,
                 "prn_indication": "fever or pain", "max_doses_per_day": 4,
                 "duration_days": 5},
            ],
            patient_instructions="Finish the full course of antibiotic even "
                                 "if you feel better.",
        )
        self.stdout.write(self.style.SUCCESS(
            f"   {prescription.reference} signed, {prescription.lines.count()} "
            f"medicines, {prescription.safety_checks['count']} warnings"))
        for line in prescription.lines.all():
            self.stdout.write(f"     {line.display_name} - {line.sig}"
                              f"  (qty {line.quantity})")

        close_encounter(encounter, actor=actor, disposition="discharged",
                        follow_up_instructions="Return in 48 hours for review.")
        self.stdout.write("   encounter closed")

    # -- 2. the allergy the system knows about ---------------------------

    def _allergy_override(self, organization, facility, actor):
        """Ram Bahadur Shrestha has a recorded severe penicillin allergy."""
        patient = _live_patient("Ram")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n2. Allergy warning - {patient.full_name} ({patient.mrn})"))

        encounter = start_encounter(
            organization, patient, facility, actor=actor,
            chief_complaint="Sore throat, difficulty swallowing",
        )

        # Amoxicillin is a penicillin. The patient's recorded allergy is to
        # "Penicillin", so this must be caught by family matching, not by an
        # exact name match.
        lines = [{"generic_name": "Amoxicillin", "strength": "500 mg",
                  "dose": "1 capsule", "route": "PO", "frequency": "TDS",
                  "duration_days": 7}]

        preview = preview_prescription(patient, lines)
        self.stdout.write(f"   preview: {preview['count']} warning(s), "
                          f"override required: {preview['requires_override']}")
        for warning in preview["warnings"]:
            self.stdout.write(self.style.ERROR(
                f"     [{warning['severity']}] {warning['message']}"))

        # Writing it without a reason must be refused.
        try:
            create_prescription(
                organization=organization, patient=patient, facility=facility,
                encounter=encounter, actor=actor, lines=lines,
            )
            self.stdout.write(self.style.ERROR(
                "   BUG: prescription was accepted with no override reason"))
        except OverrideRequired:
            self.stdout.write(
                "   correctly refused without an override reason")

        # With a reason, it proceeds and the reason is kept forever.
        prescription = create_prescription(
            organization=organization, patient=patient, facility=facility,
            encounter=encounter, actor=actor, lines=lines,
            override_reason="Recorded reaction was a mild childhood rash in "
                            "1968; formal allergy testing in 2024 was "
                            "negative. Discussed with the patient.",
        )
        self.stdout.write(self.style.SUCCESS(
            f"   {prescription.reference} written with override recorded"))
        self.stdout.write(f"     reason: {prescription.override_reason[:60]}...")

        write_note(encounter, {
            "subjective": "Sore throat, odynophagia, no stridor.",
            "objective": "Tonsils enlarged with exudate. Cervical nodes tender.",
            "assessment": "Bacterial tonsillitis.",
            "plan": "Amoxicillin after documented allergy review.",
        }, actor=actor, sign=True)
        close_encounter(encounter, actor=actor)
        self.stdout.write("   encounter closed")

    # -- 3. interaction, and a diagnosis that becomes a condition --------

    def _interaction(self, organization, facility, actor):
        patient = _live_patient("Bishnu")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n3. Interaction warning - {patient.full_name} ({patient.mrn})"))

        encounter = start_encounter(
            organization, patient, facility, actor=actor,
            chief_complaint="Follow-up, on warfarin for atrial fibrillation",
        )
        record_vitals(encounter, {
            "systolic_bp": 152, "diastolic_bp": 94, "pulse_bpm": 88,
        }, actor=actor)

        lines = [
            {"generic_name": "Warfarin", "strength": "5 mg", "dose": "1 tablet",
             "route": "PO", "frequency": "OD", "duration_days": 30},
            {"generic_name": "Ibuprofen", "strength": "400 mg",
             "dose": "1 tablet", "route": "PO", "frequency": "TDS",
             "duration_days": 5},
        ]
        preview = preview_prescription(patient, lines)
        for warning in preview["warnings"]:
            self.stdout.write(self.style.ERROR(
                f"     [{warning['severity']}] {warning['message']}"))

        # The clinically correct outcome: drop the NSAID rather than override.
        safe_lines = [
            lines[0],
            {"generic_name": "Paracetamol", "strength": "500 mg",
             "dose": "1 tablet", "route": "PO", "frequency": "QDS",
             "duration_days": 5},
        ]
        prescription = create_prescription(
            organization=organization, patient=patient, facility=facility,
            encounter=encounter, actor=actor, lines=safe_lines,
        )
        self.stdout.write(self.style.SUCCESS(
            f"   {prescription.reference} written with paracetamol instead "
            f"({prescription.safety_checks['count']} warnings)"))

        diagnosis = add_diagnosis(encounter, {
            "name": "Atrial fibrillation", "icd10_code": "I48.9",
            "certainty": "confirmed", "is_primary": True, "is_chronic": True,
        }, actor=actor)
        condition = promote_to_condition(diagnosis, actor=actor)
        self.stdout.write(
            f"   diagnosis I48.9 promoted to ongoing condition "
            f"({condition.status})")

        write_note(encounter, {
            "subjective": "Well. No palpitations or bleeding.",
            "objective": "Irregularly irregular pulse. BP 152/94.",
            "assessment": "AF, rate controlled. Hypertension, not at target.",
            "plan": "Continue warfarin. Paracetamol rather than an NSAID "
                    "given bleeding risk. Recheck BP in two weeks.",
        }, actor=actor, sign=True)
        close_encounter(encounter, actor=actor,
                        follow_up_instructions="BP review in two weeks.")

        medications = active_medications(patient)
        self.stdout.write(f"   active medications now: {len(medications)}")
        for medication in medications:
            self.stdout.write(f"     {medication['display_name']} - "
                              f"{medication['sig']}")
