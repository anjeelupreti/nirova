"""A day in the operating theatre.

Through the real service layer:

1. Theatres with their own turnaround times.
2. A case requested, approved and scheduled.
3. A double-booking refused, then forced with a stated reason.
4. A surgeon on a lapsed registration refused a place in the team.
5. The WHO checklist: sign in, time out, sign out — and one case that reaches
   incision without a time-out, recorded rather than prevented.
6. Consumables and an implant, taken from real stock, with a serial number.
7. A recall: which patients have an implant from a given batch.
8. A cancellation with a countable reason.
9. Utilisation: booked against used, and the gap between them.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.billing.models import ServiceCategory, ServiceItem, TaxTreatment
from apps.hr.models import Employee, EmployeeStatus
from apps.hr.services import NotPractising
from apps.identity.models import User
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.pharmacy.models import Batch, Product, StockLocation
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization
from apps.theatre.models import (
    CHECKLIST_ITEMS,
    AnaesthesiaRecord,
    CancellationReason,
    CaseStatus,
    ChecklistPhase,
    ConsumptionKind,
    RecoveryRecord,
    SurgicalCase,
    TeamRole,
    Theatre,
    TheatreType,
    Urgency,
)
from apps.theatre.services import (
    SlotUnavailable,
    TheatreError,
    approve_case,
    assign,
    cancel_case,
    case_cost,
    checklist_state,
    complete_checklist,
    consume,
    day_list,
    implant_registry,
    mark,
    request_case,
    safety_audit,
    schedule,
    team_gaps,
    utilisation,
)

#: (code, name, type, turnaround minutes)
THEATRES = [
    ("OT-1", "Theatre 1 — General", TheatreType.GENERAL, 30),
    ("OT-2", "Theatre 2 — Orthopaedic", TheatreType.ORTHOPAEDIC, 45),
]

#: (code, name, price) — what theatre time and implants are billed as.
SERVICES = [
    ("OT-TIME", "Operating theatre, per hour", "8000.00"),
    ("OT-IMPLANT", "Implant, at cost", "0.00"),
    ("OT-CONSUMABLE", "Theatre consumables", "0.00"),
]


class Command(BaseCommand):
    help = "Run a day in the operating theatre."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        coordinator = User.objects.filter(email=f"manager@{slug}.test").first()
        surgeon_user = User.objects.filter(email=f"doctor@{slug}.test").first()
        director = User.objects.filter(email=f"owner@{slug}.test").first()
        if not (coordinator and director):
            raise CommandError("Run `seed_demo` first.")

        with tenant_context(context_for_organization(organization)):
            facility = (
                Facility.objects.filter(facility_type="hospital").first()
                or Facility.objects.filter(facility_type="clinic").first()
            )
            # Excluding provisional emergency records: an implant registry
            # that reads "Unknown 1 Unidentified" demonstrates nothing.
            patients = list(
                Patient.objects.filter(merged_into__isnull=True)
                .exclude(last_name="Unidentified")[:4]
            )
            if not patients:
                raise CommandError("No patients. Run `seed_demo` first.")

            self._services()
            theatres = self._theatres(facility)
            case = self._book(organization, facility, patients[0],
                              theatres, coordinator)
            self._clash(case, theatres, organization, facility,
                        patients[1], coordinator)
            self._team(case, coordinator, director)
            self._run(organization, case, coordinator, director)
            unsafe = self._unsafe(organization, facility, patients[2],
                                  theatres, coordinator, director)
            self._recall(case)
            self._cancel(organization, facility, patients[3], theatres,
                         coordinator)
            self._report(facility, theatres)

    # -- setup -------------------------------------------------------------

    def _services(self):
        for code, name, price in SERVICES:
            ServiceItem.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": ServiceCategory.THEATRE,
                    "default_price": Decimal(price),
                    "tax_treatment": TaxTreatment.EXEMPT,
                },
            )

    def _theatres(self, facility):
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. The theatres"))
        location = StockLocation.objects.filter(
            facility=facility
        ).first() or StockLocation.objects.first()

        rooms = {}
        for code, name, kind, turnaround in THEATRES:
            room, _ = Theatre.objects.update_or_create(
                facility=facility, code=code,
                defaults={
                    "name": name,
                    "theatre_type": kind,
                    "turnaround_minutes": turnaround,
                    "session_starts_at": time(8, 0),
                    "session_ends_at": time(17, 0),
                    "stock_location": location,
                    "has_image_intensifier": kind == TheatreType.ORTHOPAEDIC,
                    "has_laminar_flow": kind == TheatreType.ORTHOPAEDIC,
                },
            )
            rooms[code] = room
            self.stdout.write(
                f"   {room.code}: {room.name}, {room.turnaround_minutes} "
                f"minutes' turnaround, session "
                f"{room.session_starts_at:%H:%M}–{room.session_ends_at:%H:%M}"
            )
        self.stdout.write(
            "   turnaround is per room: an orthopaedic theatre and an "
            "endoscopy room are not comparable, and a scheduler assuming one "
            "number overbooks the slower room every day"
        )
        return rooms

    # -- booking -----------------------------------------------------------

    def _slot(self, hour, minute=0):
        base = timezone.localtime(timezone.now()).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return base

    def _book(self, organization, facility, patient, theatres, actor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Booking a case"))

        # Clear anything left scheduled by an earlier run. Deleted rather
        # than cancelled: a case that never ran in a previous *seed* is a demo
        # artefact, and cancelling it would put a fictional avoidable
        # cancellation into the statistics this seed then reports on.
        stale = SurgicalCase.all_objects.filter(
            facility=facility,
            status__in=["requested", "approved", "scheduled", "sent_for"],
        )
        removed = stale.count()
        stale.delete()

        # A case left mid-flight by an earlier run still holds its slot, since
        # `in_recovery` is a live status. Closed rather than deleted: it has
        # real clinical data hanging off it.
        left_open = SurgicalCase.objects.filter(
            facility=facility, status__in=["in_theatre", "in_recovery"]
        )
        closed = left_open.count()
        left_open.update(
            status=CaseStatus.COMPLETED,
            recovery_out_at=timezone.now(),
        )
        if removed or closed:
            self.stdout.write(
                f"   removed {removed} case(s) left scheduled and closed "
                f"{closed} left mid-flight by an earlier run"
            )

        case = request_case(
            organization=organization,
            patient=patient,
            facility=facility,
            planned_procedure="Total knee replacement",
            actor=actor,
            urgency=Urgency.ELECTIVE,
            planned_minutes=120,
            laterality="right",
            asa_grade=2,
            indication="End-stage osteoarthritis, failed conservative therapy.",
        )
        self.stdout.write(
            f"   {case.reference} requested: {case.planned_procedure} "
            f"({case.laterality}), {case.planned_minutes} minutes"
        )
        self.stdout.write(
            f"   {case.checklists.count()} checklist phases created at request "
            "— an unperformed one is visibly unperformed rather than merely "
            "absent"
        )

        approve_case(case, actor=actor, notes="Listed for the Tuesday list.")
        # Scheduled relative to the timings this seed will record, so the
        # start delay it reports is a believable number rather than an
        # artefact of the seed running in the afternoon.
        schedule(
            case, theatres["OT-2"],
            timezone.now() - timedelta(minutes=150), actor=actor,
        )
        case.refresh_from_db()
        self.stdout.write(
            f"   scheduled in {case.theatre.code} at "
            f"{timezone.localtime(case.scheduled_start):%H:%M}–"
            f"{timezone.localtime(case.scheduled_end):%H:%M}"
        )
        return case

    def _clash(self, case, theatres, organization, facility, patient, actor):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n3. What the schedule refuses")
        )
        second = request_case(
            organization=organization,
            patient=patient,
            facility=facility,
            planned_procedure="Arthroscopy, left knee",
            actor=actor,
            planned_minutes=45,
            laterality="left",
            asa_grade=1,
        )
        approve_case(second, actor=actor)

        # Every time below is relative to the first case's actual slot, so
        # the demonstration holds whatever hour the seed happens to run at.
        room = theatres["OT-2"]
        turnaround = timedelta(minutes=room.turnaround_minutes)

        # Inside the first case's slot.
        try:
            schedule(
                second, room,
                case.scheduled_start + timedelta(minutes=60), actor=actor,
            )
        except SlotUnavailable as exc:
            self.stdout.write(f"   overlapping booking refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   two operations booked into one room at one time"
            ))

        # Immediately after it, but inside the turnaround gap.
        try:
            schedule(
                second, room,
                case.scheduled_end + timedelta(minutes=10), actor=actor,
            )
        except SlotUnavailable as exc:
            self.stdout.write(
                f"   booking inside the turnaround gap refused: {exc}"
            )
        else:
            self.stdout.write(self.style.WARNING(
                "   a case was booked with no time to clean the room"
            ))

        # Properly clear of it: the turnaround plus a little.
        schedule(
            second, room,
            case.scheduled_end + turnaround + timedelta(minutes=15),
            actor=actor,
        )
        second.refresh_from_db()
        self.stdout.write(
            f"   {second.reference} scheduled at "
            f"{timezone.localtime(second.scheduled_start):%H:%M} — clear of "
            f"the {room.turnaround_minutes} minute turnaround"
        )

        rows = day_list(theatres["OT-2"])
        self.stdout.write(f"   the {theatres['OT-2'].code} list:")
        for row in rows:
            gap = (
                f"  (+{row['unused_gap_minutes']}m idle)"
                if row["unused_gap_minutes"] else ""
            )
            self.stdout.write(
                f"     {timezone.localtime(row['scheduled_start']):%H:%M} "
                f"{row['procedure'][:32]:<32} {row['planned_minutes']}m{gap}"
            )
        return second

    # -- the team ----------------------------------------------------------

    def _team(self, case, coordinator, director):
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. The team"))
        gaps = team_gaps(case)
        self.stdout.write(
            f"   {len(gaps)} required roles unfilled: "
            + ", ".join(row["role"] for row in gaps)
        )

        staff = list(Employee.objects.filter(status=EmployeeStatus.ACTIVE))
        lapsed = next(
            (
                person for person in staff
                if person.position and person.position.requires_licence
                and any(c.is_expired for c in person.credentials.all())
            ),
            None,
        )
        if lapsed:
            try:
                assign(case, lapsed, TeamRole.PRIMARY_SURGEON, actor=coordinator)
            except NotPractising as exc:
                self.stdout.write(
                    f"   {lapsed.full_name} refused as surgeon: {exc}"
                )
            else:
                self.stdout.write(self.style.ERROR(
                    f"   {lapsed.full_name} was assigned to operate on a "
                    "lapsed registration"
                ))

        clear_staff = [
            person for person in staff
            if not any(c.blocks_practice for c in person.credentials.all())
        ]
        roles = [
            TeamRole.PRIMARY_SURGEON,
            TeamRole.ANAESTHETIST,
            TeamRole.SCRUB_NURSE,
            TeamRole.CIRCULATING_NURSE,
        ]
        for index, role in enumerate(roles):
            if index >= len(clear_staff):
                break
            member = assign(
                case, clear_staff[index], role, actor=coordinator,
                # The circulating nurse in this demo has no registration on
                # file; a real hospital would record one.
                allow_unregistered=role == TeamRole.CIRCULATING_NURSE,
            )
            self.stdout.write(
                f"   {member.get_role_display():<20} {member.name}"
                + (f" ({member.registration_number})"
                   if member.registration_number else "")
            )

        remaining = team_gaps(case)
        if remaining:
            self.stdout.write(self.style.WARNING(
                "   still unfilled: "
                + ", ".join(row["role"] for row in remaining)
            ))
        else:
            self.stdout.write("   every required role is filled")

    # -- running it --------------------------------------------------------

    def _run(self, organization, case, coordinator, surgeon):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n5. Running the case")
        )
        start = timezone.now() - timedelta(minutes=150)

        mark(case, "sent_for", actor=coordinator, at=start)
        mark(case, "wheels_in", actor=coordinator,
             at=start + timedelta(minutes=12))

        complete_checklist(
            case, ChecklistPhase.SIGN_IN, actor=coordinator,
            responses={item: True for item in CHECKLIST_ITEMS[ChecklistPhase.SIGN_IN]},
            at=start + timedelta(minutes=15),
        )
        mark(case, "anaesthesia_start", actor=surgeon,
             at=start + timedelta(minutes=18))

        time_out = complete_checklist(
            case, ChecklistPhase.TIME_OUT, actor=surgeon,
            responses={
                **{item: True for item in CHECKLIST_ITEMS[ChecklistPhase.TIME_OUT]},
                "Essential imaging displayed": False,
            },
            concerns="Radiographs not on the screen; fetched before incision.",
            at=start + timedelta(minutes=30),
        )
        self.stdout.write(
            f"   time out completed by {time_out.completed_by_name}"
        )
        if time_out.negative_answers:
            self.stdout.write(self.style.WARNING(
                "   concerns raised: " + "; ".join(time_out.negative_answers)
            ))

        mark(case, "incision", actor=surgeon, at=start + timedelta(minutes=35))

        # Consumption, out of real stock.
        location = case.theatre.stock_location
        batch = (
            Batch.objects.filter(
                stock_levels__location=location,
                stock_levels__quantity__gt=10,
            ).select_related("product").first()
            if location else None
        )
        if batch:
            consumable = consume(
                organization, case,
                description=f"{batch.product.display_name}",
                actor=surgeon, kind=ConsumptionKind.CONSUMABLE,
                batch=batch, quantity=Decimal("4"),
                service_code="OT-CONSUMABLE",
            )
            self.stdout.write(
                f"   consumed {consumable.quantity} × {consumable.description} "
                f"from batch {consumable.batch_number} — out of the ledger, "
                "not off a list"
            )

        # An implant without a serial number, refused.
        try:
            consume(
                organization, case, description="Knee prosthesis, size 4",
                actor=surgeon, kind=ConsumptionKind.IMPLANT,
                unit_cost=Decimal("185000.00"),
            )
        except TheatreError as exc:
            self.stdout.write(f"   implant without a serial refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   an implant went in with no serial number — a recall could "
                "not name the patient"
            ))

        # Unique per run, as a real device serial is.
        serial = f"KP-4-2026-{timezone.now():%H%M%S}"
        implant = consume(
            organization, case,
            description="Knee prosthesis, size 4, cobalt-chrome",
            actor=surgeon, kind=ConsumptionKind.IMPLANT,
            serial_number=serial,
            unit_cost=Decimal("185000.00"),
            implanted_site="Right knee",
            service_code="OT-IMPLANT",
            notes="Manufacturer lot MFG-2026-Q3-114.",
        )
        self.stdout.write(
            f"   implanted {implant.description}, serial "
            f"{implant.serial_number}, into {implant.implanted_site}"
        )

        # The same device cannot go into a second patient.
        try:
            consume(
                organization, case, description="Knee prosthesis, size 4",
                actor=surgeon, kind=ConsumptionKind.IMPLANT,
                serial_number=serial, unit_cost=Decimal("185000.00"),
            )
        except TheatreError as exc:
            self.stdout.write(f"   duplicate serial refused: {exc}")
        else:
            self.stdout.write(self.style.ERROR(
                "   one physical device was recorded in two patients"
            ))

        mark(case, "closure", actor=surgeon, at=start + timedelta(minutes=128))
        complete_checklist(
            case, ChecklistPhase.SIGN_OUT, actor=coordinator,
            responses={item: True for item in CHECKLIST_ITEMS[ChecklistPhase.SIGN_OUT]},
            at=start + timedelta(minutes=133),
        )
        mark(case, "wheels_out", actor=coordinator,
             at=start + timedelta(minutes=142))

        case.performed_procedure = "Total knee replacement, right"
        case.findings = "Grade IV changes medial compartment. Good bone stock."
        case.blood_loss_ml = 250
        case.save()

        AnaesthesiaRecord.objects.update_or_create(
            case=case,
            defaults={
                "anaesthesia_type": "spinal",
                "airway": "None — spinal with sedation",
                "crystalloid_ml": 1500,
                "urine_output_ml": 400,
                "lowest_systolic": 92,
                "lowest_spo2": 96,
                "anaesthetist_name": (
                    case.team.filter(role=TeamRole.ANAESTHETIST)
                    .values_list("name", flat=True).first() or ""
                ),
                "post_op_analgesia": "Paracetamol and tramadol as prescribed.",
            },
        )
        RecoveryRecord.objects.update_or_create(
            case=case,
            defaults={
                "arrived_at": start + timedelta(minutes=142),
                "discharged_at": start + timedelta(minutes=187),
                "aldrete_score": 9,
                "pain_score": 3,
                "discharged_to": "ward",
                "nurse_name": "Recovery",
            },
        )
        mark(case, "recovery_out", actor=coordinator,
             at=start + timedelta(minutes=187))
        case.refresh_from_db()

        self.stdout.write("\n   timings:")
        self.stdout.write(
            f"     started {case.start_delay_minutes:+} minutes against the "
            "schedule"
        )
        self.stdout.write(
            f"     anaesthesia {case.anaesthesia_minutes}m, operating "
            f"{case.operating_minutes}m, theatre {case.theatre_minutes}m"
        )
        self.stdout.write(
            f"     booked for {case.planned_minutes}m, "
            f"overran by {case.overran_minutes}m"
        )
        if case.theatre_minutes <= case.operating_minutes:
            self.stdout.write(self.style.ERROR(
                "   theatre time is not longer than operating time — which "
                "is why booking a list on surgeons' estimates overruns it"
            ))
        else:
            self.stdout.write(
                f"     the room was occupied {case.theatre_minutes - case.operating_minutes}m "
                "longer than the operation took — the gap booking a list on "
                "surgeons' estimates always misses"
            )

        state = checklist_state(case)
        self.stdout.write(
            f"   checklist: all three phases complete = {state['all_complete']}, "
            f"incision without a time-out = {state['incision_without_timeout']}"
        )
        if state["incision_without_timeout"]:
            self.stdout.write(self.style.ERROR(
                "   the time-out was recorded before the incision and the "
                "audit still calls it a breach"
            ))

        cost = case_cost(case)
        self.stdout.write(
            f"   consumed {cost['items']} items totalling {cost['total']}, of "
            f"which implants {cost['by_kind'].get('implant', 0)}"
        )

    def _unsafe(self, organization, facility, patient, theatres, coordinator,
                surgeon):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n6. The case that skipped the time-out")
        )
        case = request_case(
            organization=organization, patient=patient, facility=facility,
            planned_procedure="Emergency laparotomy",
            actor=coordinator, urgency=Urgency.EMERGENCY,
            planned_minutes=90, asa_grade=4,
        )
        approve_case(case, actor=coordinator)
        schedule(
            case, theatres["OT-1"],
            timezone.now() - timedelta(minutes=60), actor=coordinator,
        )

        start = timezone.now() - timedelta(minutes=60)
        mark(case, "wheels_in", actor=coordinator, at=start)
        mark(case, "anaesthesia_start", actor=surgeon,
             at=start + timedelta(minutes=4))
        # Straight to incision. No time-out.
        mark(case, "incision", actor=surgeon, at=start + timedelta(minutes=9))

        state = checklist_state(case)
        self.stdout.write(
            f"   {case.reference}: incision at "
            f"{timezone.localtime(case.incision_at):%H:%M} with no time-out"
        )
        if state["incision_without_timeout"]:
            self.stdout.write(self.style.WARNING(
                "   recorded as an incision without a time-out — the system "
                "did not stop the surgeon, it made the omission undeniable"
            ))
        else:
            self.stdout.write(self.style.ERROR(
                "   the omission was not recorded"
            ))

        # And the honest version: skipped, with a reason.
        from apps.theatre.services import skip_checklist

        skip_checklist(
            case, ChecklistPhase.TIME_OUT, actor=surgeon,
            reason=(
                "Exsanguinating haemorrhage; time-out performed verbally "
                "without recording. Declared at handover."
            ),
        )
        state = checklist_state(case)
        skipped = [row for row in state["phases"] if row["skipped"]]
        self.stdout.write(
            f"   afterwards recorded as skipped, with a reason: "
            f"{skipped[0]['skip_reason'][:60]}…"
        )
        self.stdout.write(
            "   a blank phase is indistinguishable from nobody filling the "
            "form in; a skip with a reason is a decision somebody made"
        )
        mark(case, "closure", actor=surgeon, at=start + timedelta(minutes=52))
        mark(case, "wheels_out", actor=coordinator,
             at=start + timedelta(minutes=58))
        mark(case, "recovery_out", actor=coordinator,
             at=start + timedelta(minutes=95))
        return case

    # -- recall ------------------------------------------------------------

    def _recall(self, case):
        self.stdout.write(
            self.style.MIGRATE_HEADING("\n7. A manufacturer recall")
        )
        registry = implant_registry()
        self.stdout.write(
            f"   {len(registry)} implants on the register:"
        )
        for row in registry[:5]:
            self.stdout.write(
                f"     {row['patient']:<22} {row['mrn']:<12} "
                f"{row['serial_number']:<18} {row['site']}"
            )
        if not registry:
            self.stdout.write(self.style.ERROR(
                "   no implants recorded — a recall could not name anybody"
            ))
        else:
            self.stdout.write(
                "   names and phone numbers, not a count: that is the whole "
                "reason a serial number is stored"
            )

    # -- cancelling --------------------------------------------------------

    def _cancel(self, organization, facility, patient, theatres, actor):
        self.stdout.write(self.style.MIGRATE_HEADING("\n8. A cancellation"))
        case = request_case(
            organization=organization, patient=patient, facility=facility,
            planned_procedure="Inguinal hernia repair",
            actor=actor, planned_minutes=60, laterality="left", asa_grade=2,
        )
        approve_case(case, actor=actor)
        schedule(
            case, theatres["OT-1"],
            timezone.now() + timedelta(hours=3), actor=actor,
        )

        cancel_case(
            case, actor=actor,
            reason=CancellationReason.NO_BED,
            notes="No post-operative bed on the surgical ward.",
        )
        case.refresh_from_db()
        self.stdout.write(
            f"   {case.reference} cancelled: "
            f"{case.get_cancellation_reason_display()}"
        )
        self.stdout.write(
            f"   avoidable by the hospital: {case.was_avoidable_cancellation}"
        )
        if not case.was_avoidable_cancellation:
            self.stdout.write(self.style.ERROR(
                "   'no bed available' should count as avoidable — it is the "
                "number a theatre committee acts on"
            ))
        else:
            self.stdout.write(
                "   the reason is an enum because a cancelled list is a "
                "hospital's largest single waste, and 'why' has to be summable"
            )

    # -- reporting ---------------------------------------------------------

    def _report(self, facility, theatres):
        self.stdout.write(self.style.MIGRATE_HEADING("\n9. The theatres"))
        for room in theatres.values():
            stats = utilisation(room)
            self.stdout.write(
                f"   {room.code}: {stats['cases']} cases, "
                f"{stats['completed']} completed, {stats['cancelled']} "
                f"cancelled ({stats['avoidable_cancellations']} avoidable)"
            )
            if stats["session_minutes"]:
                self.stdout.write(
                    f"     booked {stats['booked_percent']}% of the session, "
                    f"used {stats['used_percent']}%"
                )
                self.stdout.write(
                    "     booked and used reported separately: a room booked "
                    "to 90% that operates for 60% has an hour a day of late "
                    "starts and slow turnarounds, and one figure would hide it"
                )
            if stats["average_start_delay_minutes"] is not None:
                self.stdout.write(
                    f"     {stats['cases_starting_late']} started late, "
                    f"average delay {stats['average_start_delay_minutes']}m, "
                    f"average overrun {stats['average_overrun_minutes']}m"
                )
            if stats["cancellation_reasons"]:
                self.stdout.write(
                    f"     cancelled because: {stats['cancellation_reasons']}"
                )

        audit = safety_audit(facility)
        self.stdout.write(
            f"\n   safety: {audit['operations']} operations, "
            f"{audit['incisions_without_a_time_out']} incisions without a "
            f"time-out ({audit['breach_percent']}%), "
            f"{audit['phases_skipped']} phases skipped"
        )
        if audit["breaching_cases"]:
            self.stdout.write(self.style.WARNING(
                "   cases to review: " + ", ".join(audit["breaching_cases"])
            ))
        self.stdout.write(
            "   the number that matters is not how many checklists exist but "
            "how many incisions happened without a time-out"
        )

        self.stdout.write(self.style.SUCCESS("\nList complete.\n"))
