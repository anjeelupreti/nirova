"""A shift in the emergency department.

Through the real service layer:

1. An unconscious arrival registered without a name, and everything that
   follows attaching to a real record.
2. Triage, and a re-triage that records a deterioration rather than hiding it.
3. Triage targets, and a breach that stays visible after the patient is seen.
4. A STEMI pathway with the clock running from arrival, not from recognition.
5. A resuscitation record written as it happens.
6. Identification, merging the provisional record into the real one — and
   everything written during the resus following it across.
7. Dispositions including left-without-being-seen, which only exists because
   somebody records it.
8. The board, sickest first, and the department's own numbers.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.emergency.models import (
    AlertPathway,
    Arrival,
    ArrivalMode,
    CriticalAlert,
    Disposition,
    TriageAssessment,
)
from apps.emergency.services import (
    EmergencyError,
    activate_alert,
    arrive,
    board,
    department_summary,
    dispose,
    identify,
    log_resus,
    mark_seen,
    pathway_performance,
    record_intervention,
    resuscitation_record,
    triage,
)
from apps.encounters.models import TriageCategory
from apps.identity.models import User
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Run a shift in the emergency department."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        nurse = User.objects.filter(email=f"manager@{slug}.test").first()
        doctor = User.objects.filter(email=f"doctor@{slug}.test").first()
        consultant = User.objects.filter(email=f"owner@{slug}.test").first()
        if not (nurse and consultant):
            raise CommandError("Run `seed_demo` first.")
        doctor = doctor or consultant

        with tenant_context(context_for_organization(organization)):
            facility = (
                Facility.objects.filter(facility_type="hospital").first()
                or Facility.objects.filter(facility_type="clinic").first()
            )
            if facility is None:
                raise CommandError("No facility. Run `seed_demo` first.")

            self._close_stale(facility, nurse)
            unknown = self._unidentified(organization, facility, nurse)
            self._triage_and_deteriorate(unknown, nurse, doctor)
            self._pathway(unknown, doctor)
            self._resus(unknown, doctor, nurse)
            self._identify(organization, facility, unknown, consultant)
            waiter = self._lwbs(organization, facility, nurse)
            self._board(facility)
            self._summary(facility)

    # -- setup -------------------------------------------------------------

    def _close_stale(self, facility, actor):
        stale = Arrival.objects.filter(
            facility=facility, disposition=Disposition.PENDING
        )
        for arrival in stale:
            dispose(
                arrival, Disposition.DISCHARGED, actor=actor,
                notes="Closed by a seed re-run.",
            )
        if stale:
            self.stdout.write(
                f"  closed {len(stale)} attendance(s) left open by an "
                "earlier run"
            )

    # -- arriving ----------------------------------------------------------

    def _unidentified(self, organization, facility, nurse):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n1. Somebody nobody can name")
        )
        arrival = arrive(
            organization=organization,
            facility=facility,
            presenting_complaint=(
                "Unresponsive, found at the roadside. Query head injury."
            ),
            actor=nurse,
            arrival_mode=ArrivalMode.AMBULANCE,
            unidentified_description=(
                "Male, approximately 40, blue shirt, tattoo on left forearm."
            ),
            apparent_gender="male",
            is_mlc=True,
            ambulance_reference="AMB-2291",
            brought_by="Nepal Ambulance Service",
        )
        self.stdout.write(
            f"   {arrival.reference}: registered as {arrival.patient.mrn} "
            f"({arrival.patient.full_name}) without a name"
        )
        self.stdout.write(
            f"   staff will call them: {arrival.provisional_description}"
        )
        self.stdout.write(
            "   a real patient record, not a placeholder — it takes charges, "
            "prescriptions and results, and merges cleanly later"
        )
        if arrival.is_mlc:
            self.stdout.write(self.style.WARNING(
                "   medico-legal: the police must be informed"
            ))
        return arrival

    # -- triage ------------------------------------------------------------

    def _triage_and_deteriorate(self, arrival, nurse, doctor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Triage"))

        # Backdate the arrival so the clocks have something to measure.
        arrival.arrived_at = timezone.now() - timedelta(minutes=48)
        arrival.save(update_fields=["arrived_at"])

        first = triage(
            arrival, TriageCategory.URGENT, actor=nurse,
            reason="Responds to voice, GCS 13, no external bleeding.",
            pulse=96, systolic=124, diastolic=78, respiratory_rate=18,
            spo2=96, gcs=13, temperature_c=Decimal("36.8"),
        )
        arrival.refresh_from_db()
        self.stdout.write(
            f"   category {first.category} — target "
            f"{arrival.target_minutes} minutes, GCS {first.gcs}"
        )

        deterioration = triage(
            arrival, TriageCategory.RESUSCITATION, actor=nurse,
            reason="GCS fallen to 8, now snoring. Airway at risk.",
            pulse=52, systolic=178, diastolic=96, respiratory_rate=9,
            spo2=91, gcs=8,
        )
        arrival.refresh_from_db()
        self.stdout.write(
            f"   re-triaged to {deterioration.category}: "
            f"{deterioration.reason}"
        )
        if deterioration.is_deterioration:
            self.stdout.write(
                f"   recorded as a deterioration "
                f"({deterioration.previous_category} → "
                f"{deterioration.category}) — an overwritten field would have "
                "destroyed the one fact a mortality review asks about"
            )
        else:
            self.stdout.write(self.style.ERROR(
                "   a fall from 3 to 1 was not recorded as a deterioration"
            ))

        history = arrival.assessments.count()
        if history < 2:
            self.stdout.write(self.style.ERROR(
                f"   only {history} assessment on the record — triage "
                "overwrote instead of appending"
            ))

        # The wait clock does not restart on a re-triage.
        self.stdout.write(
            f"   waiting {arrival.waiting_minutes} minutes against a "
            f"{arrival.target_minutes} minute target"
        )
        if not arrival.is_breaching:
            self.stdout.write(self.style.ERROR(
                "   48 minutes against a 0 minute target is not showing as a "
                "breach"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"   BREACHING by {abs(arrival.minutes_to_breach)} minutes"
            ))

        mark_seen(arrival, actor=doctor)
        arrival.refresh_from_db()
        self.stdout.write(
            f"   seen by {arrival.seen_by_name} after "
            f"{arrival.waiting_minutes} minutes"
        )
        if not arrival.is_breaching:
            self.stdout.write(self.style.ERROR(
                "   the breach disappeared once the patient was seen — a "
                "department would under-report its own performance"
            ))
        else:
            self.stdout.write(
                "   still recorded as a breach: a breach that happened is a "
                "breach"
            )

    # -- pathways ----------------------------------------------------------

    def _pathway(self, arrival, doctor):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n3. A time-critical pathway")
        )
        alert = activate_alert(
            arrival, AlertPathway.STROKE, actor=doctor,
            notes="Sudden collapse, unequal pupils. CT head requested.",
        )
        self.stdout.write(
            f"   {alert.get_pathway_display()} activated "
            f"{alert.recognition_minutes} minutes after arrival"
        )
        self.stdout.write(
            f"   target is {alert.target_minutes} minutes from *arrival*, not "
            "from activation — a stroke recognised 48 minutes late has "
            "already spent 48 minutes of its window"
        )

        record_intervention(
            alert, actor=doctor,
            intervention="CT head, then thrombolysis started.",
            at=arrival.arrived_at + timedelta(minutes=74),
        )
        alert.refresh_from_db()
        self.stdout.write(
            f"   door to needle: {alert.door_to_intervention_minutes} minutes "
            f"against a {alert.target_minutes} minute target — "
            f"{'met' if alert.met_target else 'MISSED'}"
        )
        if alert.met_target is not False:
            self.stdout.write(self.style.ERROR(
                "   74 minutes against a 60 minute target should be a miss"
            ))

    def _resus(self, arrival, doctor, nurse):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n4. The resuscitation record")
        )
        start = timezone.now() - timedelta(minutes=11)
        script = [
            ("arrest", "Witnessed arrest on the trolley.", {}, 0),
            ("cpr_start", "Chest compressions started.", {}, 0),
            ("rhythm", "", {"rhythm": "Ventricular fibrillation"}, 2),
            ("shock", "", {"joules": 200, "rhythm": "VF"}, 2),
            ("drug", "", {"drug": "Adrenaline", "dose": "1 mg",
                          "route": "IV"}, 3),
            ("airway", "Intubated, size 8 tube, grade 1 view.", {}, 4),
            ("rhythm", "", {"rhythm": "Ventricular fibrillation"}, 6),
            ("shock", "", {"joules": 200, "rhythm": "VF"}, 6),
            ("drug", "", {"drug": "Amiodarone", "dose": "300 mg",
                          "route": "IV"}, 7),
            ("rhythm", "", {"rhythm": "Sinus rhythm"}, 9),
            ("rosc", "Palpable carotid, blood pressure 96/60.", {}, 9),
            ("cpr_stop", "Compressions stopped.", {}, 9),
        ]
        for event_type, detail, fields, offset in script:
            log_resus(
                arrival, event_type, actor=doctor, detail=detail,
                at=start + timedelta(minutes=offset), **fields,
            )

        result = resuscitation_record(arrival)
        self.stdout.write(
            f"   {len(result['events'])} entries over "
            f"{result['duration_minutes']} minutes: {result['shocks']} shocks, "
            f"{result['drugs']} drugs, ROSC {result['rosc']}"
        )
        for row in result["events"][:6]:
            label = row["drug"] or row["rhythm"] or row["detail"]
            self.stdout.write(
                f"     +{row['elapsed_minutes']:>2}m  {row['event_type']:<12} "
                f"{label}"
                + (f" {row['dose']}" if row["dose"] else "")
                + (f" {row['joules']}J" if row["joules"] else "")
            )
        self.stdout.write(
            "     ... and the rest, each timestamped as it happened rather "
            "than written up afterwards from memory"
        )
        if result["duration_minutes"] != 9:
            self.stdout.write(self.style.ERROR(
                f"   the resus should span 9 minutes, not "
                f"{result['duration_minutes']}"
            ))

    # -- identification ----------------------------------------------------

    def _identify(self, organization, facility, arrival, actor):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n5. Somebody comes to the desk")
        )
        provisional = arrival.patient
        provisional_mrn = provisional.mrn
        events_before = arrival.resuscitation.count()
        alerts_before = arrival.alerts.count()

        existing = (
            Patient.objects.filter(merged_into__isnull=True)
            .exclude(pk=provisional.pk)
            .exclude(last_name="Unidentified")
            .first()
        )
        if existing is None:
            self.stdout.write("   no existing record to merge into")
            return

        self.stdout.write(
            f"   the brother recognises the tattoo: this is {existing.mrn}, "
            f"{existing.full_name}"
        )
        identify(arrival, actor=actor, existing_patient=existing)
        arrival.refresh_from_db()
        provisional.refresh_from_db()

        self.stdout.write(
            f"   {provisional_mrn} merged into {arrival.patient.mrn}; the "
            f"attendance now reads {arrival.patient.full_name}"
        )
        self.stdout.write(
            f"   they went {arrival.minutes_unidentified} minutes without a "
            "name — an hour unidentified is an hour nobody can ring a "
            "relative or check an allergy"
        )
        self.stdout.write(
            f"   the resus record ({arrival.resuscitation.count()} entries) "
            f"and the stroke call ({arrival.alerts.count()}) came across"
        )
        if (
            arrival.resuscitation.count() != events_before
            or arrival.alerts.count() != alerts_before
        ):
            self.stdout.write(self.style.ERROR(
                "   entries were lost in the merge"
            ))
        if not provisional.is_merged:
            self.stdout.write(self.style.ERROR(
                "   the provisional record was not marked merged"
            ))
        else:
            self.stdout.write(
                f"   {provisional_mrn} is kept as a tombstone pointing at "
                f"{provisional.resolve().mrn} — deleting it would orphan "
                "everything already written against it"
            )

        dispose(
            arrival, Disposition.ADMITTED, actor=actor,
            notes="To ICU for post-arrest care.",
            admission_reference="IPD-PENDING",
        )
        arrival.refresh_from_db()
        self.stdout.write(
            f"   admitted after {arrival.total_minutes} minutes in the "
            "department"
        )

    # -- the one who gave up -----------------------------------------------

    def _lwbs(self, organization, facility, nurse):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n6. The one who gave up waiting")
        )
        patient = (
            Patient.objects.filter(merged_into__isnull=True)
            .exclude(last_name="Unidentified")
            .exclude(arrivals__disposition=Disposition.PENDING)
            .last()
        )
        if patient is None:
            self.stdout.write("   nobody available")
            return None

        arrival = arrive(
            organization=organization,
            facility=facility,
            presenting_complaint="Ankle pain after a fall on the stairs.",
            actor=nurse,
            arrival_mode=ArrivalMode.WALK_IN,
            patient=patient,
        )
        arrival.arrived_at = timezone.now() - timedelta(minutes=185)
        arrival.save(update_fields=["arrived_at"])
        triage(
            arrival, TriageCategory.LESS_URGENT, actor=nurse,
            reason="Weight bearing, no deformity.", pain_score=5,
        )
        arrival.refresh_from_db()

        self.stdout.write(
            f"   {arrival.reference}: category {arrival.triage_category}, "
            f"target {arrival.target_minutes} minutes, waited "
            f"{arrival.waiting_minutes}"
        )
        dispose(
            arrival, Disposition.LWBS, actor=nurse,
            notes="Told reception they were going to a private clinic.",
        )
        self.stdout.write(
            "   recorded as left without being seen — a fact about the "
            "department that only exists because somebody recorded it. An "
            "encounter that simply went quiet would flatter the numbers."
        )
        return arrival

    # -- the board ---------------------------------------------------------

    def _board(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n7. The board"))
        rows = board(facility)
        if not rows:
            self.stdout.write("   the department is empty")
            return
        for row in rows:
            marker = "!" if row["is_breaching"] else " "
            category = row["triage_category"] or "-"
            self.stdout.write(
                f"   {marker} cat {category}  {row['patient'][:22]:<22} "
                f"{row['waiting_minutes']:>3}m"
                + (f" / {row['target_minutes']}m" if row["target_minutes"] is not None else "")
                + (f"  {row['complaint'][:34]}")
            )
        self.stdout.write(
            "   ordered by triage category then arrival — a board sorted by "
            "arrival alone is the first-come-first-served queue triage exists "
            "to override"
        )

    def _summary(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n8. The department"))
        summary = department_summary(facility)
        self.stdout.write(
            f"   {summary['arrivals']} attendances since {summary['since']}, "
            f"{summary['in_department']} still here"
        )
        self.stdout.write(
            f"   median wait {summary['median_wait_minutes']}m, longest "
            f"{summary['longest_wait_minutes']}m, {summary['breaches']} "
            f"breaches ({summary['breach_percent']}%)"
        )
        for category, bucket in sorted(summary["breach_by_category"].items()):
            self.stdout.write(
                f"     category {category}: {bucket['breached']} of "
                f"{bucket['seen']} breached ({bucket['breach_percent']}%)"
            )
        self.stdout.write(
            "   per category, because an aggregate can look healthy while "
            "every single category-2 target is missed"
        )
        if summary["left_without_being_seen"]:
            self.stdout.write(self.style.WARNING(
                f"   {summary['left_without_being_seen']} left without being "
                f"seen ({summary['lwbs_percent']}%)"
            ))
        self.stdout.write(
            f"   {summary['arrived_unidentified']} arrived unidentified "
            f"({summary['still_unidentified']} still unnamed), "
            f"{summary['medico_legal']} medico-legal"
        )
        if summary["arrived_unidentified"] == 0:
            self.stdout.write(self.style.ERROR(
                "   somebody was registered without a name and the count says "
                "zero — identification erased the fact that they arrived "
                "unidentified"
            ))
        self.stdout.write(f"   by disposition: {summary['by_disposition']}")

        pathways = pathway_performance(facility)
        if pathways:
            self.stdout.write("\n   pathways:")
            for row in pathways:
                self.stdout.write(
                    f"     {row['pathway']:<16} {row['activations']} activated, "
                    f"recognition {row['average_recognition_minutes']}m, "
                    f"door-to-intervention "
                    f"{row['average_door_to_intervention_minutes']}m against "
                    f"{row['target_minutes']}m"
                )
            self.stdout.write(
                "   recognition and intervention reported separately: a slow "
                "recognition is a triage problem, a slow intervention is a "
                "resource problem, and one figure cannot tell them apart"
            )

        self.stdout.write(self.style.SUCCESS("\nShift complete.\n"))
