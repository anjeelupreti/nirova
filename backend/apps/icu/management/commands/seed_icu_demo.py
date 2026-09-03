"""A night in the intensive care unit, narrated.

The seed runs the real service layer and prints what it expects beside what it
got. Nothing here asserts; the output is meant to be read, and it contradicts
itself out loud when the arithmetic is wrong. Every bug in this module so far
was found this way rather than by a test — a test tells you a number changed,
and this tells you a number is absurd.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.icu.models import (
    AdmissionRoute,
    AlertSeverity,
    DeviceType,
    FluidDirection,
    FluidRoute,
    IcuOutcome,
    ObservationSource,
    VentilationMode,
)
from apps.icu.services import (
    acknowledge_alert,
    admit_to_icu,
    alert_summary,
    change_rate,
    chart_observation,
    chart_ventilation,
    cumulative_balance,
    device_days,
    discharge_from_icu,
    fasthug_compliance,
    fluid_balance,
    infused_volume,
    infusion_state,
    insert_device,
    overdue_devices,
    record_fluid,
    record_round,
    remove_device,
    score_sofa,
    set_ceiling_of_care,
    set_threshold,
    severity_trend,
    start_infusion,
    step_down_blockers,
    stop_infusion,
    unit_board,
    unit_summary,
    validate_observation,
    ventilator_days,
)
from apps.identity.models import User
from apps.inpatient.models import (
    Admission,
    AdmissionStatus,
    Bed,
    BedStatus,
    Ward,
    WardType,
)
from apps.inpatient.services import admit, available_beds, transfer_bed
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Seed an ICU shift: charting, titration, scoring and step-down."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.get(slug=options["org"])
        with tenant_context(context_for_organization(organization)):
            self.run(organization)

    # -- helpers ----------------------------------------------------------

    def say(self, text=""):
        self.stdout.write(text)

    def step(self, number, title):
        self.say("")
        self.say(self.style.MIGRATE_HEADING(f"{number}. {title}"))

    def expect(self, claim, expected, actual):
        """Print a claim beside the number, and mark it when they disagree."""
        agrees = str(expected) == str(actual)
        mark = "  " if agrees else "  <-- DISAGREES"
        self.say(f"   {claim}: expected {expected}, got {actual}{mark}")

    # -- the shift --------------------------------------------------------

    def run(self, organization):
        now = timezone.now()
        actor = User.objects.filter(email__endswith="@manakamana.test").first()
        facility = Facility.objects.filter(facility_type="hospital").first()

        self.step(1, "The unit")
        ward = Ward.objects.filter(
            facility=facility, ward_type=WardType.ICU
        ).first()
        if not ward:
            ward = Ward.objects.create(
                facility=facility,
                code="ICU",
                name="Intensive Care Unit",
                ward_type=WardType.ICU,
                nurse_to_patient_ratio=Decimal("1.0"),
                is_gender_segregated=False,
                allows_attendant=False,
                notes="Eight beds, all monitored, six ventilated.",
            )
            for index in range(1, 7):
                Bed.objects.create(
                    ward=ward,
                    code=f"ICU-{index:02d}",
                    has_oxygen=True,
                    has_suction=True,
                    has_monitor=True,
                    has_ventilator=index <= 4,
                    daily_rate=Decimal("8500.00"),
                    service_code="BED-ICU",
                )
        beds = list(ward.beds.order_by("code"))
        self.say(f"   {ward.name}: {len(beds)} beds, "
                 f"{sum(1 for bed in beds if bed.has_ventilator)} ventilated.")

        # Free any bed still held by a previous run, so the seed is
        # re-runnable. A seed that only works on an empty database is a seed
        # nobody runs twice, and the second run is where the bugs are.
        self.step(2, "Clearing what an earlier run left behind")
        # Closing the ICU episode does not vacate the bed -- the two are
        # deliberately separate, since a patient whose ICU care has ended is
        # often still physically in the unit waiting for a ward bed. So the
        # cleanup has to move them out as well, exactly as a real step-down
        # would.
        general = Ward.objects.filter(
            facility=facility, ward_type=WardType.GENERAL
        ).first()

        def free_bed(in_ward, gender=""):
            """A bed this patient may actually go into.

            Gender segregation is real on a general ward, so the seed asks
            `available_beds` rather than taking the first empty one -- which
            is how the first run of this cleanup discovered that it was
            putting a man in a bed reserved for women.
            """
            for candidate in in_ward.beds.filter(
                is_active=True, status=BedStatus.CLEANING
            ):
                candidate.status = BedStatus.AVAILABLE
                candidate.save(update_fields=["status"])
            options = available_beds(ward=in_ward, gender=gender)
            return options[0] if options else None

        stale = list(ward.icu_stays.filter(outcome=IcuOutcome.ONGOING))
        for stay in stale:
            discharge_from_icu(
                stay, IcuOutcome.TO_WARD, actor=actor,
                bed=free_bed(general, stay.patient.gender),
                notes="Cleared by a re-run of the seed.",
                override_blockers=True,
            )
        # An earlier run may also have left patients physically in ICU beds
        # after their episode was closed. Move them out too, or the unit is
        # full of people who are not in it.
        left_behind = 0
        for bed in ward.beds.all():
            assignment = bed.assignments.filter(vacated_at__isnull=True).first()
            if assignment is None:
                continue
            destination = free_bed(
                general, assignment.admission.patient.gender,
            )
            if destination is None:
                break
            transfer_bed(
                assignment.admission, destination, actor=actor,
                reason="Cleared by a re-run of the ICU seed.",
            )
            left_behind += 1

        self.say(f"   {len(stale)} stay(s) closed, {left_behind} bed(s) "
                 "vacated, all moved back to a ward.")
        for bed in ward.beds.all():
            if bed.status == BedStatus.CLEANING:
                bed.status = BedStatus.AVAILABLE
                bed.save(update_fields=["status"])
        beds = list(ward.beds.order_by("code"))

        self.step(3, "Three admissions")
        # The seed admits its own patients rather than borrowing whoever
        # happens to be in a bed. A seed that depends on another seed's
        # leftovers works once and then reports something different every
        # time, which is the opposite of what a narrated seed is for.
        stories = [
            (AdmissionRoute.WARD, "Septic shock, ward deterioration",
             Decimal("64.0")),
            (AdmissionRoute.THEATRE, "Post-operative, elective ventilation",
             Decimal("78.5")),
            (AdmissionRoute.EMERGENCY, "Severe head injury", Decimal("55.0")),
        ]
        patients = list(
            Patient.objects.filter(merged_into__isnull=True).order_by("id")[:12]
        )
        candidates = []
        for patient in patients:
            if len(candidates) == 3:
                break
            existing = Admission.objects.filter(
                patient=patient, status__in=(
                    AdmissionStatus.ADMITTED, AdmissionStatus.PENDING,
                ),
            ).first()
            if existing:
                candidates.append(existing)
                continue
            try:
                candidates.append(admit(
                    organization, patient, facility, actor=actor,
                    ward=general, source="emergency",
                    admitting_diagnosis="For intensive care",
                ))
            except Exception as error:  # a full ward, a merged record
                self.say(f"   could not admit {patient.mrn}: {error}")

        if len(candidates) < 3:
            self.say(self.style.WARNING(
                "   Could not find or create three admissions."
            ))
            return
        self.say(f"   {len(candidates)} patients admitted and on a ward.")

        free = [bed for bed in beds if bed.status == BedStatus.AVAILABLE]
        if len(free) < 3:
            self.say(self.style.WARNING("   Not enough free ICU beds."))
            return

        stays = []
        for admission, bed, (route, reason, weight) in zip(
            candidates, free, stories
        ):
            stay = admit_to_icu(
                organization, admission, ward, bed, reason, actor=actor,
                route=route, at=now - timedelta(days=3),
            )
            stay.weight_kg = weight
            stay.save(update_fields=["weight_kg"])
            stays.append(stay)
            self.say(f"   {stay.patient.full_name} into {bed.code}: {reason}")

        septic, post_op, head_injury = stays

        self.step(4, "A night of observations on the septic patient")
        # Three days of charting, four-hourly, with the pressure falling
        # through the first night and recovering after the noradrenaline.
        charted = 0
        for hour in range(0, 72, 4):
            at = septic.admitted_at + timedelta(hours=hour)
            falling = hour < 12
            chart_observation(
                septic, actor=actor, at=at,
                heart_rate=118 if falling else 92,
                systolic=78 if falling else 112,
                diastolic=44 if falling else 68,
                respiratory_rate=26 if falling else 18,
                spo2=93 if falling else 97,
                temperature=Decimal("38.9") if falling else Decimal("37.2"),
                gcs_eye=3, gcs_verbal=4, gcs_motor=6,
                lactate=Decimal("4.8") if falling else Decimal("1.6"),
                blood_glucose=Decimal("9.2"),
            )
            charted += 1
        self.say(f"   {charted} observation sets charted over three days.")

        alerts = septic.alerts.all()
        self.say(f"   {alerts.count()} alerts across "
                 f"{len(set(alerts.values_list('parameter', flat=True)))} "
                 "parameters — low pressure, high lactate, fever, tachycardia.")
        self.say("   Parameters: " + ", ".join(sorted(
            set(alerts.values_list("parameter", flat=True))
        )))

        self.step(5, "A device reading nobody has validated")
        artefact = chart_observation(
            septic, actor=actor,
            at=now - timedelta(hours=2),
            source=ObservationSource.DEVICE,
            device_identifier="PHILIPS-MX450-3",
            systolic=300, diastolic=150, heart_rate=95,
            notes="Arterial line flushed.",
        )
        from_device = septic.alerts.filter(from_unvalidated_device=True).count()
        self.say(f"   {from_device} alert(s) flagged as coming from "
                 "unvalidated device data.")
        self.say("   An arterial line reading 300/150 during a flush is "
                 "artefact. It is stored, alerted, and marked as unvalidated —")
        self.say("   because deleting it would hide a transducer that is "
                 "misbehaving.")
        validate_observation(artefact, actor=actor)
        self.say(f"   Validated by {artefact.validated_by_name or 'staff'} — "
                 "the row stays either way.")

        self.step(6, "Noradrenaline, titrated")
        pressor = start_infusion(
            septic, "Noradrenaline", Decimal("0.05"), actor=actor,
            concentration="4mg in 50ml", rate_unit="mcg/kg/min",
            is_titratable=True, target="MAP > 65",
            maximum_rate=Decimal("0.5"),
            at=septic.admitted_at + timedelta(hours=1),
        )
        titration = [
            (2, "0.10", "MAP 58"),
            (4, "0.20", "MAP 55, fluid given"),
            (8, "0.15", "MAP 72, weaning"),
            (16, "0.08", "MAP 78"),
            (30, "0.03", "Weaning"),
        ]
        for hours, rate, reason in titration:
            change_rate(
                pressor, Decimal(rate), actor=actor, reason=reason,
                at=septic.admitted_at + timedelta(hours=hours),
            )
        self.expect("rate changes recorded", len(titration) + 1,
                   pressor.rates.count())
        self.say("   Every rate is still there, with why it changed. "
                 "'What was she on when the pressure dropped?' has an answer.")

        maintenance = start_infusion(
            septic, "Sodium chloride 0.9%", Decimal("80"), actor=actor,
            rate_unit="ml/hr",
            at=septic.admitted_at + timedelta(hours=1),
        )
        volume = infused_volume(
            maintenance, until=septic.admitted_at + timedelta(hours=25),
        )
        self.expect(
            "volume infused at 80ml/hr for 24 hours", "1920.0", volume,
        )
        pressor_volume = infused_volume(pressor)
        self.expect(
            "volume for a mcg/kg/min infusion", None, pressor_volume,
        )
        self.say("   Nothing, deliberately: that rate integrates to a dose, "
                 "not to millilitres, and a number that looked like volume")
        self.say("   would be worse than none.")

        self.step(7, "Fluid balance")
        # A day that ends up 1,150ml positive: 2,400 in, 1,250 out.
        day_start = septic.admitted_at + timedelta(days=1)
        for hour, direction, route, volume_ml, what in [
            (1, FluidDirection.IN, FluidRoute.IV, 1000, "Hartmann's"),
            (4, FluidDirection.IN, FluidRoute.IV, 500, "Antibiotic"),
            (6, FluidDirection.IN, FluidRoute.NASOGASTRIC, 400, "Feed"),
            (10, FluidDirection.IN, FluidRoute.IV, 500, "Hartmann's"),
            (2, FluidDirection.OUT, FluidRoute.URINE, 300, ""),
            (6, FluidDirection.OUT, FluidRoute.URINE, 350, ""),
            (10, FluidDirection.OUT, FluidRoute.URINE, 400, ""),
            (12, FluidDirection.OUT, FluidRoute.DRAIN, 200, "Abdominal drain"),
        ]:
            record_fluid(
                septic, direction, route, volume_ml, actor=actor,
                description=what, at=day_start + timedelta(hours=hour),
            )

        balance = fluid_balance(
            septic, hours=24, until=day_start + timedelta(hours=24),
        )
        self.expect("intake for the day", 2400, balance["intake_ml"])
        self.expect("output for the day", 1250, balance["output_ml"])
        self.expect("balance", 1150, balance["balance_ml"])
        self.expect("urine", 1050, balance["urine_ml"])
        # 1,050ml over 24 hours at 64kg is 0.68 ml/kg/hr -- below 0.5 is
        # oliguria, so this patient is passing enough, just.
        self.expect(
            "urine ml/kg/hr at 64kg", "0.68",
            balance["urine_ml_per_kg_per_hour"],
        )

        cumulative = cumulative_balance(septic)
        self.say(f"   Cumulative over {len(cumulative['days'])} ICU days: "
                 f"{cumulative['cumulative_ml']}ml")
        self.say("   The cumulative figure is the one nobody has and the one "
                 "that matters — a patient six litres up over four days is in")
        self.say("   trouble no single day's chart shows.")

        self.step(8, "Ventilation: what was set, and what came back")
        for hours, mode, settings in [
            (1, VentilationMode.CMV, dict(
                set_rate=16, set_tidal_volume=420, peep=Decimal("8.0"),
                fio2=60, measured_rate=16, expired_tidal_volume=410,
                peak_pressure=Decimal("28.0"), plateau_pressure=Decimal("24.0"),
                pao2=Decimal("78.0"), paco2=Decimal("45.0"), ph=Decimal("7.31"),
            )),
            (24, VentilationMode.SIMV, dict(
                set_rate=12, set_tidal_volume=420, peep=Decimal("6.0"),
                fio2=40, measured_rate=18, expired_tidal_volume=330,
                peak_pressure=Decimal("24.0"), plateau_pressure=Decimal("19.0"),
                pao2=Decimal("92.0"), paco2=Decimal("41.0"), ph=Decimal("7.38"),
            )),
            (48, VentilationMode.PSV, dict(
                pressure_support=Decimal("10.0"), peep=Decimal("5.0"),
                fio2=35, measured_rate=16, expired_tidal_volume=450,
                pao2=Decimal("98.0"),
            )),
        ]:
            chart_ventilation(
                septic, mode, actor=actor,
                at=septic.admitted_at + timedelta(hours=hours), **settings,
            )

        record = septic.ventilation.order_by("recorded_at")[1]
        self.expect(
            "set tidal volume vs what came back at 24 hours",
            "420 set, 330 expired",
            f"{record.set_tidal_volume} set, {record.expired_tidal_volume} expired",
        )
        self.say("   A 90ml leak, visible only because the two are separate "
                 "fields.")
        self.say("   One `tidal_volume` field would have answered both "
                 "questions with whichever number somebody typed, and the")
        self.say("   difference between them is a cuff leak.")

        first = septic.ventilation.order_by("recorded_at").first()
        self.expect(
            "PF ratio on admission (PaO2 78 on 60% oxygen)", "130", first.pf_ratio,
        )
        self.expect(
            "driving pressure (plateau 24 minus PEEP 8)", "16.0",
            first.driving_pressure,
        )

        vent_days = ventilator_days(septic)
        self.say(f"   Invasive ventilation: {vent_days['invasive_hours']} hours "
                 f"({vent_days['invasive_days']} days)")

        self.step(9, "Lines and tubes")
        central = insert_device(
            septic, DeviceType.CENTRAL_LINE, actor=actor,
            site="Right internal jugular", size="7Fr",
            at=septic.admitted_at, in_emergency=True,
        )
        insert_device(
            septic, DeviceType.ARTERIAL_LINE, actor=actor,
            site="Left radial", at=septic.admitted_at,
        )
        insert_device(
            septic, DeviceType.URINARY_CATHETER, actor=actor,
            at=septic.admitted_at,
        )
        insert_device(
            septic, DeviceType.ENDOTRACHEAL, actor=actor, size="7.5",
            at=septic.admitted_at,
        )
        overdue = overdue_devices(septic)
        self.expect("lines flagged as needing attention", 1, len(overdue))
        for row in overdue:
            self.say(f"   {row['device']} ({row['site']}): {row['reason']}, "
                     f"{row['days_in_situ']} days")

        remove_device(
            central, actor=actor, reason="Re-sited electively", infected=False,
            at=now - timedelta(days=1),
        )
        self.expect(
            "line-days for the central line (3 days in, removed yesterday)",
            "2.0", central.days_in_situ,
        )

        self.step(10, "The daily round")
        for day, plan, fasthug in [
            (0, "Continue noradrenaline, wean FiO2, hold sedation in the "
                "morning.",
             {"feeding": True, "analgesia": True, "sedation": True,
              "thromboprophylaxis": False, "head_up": True,
              "ulcer_prophylaxis": True, "glucose": True}),
            (1, "Weaning. Trial of pressure support tomorrow.",
             {"feeding": True, "analgesia": True, "sedation": True,
              "thromboprophylaxis": True, "head_up": True,
              "ulcer_prophylaxis": True, "glucose": True}),
            (2, "Extubate today if the trial goes well. For step-down.",
             {"feeding": True, "analgesia": True, "sedation": True,
              "thromboprophylaxis": True, "head_up": True, "glucose": True}),
        ]:
            record_round(
                septic, actor=actor,
                at=septic.admitted_at + timedelta(days=day, hours=9),
                assessment="Septic shock, improving.",
                plan=plan,
                fasthug=fasthug,
                fasthug_reasons={"thromboprophylaxis": "Platelets 38, held."},
                sedation_hold=True, weaning_trial=day >= 1,
                step_down=day == 2, family_updated=True,
            )
        self.expect("rounds recorded", 3, septic.rounds.count())
        last_round = septic.rounds.order_by("-icu_day").first()
        self.expect(
            "FASTHUG items nobody answered on the last round",
            "['ulcer_prophylaxis']", last_round.missed_items,
        )
        self.say("   A missing item is missing, not false. Nobody considered "
                 "ulcer prophylaxis on day three, and that is a different")
        self.say("   fact from considering it and deciding against.")

        self.step(11, "SOFA, and what it could not score")
        partial = score_sofa(septic, at=septic.admitted_at + timedelta(hours=12))
        self.say(f"   Day 1 with no labs: total {partial.total}, "
                 f"missing {partial.missing_components}")
        self.expect("is that score complete?", False, partial.is_complete)

        full = score_sofa(
            septic,
            at=septic.admitted_at + timedelta(hours=12),
            platelets=38, bilirubin=Decimal("2.4"),
            creatinine=Decimal("2.1"), urine_ml_24h=1050,
        )
        self.say(f"   The same day with labs: total {full.total}, "
                 f"missing {full.missing_components}")
        self.say(f"   Components: {full.components}")
        self.expect(
            "did adding the labs raise the score?", "yes",
            "yes" if full.total > partial.total else "NO",
        )
        self.say("   The gaps had been scoring as zero.")
        self.say("   That is the whole reason `missing_components` exists. A "
                 "missing bilirubin and a healthy liver both score 0, and the")
        self.say("   error only ever runs one way: the patient looks less sick "
                 "than they are.")

        for day, values in [
            (1, dict(platelets=52, bilirubin=Decimal("2.0"),
                     creatinine=Decimal("1.6"), urine_ml_24h=1400)),
            (2, dict(platelets=110, bilirubin=Decimal("1.4"),
                     creatinine=Decimal("1.1"), urine_ml_24h=1900)),
        ]:
            score_sofa(
                septic, at=septic.admitted_at + timedelta(days=day, hours=12),
                **values,
            )
        trend = severity_trend(septic)
        self.say("   Trajectory: " + " → ".join(
            f"day {row['icu_day']}: {row['total']}"
            f"{'' if row['complete'] else ' (partial)'}"
            for row in trend
        ))

        self.step(12, "A patient with a threshold of their own")
        chart_observation(
            head_injury, actor=actor, at=now - timedelta(hours=6),
            heart_rate=88, systolic=104, diastolic=62, spo2=89,
            respiratory_rate=14, gcs_eye=1, gcs_motor=4,
            gcs_verbal_not_testable=True,
        )
        before = head_injury.alerts.filter(parameter="spo2").count()
        set_threshold(
            head_injury, "spo2", actor=actor,
            reason="Chronic lung disease, lives at 88%.",
            low=Decimal("86"), critical_low=Decimal("82"),
        )
        chart_observation(
            head_injury, actor=actor, at=now - timedelta(hours=2),
            heart_rate=86, systolic=108, diastolic=64, spo2=89,
            respiratory_rate=15, gcs_eye=1, gcs_motor=4,
            gcs_verbal_not_testable=True,
        )
        after = head_injury.alerts.filter(parameter="spo2").count()
        self.expect(
            "alerts on the same 89% saturation, before then after the "
            "threshold change", "1 then 0",
            f"{before} then {after - before}",
        )
        self.say("   Alerting all night on a saturation this patient lives at "
                 "is how the alarm that matters gets ignored.")

        latest = head_injury.observations.order_by("-recorded_at").first()
        self.expect(
            "GCS total with an untestable verbal score (E1 V1nt M4)",
            6, latest.gcs_total,
        )
        self.say("   And the SOFA excludes that day's neurology entirely "
                 "rather than scoring four points of brain failure caused by")
        self.say("   the sedation.")

        self.step(13, "Acknowledging what fired")
        unacknowledged = list(
            septic.alerts.filter(acknowledged_at__isnull=True)[:4]
        )
        for alert in unacknowledged[:3]:
            acknowledge_alert(
                alert, actor=actor, action="Reviewed, fluid given.",
            )
        summary = alert_summary(septic, hours=96)
        self.say(f"   {summary['total']} alerts in 96 hours, "
                 f"{summary['critical']} critical, "
                 f"{summary['unacknowledged']} unacknowledged.")
        self.say(f"   Median minutes to acknowledge: "
                 f"{summary['median_minutes_to_acknowledge']}")
        self.say(f"   Most frequent: {list(summary['by_parameter'].items())[:3]}")
        self.say("   An alert that self-cleared when the number came back "
                 "would leave none of this to look at in the morning.")

        self.step(14, "Ceiling of care")
        set_ceiling_of_care(
            head_injury,
            "For full support including renal replacement. Not for CPR.",
            actor=actor, for_resuscitation=False,
        )
        chart_observation(
            head_injury, actor=actor, heart_rate=38, systolic=76,
            diastolic=40, spo2=90,
        )
        newest = head_injury.alerts.order_by("-raised_at").first()
        self.say(f"   Alert text: {newest.message}")
        self.expect(
            "does the alert say the patient is not for resuscitation?",
            "yes", "yes" if "Not for resuscitation" in newest.message else "NO",
        )

        self.step(15, "Step-down")
        blockers = step_down_blockers(septic)
        self.say(f"   {septic.patient.full_name}: {len(blockers)} blocker(s)")
        for row in blockers:
            self.say(f"     · [{row['kind']}] {row['detail']}")
        self.say("   Sentences, not a boolean, and labelled. A vasopressor "
                 "makes the patient unfit for a ward; an unacknowledged alert")
        self.say("   is unfinished reviewing. Both stop the step-down and they "
                 "are not the same argument.")

        stop_infusion(pressor, actor=actor, reason="Off pressors")
        stop_infusion(maintenance, actor=actor, reason="Eating and drinking")
        chart_ventilation(
            septic, VentilationMode.SPONTANEOUS, actor=actor,
            fio2=28, is_invasive=False,
        )
        clinical_left = step_down_blockers(septic)
        self.expect(
            "clinical blockers after the pressors stopped and the tube "
            "came out", 0,
            sum(1 for row in clinical_left if row["kind"] == "clinical"),
        )
        self.expect(
            "what is left", "record",
            ", ".join(sorted({row["kind"] for row in clinical_left})),
        )

        for alert in septic.alerts.filter(
            acknowledged_at__isnull=True, severity=AlertSeverity.CRITICAL,
        ):
            acknowledge_alert(
                alert, actor=actor, action="Reviewed at the handover.",
            )
        self.expect(
            "blockers once the alerts were reviewed", 0,
            len(step_down_blockers(septic)),
        )

        self.step(16, "The board")
        board = unit_board(ward)
        self.say(f"   {len(board)} patients, sickest and least-attended first:")
        for row in board:
            flags = []
            if row["critical_alerts"]:
                flags.append(f"{row['critical_alerts']} critical alerts")
            if row["ventilated"]:
                flags.append(f"ventilated {row['mode']}")
            if row["vasopressors"]:
                flags.append("+".join(row["vasopressors"]))
            if not row["for_resuscitation"]:
                flags.append("not for CPR")
            self.say(
                f"     {row['bed']:8} {row['patient'][:22]:22} "
                f"day {row['icu_day']}  SOFA "
                f"{row['sofa'] if row['sofa'] is not None else '—'}"
                f"{'' if row['sofa_complete'] in (True, None) else '*'}  "
                f"{', '.join(flags)}"
            )
        self.say("   A board sorted by bed number tells a charge nurse nothing "
                 "they did not know from walking past.")

        self.step(17, "Stepping one patient out")
        discharge_from_icu(
            septic, IcuOutcome.TO_WARD, actor=actor,
            bed=free_bed(general, septic.patient.gender),
            notes="Extubated, off pressors, for the ward.",
        )
        self.expect("stay closed", False, septic.is_current)
        self.expect(
            "infusions left running against a closed stay",
            0,
            septic.infusions.exclude(status="stopped").count(),
        )
        self.say("   An infusion left running against a closed stay would "
                 "accumulate volume forever in every later calculation.")

        self.step(18, "The unit's numbers")
        stats = unit_summary(facility, since=now - timedelta(days=90))
        for key, value in stats.items():
            self.say(f"   {key}: {value}")
        self.say("   Mortality is printed beside transferred-out and LAMA "
                 "because both remove a patient whose outcome nobody knows —")
        self.say("   and a mortality rate quoted without them can be improved "
                 "by transferring the sickest patients out.")

        self.step(19, "Infection surveillance")
        surveillance = device_days(facility, since=now - timedelta(days=90))
        for device_type, bucket in surveillance["by_type"].items():
            self.say(
                f"   {device_type}: {bucket['devices']} devices, "
                f"{bucket['device_days']} device-days, "
                f"{bucket['infections']} infections, "
                f"{bucket['per_thousand_device_days']} per 1,000 device-days"
            )
        self.say("   'Six infections' means nothing. Six per thousand "
                 "line-days is a number a unit can act on.")

        self.step(20, "Daily-goals compliance")
        compliance = fasthug_compliance(facility, since=now - timedelta(days=90))
        self.say(f"   Across {compliance['rounds']} rounds:")
        for item in compliance["items"]:
            self.say(
                f"     {item['item']:20} answered {item['answered']:3} "
                f"({item['answered_percent']}%), declined {item['declined']}"
            )
        self.say("   Reported per item because they fail differently: "
                 "sedation is nearly always addressed and thromboprophylaxis")
        self.say("   is the one that quietly is not.")

        self.say("")
        self.say(self.style.SUCCESS("ICU seed complete."))
