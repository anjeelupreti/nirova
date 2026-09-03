"""A week in the blood bank, and every refusal that matters.

The module is built around refusals rather than warnings, so the seed's job is
to try each dangerous thing and show it being stopped. Nothing here asserts;
it prints what it expects beside what it got, and contradicts itself out loud
when a guard is missing.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bloodbank.models import (
    RED_CELL_COMPATIBILITY,
    SCREENING_KEYS,
    BloodGroup,
    BloodUnit,
    ComponentType,
    CrossMatchResult,
    Donation,
    DonationStatus,
    Donor,
    DonorStatus,
    InfectionResult,
    ReactionSeverity,
    RequestUrgency,
    UnitStatus,
)
from apps.bloodbank.services import (
    BloodBankError,
    Incompatible,
    collect_donation,
    compatible_units,
    cross_match,
    defer_donor,
    discard_unit,
    donor_call_list,
    expire_units,
    finish_transfusion,
    haemovigilance,
    issue_blockers,
    issue_emergency,
    issue_unit,
    look_back,
    record_grouping,
    record_observation,
    record_screening,
    register_donor,
    release_blockers,
    release_units,
    report_reaction,
    request_blood,
    reserve_unit,
    return_unit,
    separate_components,
    stock,
    trace_patient,
    transfuse,
    verify_screening,
    wastage,
)
from apps.identity.models import User
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Person:
    """A stand-in actor, so the two-person checks are genuinely two people."""

    def __init__(self, name, uuid=None):
        self.full_name = name
        self.uuid = uuid


class Command(BaseCommand):
    help = "Seed donors, donations, components, cross-matches and transfusions."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.get(slug=options["org"])
        with tenant_context(context_for_organization(organization)):
            self.run(organization)

    def say(self, text=""):
        self.stdout.write(text)

    def step(self, number, title):
        self.say("")
        self.say(self.style.MIGRATE_HEADING(f"{number}. {title}"))

    def expect(self, claim, expected, actual):
        agrees = str(expected) == str(actual)
        self.say(
            f"   {claim}: expected {expected}, got {actual}"
            f"{'  ' if agrees else '  <-- DISAGREES'}"
        )

    def refused(self, what, call):
        """Run something that must be refused, and print the refusal."""
        try:
            call()
            self.say(f"   <-- DISAGREES: {what} was allowed")
        except (BloodBankError, Incompatible) as error:
            detail = getattr(error, "detail", {}) or {}
            self.say(f"   Refused: {error}")
            for line in detail.get("blockers", detail.get("reasons", []))[:4]:
                self.say(f"     · {line}")

    def run(self, organization):
        actor = User.objects.filter(email="owner@manakamana.test").first()
        facility = Facility.objects.filter(facility_type="hospital").first()
        today = timezone.localdate()
        now = timezone.now()

        # Two different people, because the two-person checks are the point.
        first = Person("Kabita Rai")
        second = Person("Dipesh Thapa")

        self.step(1, "The module has to be bought")
        from apps.catalog.models import AddOn
        from apps.subscriptions.models import Subscription, SubscriptionAddOn

        subscription = Subscription.objects.filter(
            organization=organization, status="active",
        ).first()
        addon = AddOn.objects.filter(target_key="blood_bank").first()
        if addon is None:
            self.say(self.style.WARNING(
                "   No blood-bank module in the catalogue. Add one to "
                "seed_catalog, or the entitlement check will refuse "
                "everything below."
            ))
            return
        link, was_new = SubscriptionAddOn.objects.get_or_create(
            subscription=subscription, addon=addon,
            defaults={"quantity": 1, "unit_price": addon.unit_price,
                      "source_reference": "seed_bloodbank_demo"},
        )
        self.say(f"   {addon.name} "
                 f"{'attached' if was_new else 'already attached'}.")

        self.step(2, "Donors")
        donors = {}
        everyone = []
        for name, group, gender, phone in [
            ("Suresh Lama", BloodGroup.O_NEG, "male", "+977-9841000101"),
            ("Anita Shrestha", BloodGroup.A_POS, "female", "+977-9841000102"),
            ("Bikash Gurung", BloodGroup.B_POS, "male", "+977-9841000103"),
            ("Rita Maharjan", BloodGroup.O_POS, "female", "+977-9841000104"),
            ("Prakash Adhikari", BloodGroup.AB_POS, "male", "+977-9841000105"),
            ("Ramesh Basnet", BloodGroup.O_NEG, "male", "+977-9841000107"),
            ("Sunita Karki", BloodGroup.A_POS, "female", "+977-9841000108"),
            ("Deepak Sharma", BloodGroup.O_POS, "male", "+977-9841000109"),
            ("Gita Poudel", BloodGroup.A_NEG, "female", "+977-9841000110"),
        ]:
            donor = Donor.objects.filter(full_name=name).first()
            if donor is None:
                donor = register_donor(
                    organization, actor,
                    full_name=name, blood_group=group, gender=gender,
                    phone=phone,
                )
            donors.setdefault(group, donor)
            everyone.append(donor)
        self.say(f"   {Donor.objects.count()} donors on the registry.")

        self.refused(
            "a donor with no phone number",
            lambda: register_donor(
                organization, actor, full_name="No Contact", phone="",
            ),
        )
        self.say("   A donor who cannot be contacted cannot be told about a "
                 "reactive result, and cannot be called when their group")
        self.say("   runs out.")

        self.step(3, "Collection, and the two floors that protect the donor")
        # A donor who has never given, so the refusal shown is the haemoglobin
        # and the weight rather than the ninety-day interval.
        walk_in = Donor.objects.filter(full_name="Sabina Tamang").first()
        if walk_in is None:
            walk_in = register_donor(
                organization, actor, full_name="Sabina Tamang",
                blood_group=BloodGroup.B_NEG, gender="female",
                phone="+977-9841000106",
            )
        self.refused(
            "a donation from somebody with haemoglobin of 10.2",
            lambda: collect_donation(
                organization, walk_in, facility, actor,
                haemoglobin=Decimal("10.2"), donor_weight_kg=Decimal("58"),
            ),
        )
        self.refused(
            "a 450ml donation from somebody weighing 41kg",
            lambda: collect_donation(
                organization, walk_in, facility, actor,
                haemoglobin=Decimal("13.4"), donor_weight_kg=Decimal("41"),
            ),
        )

        # Re-running must be safe. A donor deferred by an earlier run cannot
        # donate again — that is the rule working, not a problem to route
        # around — so the seed reuses their existing donation rather than
        # trying to collect a second one.
        donations = {}
        collected = []
        for donor in everyone:
            group = donor.blood_group
            existing = donor.donations.order_by("-collected_at").first()
            eligible, _ = donor.eligible_on(today)
            if existing and not eligible:
                donations.setdefault(group, existing)
                collected.append(existing)
                continue
            if not eligible:
                continue
            # Back-dated so that eligibility, expiry and the seven-day
            # expiring bucket all have something to say.
            fresh = collect_donation(
                organization, donor, facility, actor,
                haemoglobin=Decimal("14.2"), donor_weight_kg=Decimal("62"),
                at=now - timedelta(days=4),
            )
            donations.setdefault(group, fresh)
            collected.append(fresh)

        # A bank whose regulars are all inside their ninety days has nothing
        # on the shelf — which is true, and is exactly why banks recruit. The
        # seed recruits too, so that a second run has blood to work with
        # rather than quietly demonstrating nothing.
        wanted = [
            BloodGroup.O_NEG, BloodGroup.A_POS, BloodGroup.O_POS,
            BloodGroup.A_NEG, BloodGroup.B_POS,
        ]
        for group in wanted:
            if any(row.donor.blood_group == group for row in collected
                   if row.status != DonationStatus.DISCARDED
                   and not row.units.exists()):
                continue
            index = Donor.objects.count() + 1
            recruit = register_donor(
                organization, actor,
                full_name=f"New donor {index}",
                blood_group=group,
                gender="male" if index % 2 else "female",
                phone=f"+977-98420{index:05d}",
            )
            everyone.append(recruit)
            fresh = collect_donation(
                organization, recruit, facility, actor,
                haemoglobin=Decimal("14.6"), donor_weight_kg=Decimal("64"),
                at=now - timedelta(days=2),
            )
            donations.setdefault(group, fresh)
            collected.append(fresh)

        self.say(f"   {len(collected)} donations on file across "
                 f"{len(donations)} groups.")

        donor = donors[BloodGroup.O_NEG]
        donor.refresh_from_db()
        eligible, problems = donor.eligible_on(today)
        self.expect("can that donor give again today?", False, eligible)
        self.say(f"     {problems[0] if problems else ''}")

        self.step(4, "Two groupings, by two people")
        target = donations.get(BloodGroup.O_NEG)
        if target is None:
            self.say(self.style.WARNING("   No O− donation to group."))
            return

        from apps.bloodbank.services import confirmed_group

        if target.groupings.count() == 0:
            record_grouping(target, BloodGroup.O_NEG, first,
                            forward="anti-A −, anti-B −", reverse="A cells +")

        self.refused(
            "the same person grouping the same donation twice",
            lambda: record_grouping(target, BloodGroup.O_NEG, first),
        )
        self.say("   One person confirming their own reading is not a second "
                 "check; it is the same check twice with the same error in it.")

        # Only meaningful on a donation that still has one determination; on a
        # re-run it already has two, and pretending otherwise would be the
        # seed lying to make its own point.
        if target.groupings.count() == 1:
            group, problems = confirmed_group(target)
            self.expect("group with only one determination", "", group)
            self.say(f"     {problems[0]}")
            record_grouping(target, BloodGroup.O_NEG, second,
                            forward="anti-A −, anti-B −", reverse="A cells +")

        group, _ = confirmed_group(target)
        self.expect("group once two people agree", "O-", group)

        # A donation whose two readings disagree, to show what happens.
        disputed = donations.get(BloodGroup.B_POS)
        if disputed is None:
            self.say(self.style.WARNING("   No B+ donation for the disagreement demo."))
            return
        if disputed.groupings.count() == 0:
            record_grouping(disputed, BloodGroup.B_POS, first)
            record_grouping(disputed, BloodGroup.A_POS, second)
        group, problems = confirmed_group(disputed)
        self.expect("group when the two readings disagree", "", group)
        for line in problems:
            self.say(f"     {line}")
        self.say("   A disagreement is a finding that stops the donation, not "
                 "a vote.")

        for row in collected:
            if row.id in (target.id, disputed.id):
                continue
            if row.groupings.count() == 0:
                record_grouping(row, row.donor.blood_group, first)
                record_grouping(row, row.donor.blood_group, second)

        self.step(5, "Screening: missing is not negative")
        partial = donations.get(BloodGroup.A_POS)
        if partial is None:
            self.say(self.style.WARNING("   No A+ donation to screen."))
            return
        record_screening(
            partial,
            {"hiv": InfectionResult.NON_REACTIVE,
             "hbsag": InfectionResult.NON_REACTIVE},
            actor=first,
        )
        screening = partial.screening
        self.expect("infections still untested", 3, len(screening.untested))
        self.say(f"     {', '.join(screening.untested)}")
        self.expect("is that donation safe to release?", False,
                    screening.is_safe)
        for line in release_blockers(partial):
            self.say(f"     · {line}")
        self.say("   A unit nobody tested and a unit that failed are both "
                 "unsafe. Treating the first as the second's opposite is how")
        self.say("   an untested unit reaches a patient.")

        # Complete the panel for everything that will be used. The AB+
        # donation is held back for the reactive demonstration below.
        clean = {key: InfectionResult.NON_REACTIVE for key in SCREENING_KEYS}
        reactive_target = donations.get(BloodGroup.AB_POS)
        held_back = {disputed.id, getattr(reactive_target, "id", None)}
        for row in collected:
            if row.id in held_back:
                continue
            row.refresh_from_db()
            if row.status == DonationStatus.DISCARDED:
                continue
            record_screening(row, dict(clean), actor=first)
            verify_screening(row.screening, actor=second)

        self.refused(
            "the same person verifying their own screening",
            lambda: verify_screening(donations[BloodGroup.O_NEG].screening,
                                     actor=first),
        )

        self.step(6, "A reactive result stops the donor as well as the unit")
        reactive_donor = donors[BloodGroup.AB_POS]
        reactive_donation = reactive_target
        if reactive_donation is None:
            self.say("   (no donation on file for the AB+ donor)")
        elif reactive_donation.status != DonationStatus.DISCARDED:
            record_screening(
                reactive_donation,
                {**clean, "hbsag": InfectionResult.REACTIVE},
                actor=first,
            )
        if reactive_donation is not None:
            reactive_donation.refresh_from_db()
        reactive_donor.refresh_from_db()
        self.expect(
            "the donation", "discarded",
            reactive_donation.status if reactive_donation else "discarded",
        )
        self.expect("the donor", "permanent", reactive_donor.status)
        self.say(f"     {reactive_donor.deferral_reason}")
        self.say("   Discarding the unit without stopping the donor is how a "
                 "hepatitis-positive donor is invited back next month.")

        self.step(7, "Components, each with its own expiry")
        made = []
        for row in collected:
            row.refresh_from_db()
            if row.status == DonationStatus.DISCARDED or row.id == disputed.id:
                continue
            if row.units.exists():
                made.extend(row.units.all())
                continue
            made.extend(separate_components(
                row,
                [(ComponentType.RED_CELLS, 280),
                 (ComponentType.PLASMA, 200),
                 (ComponentType.PLATELETS, 50)],
                actor=actor,
                at=now - timedelta(days=4),
            ))
        by_component = {}
        for unit in made:
            by_component.setdefault(unit.component, unit)
        for component, unit in by_component.items():
            self.say(f"     {component:12} expires {unit.expires_on} "
                     f"({unit.days_to_expiry} days), stored "
                     f"{unit.storage_min_c} to {unit.storage_max_c} °C")
        self.say("   Platelets last five days and red cells thirty-five. One "
                 "expiry on the parent bag would be wrong for two of the")
        self.say("   three, and always in the dangerous direction for "
                 "platelets.")

        self.refused(
            "separating a donation whose groupings disagree",
            lambda: separate_components(
                disputed, [(ComponentType.RED_CELLS, 280)], actor=actor,
            ),
        )

        self.step(8, "Release: the one gate between a bag and a patient")
        blockers = release_blockers(disputed)
        self.say(f"   {disputed.donation_number}: {len(blockers)} blocker(s)")
        for line in blockers:
            self.say(f"     · {line}")
        self.say("   Every blocker at once, not the first one. A laboratory "
                 "told only the first problem fixes it and comes back.")

        released = 0
        for row in collected:
            if row.units.filter(status=UnitStatus.QUARANTINED).exists():
                try:
                    released += len(release_units(row, actor=actor))
                except BloodBankError:
                    pass
        self.say(f"   {released} units released onto the shelf.")

        self.step(9, "Compatibility, both ways round")
        patient = (
            Patient.objects.filter(merged_into__isnull=True)
            .exclude(first_name__startswith="Unknown")
            .first()
        )
        red_for_a_pos = RED_CELL_COMPATIBILITY["A+"]
        self.expect(
            "red cells an A+ patient may receive",
            "['O-', 'O+', 'A-', 'A+']", str(red_for_a_pos),
        )
        from apps.bloodbank.models import PLASMA_COMPATIBILITY
        self.expect(
            "plasma an A+ patient may receive",
            "['A-', 'A+', 'AB-', 'AB+']", str(PLASMA_COMPATIBILITY["A+"]),
        )
        self.say("   Opposite directions. AB plasma suits everyone and AB red "
                 "cells suit almost nobody, and one table used for both is")
        self.say("   the classic fatal shortcut.")

        available = compatible_units(facility, ComponentType.RED_CELLS, "A+")
        self.say(f"   {len(available)} red cell units on the shelf for an A+ "
                 f"patient: "
                 f"{', '.join(f'{u.unit_number} {u.blood_group}' for u in available[:4])}")

        self.step(10, "Cross-matching")
        request = request_blood(
            organization, patient, facility, ComponentType.RED_CELLS, 2,
            "Symptomatic anaemia, haemoglobin 6.4 g/dL",
            actor=actor, stated_group="A+", haemoglobin=Decimal("6.4"),
        )
        self.say(f"   {request.reference}: {request.units_requested} units of "
                 f"{request.component}.")

        b_unit = BloodUnit.objects.filter(
            blood_group=BloodGroup.O_POS,
            component=ComponentType.RED_CELLS,
            status=UnitStatus.AVAILABLE,
        ).first()
        if b_unit:
            self.refused(
                "cross-matching an O+ unit against an A− patient",
                lambda: cross_match(b_unit, patient, "A-", actor=first),
            )
            self.say("   Refused outright rather than recorded as "
                     "incompatible: entering it at all means the wrong unit")
            self.say("   was pulled, and the useful response is to check the "
                     "label, not to file a result.")

        if not available:
            self.say(self.style.WARNING("   No compatible units to match."))
            return
        unit = available[0]
        match = cross_match(
            unit, patient, "A+", actor=first, request=request,
            method="Column agglutination",
        )
        unit.refresh_from_db()
        self.expect("the unit's state after a compatible match",
                    "crossmatched", unit.status)
        self.say(f"   Valid until {match.valid_until:%d %b %H:%M} "
                 f"({(match.valid_until - now).days * 24 + (match.valid_until - now).seconds // 3600}h).")
        self.say("   A compatible cross-match from four days ago is not a "
                 "compatible cross-match: the patient may have been")
        self.say("   transfused since and developed antibodies.")

        self.step(11, "Issue refuses. It does not warn.")
        other = (
            Patient.objects.filter(merged_into__isnull=True)
            .exclude(id=patient.id)
            .exclude(first_name__startswith="Unknown")
            .first()
        )
        if other:
            self.refused(
                "issuing a cross-matched unit to a different patient",
                lambda: issue_unit(unit, other, actor=actor),
            )

        stale_unit = next(
            (u for u in available[1:] if u.status == UnitStatus.AVAILABLE), None,
        )
        if stale_unit:
            expired_match = cross_match(
                stale_unit, patient, "A+", actor=second,
                at=now - timedelta(hours=80),
            )
            self.refused(
                "issuing against a cross-match performed eighty hours ago",
                lambda: issue_unit(stale_unit, patient, actor=actor),
            )

        never_matched = BloodUnit.objects.filter(
            status=UnitStatus.AVAILABLE, component=ComponentType.PLASMA,
        ).first()
        if never_matched:
            self.say("   Blockers on a unit nobody has matched:")
            for line in issue_blockers(never_matched, patient):
                self.say(f"     · {line}")

        self.say("   `issue_unit` has no override parameter and will not get "
                 "one. Every other guard in this system can be overridden")
        self.say("   with a permission and a reason, because the alternative "
                 "is people working around it. Here the alternative is a")
        self.say("   death.")

        self.step(12, "The emergency path is a different function")
        # Whatever is left on the shelf. O negative red cells and AB plasma
        # are the two universal products; anything else is refused, and the
        # seed shows both halves with whatever the bank actually has.
        from apps.bloodbank.models import PLASMA_COMPONENTS

        # Red cells and plasma only. Platelets are matched on different
        # grounds again, and demonstrating a universal-donor rule on a
        # platelet unit would be teaching the wrong thing.
        available_now = list(BloodUnit.objects.filter(
            status=UnitStatus.AVAILABLE,
            component__in=(ComponentType.RED_CELLS, ComponentType.PLASMA),
            expires_on__gte=today,
        ))

        def universal_for(unit):
            return (
                {"AB+", "AB-"} if unit.component in PLASMA_COMPONENTS
                else {"O-"}
            )

        o_neg = next(
            (u for u in available_now if u.blood_group in universal_for(u)),
            None,
        )
        a_pos = next(
            (u for u in available_now if u.blood_group not in universal_for(u)),
            None,
        )
        if a_pos:
            self.refused(
                f"an uncross-matched {a_pos.blood_group} "
                f"{a_pos.get_component_display().lower()} unit in an emergency",
                lambda: issue_emergency(
                    a_pos, patient, actor=actor,
                    authorised_by="Dr Sunita Karki",
                    reason="Massive haemorrhage, no time to cross-match.",
                ),
            )
        if o_neg:
            self.refused(
                "an emergency issue with no named authoriser",
                lambda: issue_emergency(
                    o_neg, patient, actor=actor, authorised_by="", reason="",
                ),
            )
            issue_emergency(
                o_neg, patient, actor=actor,
                authorised_by="Dr Sunita Karki",
                reason="Massive obstetric haemorrhage; group unknown.",
            )
            o_neg.refresh_from_db()
            self.expect(
                f"the {o_neg.blood_group} unit after an authorised emergency "
                "issue", "issued", o_neg.status,
            )
            self.say("   A different function with a different name, so no "
                     "path through the ordinary issue can skip the check by")
            self.say("   passing an argument. It still refuses an expired "
                     "unit and a non-universal group.")

        if not o_neg and not a_pos:
            self.say("   Nothing left on the shelf to demonstrate with.")

        self.step(13, "Issuing properly, and the bedside check")
        issue_unit(unit, patient, actor=actor, issued_to="Ward 3")
        unit.refresh_from_db()
        self.expect("the unit", "issued", unit.status)

        self.refused(
            "a bedside check by one person entered twice",
            lambda: transfuse(
                unit, patient, actor=actor,
                checked_by_first="Kabita Rai",
                checked_by_second="Kabita Rai",
            ),
        )
        self.say("   The bedside check is the last barrier before a fatal "
                 "error. One person checking alone is not the check, and the")
        self.say("   database refuses the two names being the same.")

        transfusion = transfuse(
            unit, patient, actor=actor,
            checked_by_first="Kabita Rai",
            checked_by_second="Dipesh Thapa",
            request=request,
        )
        record_observation(
            transfusion, first, temperature="36.9", pulse="88",
            systolic="112", note="Fifteen minutes, no reaction.",
        )
        finish_transfusion(transfusion, actor=first, volume_ml=280)
        unit.refresh_from_db()
        self.expect("the unit after transfusion", "transfused", unit.status)
        request.refresh_from_db()
        self.expect("the request after one of two units",
                    "part_filled", request.status)

        self.step(14, "The cold chain has a clock")
        spare = BloodUnit.objects.filter(
            status=UnitStatus.AVAILABLE, component=ComponentType.RED_CELLS,
        ).first()
        if spare:
            reserve_unit(spare, patient, actor=actor, reason="Theatre list")
            spare.refresh_from_db()
            self.expect("a reserved unit", "reserved", spare.status)
            self.say("   Reserved is not cross-matched: off the available "
                     "pool for tomorrow's list, but untested against this")
            self.say("   patient and not issuable. Collapsing the two either "
                     "double-issues units or makes the bank look empty.")

            cross_match(spare, patient, "A+", actor=second)
            issue_unit(spare, patient, actor=actor)
            spare.refresh_from_db()
            spare.left_storage_at = now - timedelta(minutes=55)
            spare.save(update_fields=["left_storage_at"])
            self.refused(
                "returning a unit that has been out of the fridge for 55 "
                "minutes",
                lambda: return_unit(spare, actor=actor, reason="Not needed"),
            )
            spare.refresh_from_db()
            self.expect("that unit's state", "discarded", spare.status)
            self.say("   Beyond thirty minutes the cold chain is broken and "
                     "the unit is discarded, however fine it looks. Bacteria")
            self.say("   grow, and a rule without a clock is a rule that gets "
                     "ignored.")

        self.step(15, "A reaction, reported rather than noted")
        second_unit = compatible_units(
            facility, ComponentType.RED_CELLS, "A+",
        )
        if second_unit:
            reacted = second_unit[0]
            cross_match(reacted, patient, "A+", actor=first)
            issue_unit(reacted, patient, actor=actor)
            second_transfusion = transfuse(
                reacted, patient, actor=actor,
                checked_by_first="Dipesh Thapa",
                checked_by_second="Kabita Rai",
                request=request,
            )
            reaction = report_reaction(
                second_transfusion, "febrile", ReactionSeverity.MODERATE,
                "Temperature rose from 36.8 to 38.6 with rigors.",
                actor=first, minutes_in=25, stopped=True, volume_ml=90,
                treatment="Paracetamol, transfusion stopped, unit returned.",
            )
            second_transfusion.refresh_from_db()
            self.expect("the transfusion's outcome", "stopped",
                        second_transfusion.outcome)
            self.expect("volume actually given", 90,
                        second_transfusion.volume_given_ml)
            self.say("   A reaction twenty-five minutes in with the volume "
                     "given recorded. A reaction in the first fifteen minutes")
            self.say("   is haemolytic until proved otherwise, which is why "
                     "the minutes are the most diagnostic fact on the form.")

            self.refused(
                "a reaction type outside the reportable list",
                lambda: report_reaction(
                    second_transfusion, "felt_a_bit_odd",
                    ReactionSeverity.MILD, "Unwell.", actor=first,
                ),
            )

        self.step(16, "Traceability, both directions")
        back = look_back(donors[BloodGroup.O_NEG])
        self.say(f"   {back['donor']}: {back['donations']} donations, "
                 f"{back['units']} units, {back['recipients']} recipients.")
        for row in back["rows"][:4]:
            self.say(f"     {row['unit']} {row['component']:12} "
                     f"{row['status']:12} "
                     f"{row['patient'] or '—'}")
        self.say("   The question asked when a donor seroconverts. Without "
                 "the link the answer is that nobody knows, and the hospital")
        self.say("   has to contact everybody or nobody.")

        forward = trace_patient(patient)
        self.say(f"   {forward['patient']} received "
                 f"{len(forward['transfusions'])} units:")
        for row in forward["transfusions"][:4]:
            self.say(f"     {row['unit']} {row['group']:3} from donor "
                     f"{row['donor']} on {row['transfused_on']}"
                     f"{'  (reaction)' if row['reactions'] else ''}")

        self.step(17, "What is in the fridge")
        holdings = stock(facility)
        self.say(f"   {holdings['total']} units: {holdings['available']} "
                 f"available, {holdings['held']} held, "
                 f"{holdings['quarantined']} quarantined, "
                 f"{holdings['expiring_within_7_days']} expiring this week.")
        for component, groups in holdings["by_component"].items():
            summary = ", ".join(
                f"{group} {cell['available']}"
                + (f"(+{cell['held']} held)" if cell["held"] else "")
                for group, cell in sorted(groups.items())
            )
            self.say(f"     {component:12} {summary}")
        self.say("   Reported by group and component because the real problem "
                 "is never the total: forty O positive expiring on Thursday")
        self.say("   and no A negative is a crisis a single number hides.")

        self.step(18, "Expiry, and what was wasted")
        expired = expire_units(facility=facility)
        self.say(f"   {expired['expired']} units expired today.")
        again = expire_units(facility=facility)
        self.expect("running the expiry sweep twice", 0, again["expired"])
        self.say("   Selects on the date rather than a flag, so a second run "
                 "is a no-operation rather than a double count.")

        waste = wastage(facility=facility)
        self.say(f"   {waste['discarded']} discarded against "
                 f"{waste['issued']} issued — {waste['wastage_percent']}%.")
        for reason, count in waste["by_reason"].items():
            self.say(f"     {count:>3}  {reason}")
        self.say("   The reasons matter more than the total: expiry is a "
                 "stock problem, a broken cold chain is a process problem,")
        self.say("   and a reactive screen is the system working.")

        self.step(19, "Haemovigilance")
        vigilance = haemovigilance(facility=facility)
        self.say(f"   {vigilance['transfusions']} transfusions, "
                 f"{vigilance['reactions']} reactions "
                 f"({vigilance['reaction_rate_percent']}%).")
        self.say(f"   By type: {vigilance['by_type']}")
        self.say(f"   By severity: {vigilance['by_severity']}")
        self.say(f"   Clerical errors: {vigilance['clerical_errors']}")
        self.say("   Reported with the clerical-error count beside it, "
                 "because that is the one category that is entirely")
        self.say("   preventable and the one a blood bank is judged on.")

        self.step(20, "Who to call when a group runs out")
        for row in donor_call_list(facility, BloodGroup.O_NEG)[:5]:
            self.say(f"   {row['donor_number']}  {row['name'][:22]:22} "
                     f"{row['phone']:18} "
                     f"{'eligible now' if row['eligible_now'] else row['problems'][0][:60]}")
        self.say("   Ordered by when each becomes eligible, not by name: a "
                 "donor eligible next week is not the same as one eligible")
        self.say("   today.")

        self.say("")
        self.say(self.style.SUCCESS("Blood bank seed complete."))
