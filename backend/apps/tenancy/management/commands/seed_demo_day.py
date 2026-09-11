"""A believable *today*, kept up to date, for demonstrating on any date.

**Every dashboard in the demo read zero, and it was not the dashboards.** The
narrative seeds (`seed_emergency_demo`, `seed_pos_demo` and the rest) each tell
one story once — an unidentified arrival, a split-tender sale — and they tell
it on the day they were run. A week later the emergency department had two
arrivals in its whole history, the counter two sales, the queue four tokens,
and all of them dated some other day. A buyer shown a facility overview of
"0 in department · NPR 0 · nothing recorded" concludes the product is empty,
not that the demo data is stale.

This keeps the day that is actually happening, at the facilities where each
thing actually happens:

* **The emergency department**, at the hospital, which has no opening hours:
  arrivals through the night and the day, triaged, seen, discharged, the
  sickest still waiting for a bed, a few past their target, the occasional
  patient who gave up and went home.
* **The outpatient queue**, at the clinic: tokens through the morning, served
  in order, one with the doctor, the rest waiting.
* **The counter**, at the pharmacy: walk-in sales paid in the mix a Nepali
  pharmacy actually takes — cash, eSewa, Khalti, card.
* **The laboratory**: blood tests ordered for inpatients and outpatients,
  each moving through collection, receipt, results and verification on its
  own clock, with values that follow the patient — the dengue patient's
  platelets are low, the kidney injury's creatinine high, and the day's one
  critical potassium raises its alert exactly as a real one would.
* **The wards**, at the hospital: beds kept around four-fifths full, patients
  admitted from emergency and outpatients through the day, the ones due home
  going through all five discharge clearances in the afternoon, the beds they
  leave passing through housekeeping, a nursing round every four hours with
  observations a NEWS2 score can be read from — mostly stable, a few being
  watched, the occasional one deteriorating — and today's shift assigned to
  the duty nurse.

**It tops the day up rather than generating it.** Each run works out how much
of each thing a day this far along should have had — twelve arrivals by eight
in the morning, twenty-odd by the afternoon — adds only the shortfall, and
then moves every open case along to wherever its own clock says it should be
by now. So it can run every hour, or before every demo, and the board at
three o'clock shows a department that has been busy since midnight rather
than one frozen at whatever time somebody last ran a seed. Running it twice in
a row adds nothing, and nothing ever doubles.

**Every patient's day is decided by their own reference.** The wait before a
category-4 patient is seen, whether they are the one who gives up, how long
the consultation takes — each is drawn from a generator seeded by the arrival
or token itself. A run at nine and a run at eleven therefore agree about the
same patient: somebody due to be seen at 09:40 is still seen at 09:40, and was
not re-rolled into a different story in between.

**Everything goes through the service layer.** `arrive`, `triage`,
`mark_seen`, `dispose`, `issue_token` and `create_sale` enforce the same
entitlement, stock, FEFO and prescription rules they enforce in production, so
what a buyer sees is what the product would have done. The one liberty is
*time*: an event the generator places at 09:40 is stamped 09:40. `arrive` and
`triage` accept the timestamp as a field; the few services that stamp `now`
themselves are corrected immediately afterwards, and nothing else about the
record is touched.

It will not invent what the product guards against. Nobody is dispositioned
"admitted", because `dispose` rightly refuses an admission with no admission
behind it — the sickest patients stay in the department, which on a real day
is exactly where they would be. Nothing prescription-only is sold, because a
sale of it needs a prescription.
"""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max
from django.utils import timezone

from apps.common.exceptions import DomainError
from apps.identity.models import User
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: Presenting complaints by triage category. Plausible for a Nepali district
#: hospital's ED on an ordinary day, and deliberately unremarkable: the demo
#: should read as a normal shift, not as a disaster drill.
COMPLAINTS = {
    1: ["Unresponsive after a fall from height"],
    2: ["Central chest pain radiating to the left arm, sweating",
        "Severe shortness of breath, SpO2 84% on air",
        "Road traffic accident, suspected pelvic fracture"],
    3: ["Abdominal pain with vomiting since last night",
        "High fever and rigors for three days",
        "Laceration to the forearm, bleeding controlled",
        "Asthma, wheezing, speaking in short sentences",
        "Dizziness and palpitations",
        "Painful swollen knee after a fall",
        "Diabetic with blood sugar over 400"],
    4: ["Sore throat and fever",
        "Ankle sprain playing football",
        "Minor burn to the hand from cooking",
        "Ear pain for two days",
        "Rash for a week"],
    5: ["Request for a repeat prescription",
        "Dressing change"],
}

#: The category a complaint was written for — so a patient who arrived in the
#: last few minutes, before anyone triaged them, is triaged on a later run to
#: the category their complaint implies rather than to a fresh roll.
CATEGORY_OF = {
    complaint: category
    for category, complaints in COMPLAINTS.items()
    for complaint in complaints
}

#: How arrivals divide across categories. Roughly an ordinary ED day: very few
#: resuscitations, most patients urgent or standard.
ACUITY_WEIGHTS = [(1, 1), (2, 3), (3, 9), (4, 7), (5, 2)]

#: Minutes from arrival to being seen, per category, as (base, most jitter).
#:
#: Base plus the largest jitter stays inside each target in
#: `emergency.models.TARGET_MINUTES` (0, 10, 30, 60, 120), so a breach is the
#: deliberate slow patient below and not the ordinary one. The first version
#: started every category *at* its target and added jitter on top, which put
#: nearly every patient over it and showed a buyer a department breaching 72%.
SEEN_AFTER = {1: (0, 0), 2: (3, 5), 3: (12, 14), 4: (25, 25), 5: (50, 50)}

#: Tenders, weighted by how often each is used at a Nepali pharmacy counter.
TENDERS = [("cash", 5), ("esewa", 3), ("khalti", 2), ("card", 1)]

#: Why people are in each generated ward, and how many nights they stay.
WARD_CASES = {
    "MW": (["Community-acquired pneumonia", "Acute exacerbation of COPD",
            "Uncontrolled type 2 diabetes", "Acute gastroenteritis with dehydration",
            "Urinary tract infection with sepsis", "Heart failure, decompensated",
            "Enteric fever", "Dengue fever with warning signs"], (3, 7)),
    "SW": (["Acute appendicitis — post appendicectomy",
            "Cholecystitis — post laparoscopic cholecystectomy",
            "Fracture neck of femur — post hemiarthroplasty", "Inguinal hernia repair",
            "Diabetic foot ulcer — debridement", "Small bowel obstruction"], (2, 6)),
    "MAT": (["Normal vaginal delivery", "Lower segment caesarean section",
             "Pre-eclampsia, monitoring", "Hyperemesis gravidarum"], (1, 3)),
    "PAED": (["Bronchiolitis", "Acute gastroenteritis", "Febrile seizure",
              "Pneumonia", "Asthma exacerbation"], (2, 4)),
    "HDU": (["Diabetic ketoacidosis", "Post-operative monitoring after laparotomy",
             "Severe sepsis, vasopressors weaned", "Acute kidney injury"], (2, 5)),
}

#: What share of usable beds the wards run at. Nepali public and mid-sized
#: private hospitals commonly run at or over capacity; four-fifths leaves the
#: board with a few free beds to admit into, which is what a demo needs.
OCCUPANCY = 0.8

#: Consultants by ward. The medical ward's is the demo doctor, so their own
#: patients appear under "mine" when they sign in.
CONSULTANTS = {
    "SW": "Dr. Prakash Adhikari", "MAT": "Dr. Sunita Rai",
    "PAED": "Dr. Kiran Shakya", "HDU": "Dr. Ramesh Karki",
}

#: When the ward's nursing rounds fall, local hour.
ROUND_HOURS = (2, 6, 10, 14, 18, 22)


class Command(BaseCommand):
    help = "Bring the demo tenant's day up to now: ED, outpatient queue, counter."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        self.organization = organization
        self.now = timezone.now()
        local_now = timezone.localtime(self.now)
        self.today = local_now.date()
        self.midnight = timezone.make_aware(datetime.combine(self.today, time.min))
        # Seeded from the date, so the new arrivals a run adds are the same
        # whether it runs at five past or ten past.
        self.random = random.Random(self.today.toordinal())

        staff = {
            key: User.objects.filter(email=f"{key}@{slug}.test").first()
            for key in ("owner", "nurse", "doctor", "reception", "counter", "manager")
        }
        if staff["owner"] is None:
            raise CommandError("Run `seed_demo` first — the demo staff are missing.")
        owner = staff["owner"]

        with tenant_context(context_for_organization(organization)):
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"\nBringing {self.today} up to {local_now:%H:%M}")
            )
            # The register and the shelf first: a day generated from six
            # patients and one open-sale product puts the same six people
            # everywhere at once and rings up NPR 2 sales all day.
            call_command("seed_demo_population", slug=slug, stdout=self.stdout)

            self._deal_deck()
            self._emergency(organization, staff["nurse"] or owner, staff["doctor"] or owner)
            self._queue(organization, staff["reception"] or owner, staff["doctor"] or owner)
            self._counter(organization, staff["counter"] or owner)
            self._wards(organization, staff["reception"] or owner,
                        staff["nurse"] or owner, staff["doctor"] or owner)
            self._laboratory(organization, staff["doctor"] or owner,
                             staff["manager"] or owner, owner)

    # -- time --------------------------------------------------------------

    def _opening(self):
        """When the counter and the clinic opened today: seven in the morning.

        It used to fall back to midnight before eight, "so an early run has
        something to show" — which, run by the half-hourly scheduler at half
        past two, rang up pharmacy sales and issued outpatient tokens in the
        middle of the night. Before seven the counter and the clinic are
        closed, and `_target` says so by returning nothing.
        """
        return self.midnight + timedelta(hours=7)

    def _department_opening(self):
        """An emergency department has no opening hours.

        At eight in the morning the counter has been open an hour and the
        department has been open all night, and its board should show the
        night shift: the overnight RTA still waiting for a bed is the most
        realistic thing on it.
        """
        return self.midnight

    def _target(self, per_hour: float, low: int, high: int, start) -> int:
        """How many of something a day this far along should have had.

        Twenty-two sales in the first hour of trading is a queue out of the
        door; twenty-two by five in the afternoon is a quiet shop. Scale by
        hours elapsed, within bounds that keep an early demo populated.
        """
        hours = max(0.0, (self.now - start).total_seconds() / 3600)
        if hours <= 0:
            return 0  # not open yet
        # The floor applies once the day has had two hours; before that it
        # grows in, so ten past seven does not arrive with eight sales rung.
        floor = low if hours >= 2 else round(low * hours / 2)
        return max(floor, min(high, round(hours * per_hour)))

    def _spread(self, count: int, start) -> list:
        """`count` moments between `start` and a minute ago, oldest first."""
        span = max(timedelta(minutes=1), self.now - timedelta(minutes=1) - start)
        return [
            start + span * ((index + self.random.uniform(0.15, 0.85)) / count)
            for index in range(count)
        ]

    # -- people ------------------------------------------------------------

    def _deal_deck(self):
        """Patients who are not already somewhere today, shuffled once.

        Dealt from one deck so nobody is in a ward bed and the resuscitation
        bay and the outpatient queue all at once — and without
        today's patients, so a second run does not try to bring somebody into
        the department who is already lying in it.
        """
        from apps.emergency.models import Arrival, Disposition
        from apps.inpatient.models import IN_HOUSE_STATUSES, Admission
        from apps.patients.models import Patient
        from apps.scheduling.models import QueueToken

        busy = set(
            Admission.objects.filter(status__in=IN_HOUSE_STATUSES).values_list("patient_id", flat=True)
        ) | set(
            Arrival.objects.filter(arrived_at__gte=self.midnight).values_list("patient_id", flat=True)
        ) | set(
            Arrival.objects.filter(disposition=Disposition.PENDING).values_list("patient_id", flat=True)
        ) | set(
            QueueToken.objects.filter(queue_date=self.today).values_list("patient_id", flat=True)
        )
        deck = list(
            Patient.objects.filter(merged_into__isnull=True)
            .exclude(pk__in=busy)
            .order_by("mrn")
        )
        self.random.shuffle(deck)
        self._deck = deck

    def _patients(self, count: int) -> list:
        dealt, self._deck = self._deck[:count], self._deck[count:]
        if len(dealt) < count:
            self.stdout.write(f"    the register ran out: {len(dealt)} of {count}")
        return dealt

    def _facility(self, facility_type: str):
        from apps.organization.models import Facility

        return (
            Facility.objects.filter(facility_type=facility_type, status="active").first()
            or Facility.objects.filter(status="active").first()
        )

    # -- the emergency department -----------------------------------------

    def _emergency(self, organization, nurse, doctor) -> None:
        from apps.emergency.models import Arrival, ArrivalMode, Disposition
        from apps.emergency.services import EmergencyError, arrive

        facility = self._facility("hospital")
        opened = self._department_opening()
        today = Arrival.objects.filter(facility=facility, arrived_at__gte=opened)
        shortfall = self._target(1.3, 10, 28, opened) - today.count()
        self.stdout.write(f"\n  Emergency department — {facility.name}")

        added = 0
        if shortfall > 0:
            latest = today.aggregate(latest=Max("arrived_at"))["latest"]
            start = latest if latest and latest > opened else opened
            categories = self.random.choices(
                [c for c, _ in ACUITY_WEIGHTS], weights=[w for _, w in ACUITY_WEIGHTS],
                k=shortfall,
            )
            # One resuscitation a day at most, and never as the newest arrival:
            # a demo that opens on a cardiac arrest in progress is a drill.
            if today.filter(triage_category=1).exists() or 1 in categories[-2:]:
                categories = [3 if c == 1 else c for c in categories]
            for arrived_at, category, patient in zip(
                self._spread(shortfall, start), categories, self._patients(shortfall)
            ):
                try:
                    arrive(
                        organization=organization,
                        facility=facility,
                        presenting_complaint=self.random.choice(COMPLAINTS[category]),
                        actor=nurse,
                        patient=patient,
                        arrival_mode=(
                            ArrivalMode.AMBULANCE if category <= 2 else ArrivalMode.WALK_IN
                        ),
                        arrived_at=arrived_at,
                    )
                    added += 1
                except EmergencyError as problem:
                    self.stdout.write(f"    skipped: {problem}")

        moved = 0
        for arrival in today.filter(disposition=Disposition.PENDING).order_by("arrived_at"):
            moved += self._advance_arrival(arrival, nurse, doctor)

        board = today.filter(disposition=Disposition.PENDING).count()
        self.stdout.write(
            f"    {today.count()} today ({added} new), {moved} steps moved on, "
            f"{board} in the department"
        )

    def _advance_arrival(self, arrival, nurse, doctor) -> int:
        """Move one attendance to wherever its own clock says it is by now.

        Returns how many steps it took, so the report can say something.
        """
        from apps.emergency.models import Disposition
        from apps.emergency.services import dispose, mark_seen, triage

        rng = random.Random(arrival.reference)
        category = arrival.triage_category or CATEGORY_OF.get(arrival.presenting_complaint, 4)
        steps = 0

        # Drawn whether or not it is used, so every later draw for this
        # patient is the same on every run.
        triage_delay = 0 if category == 1 else rng.randint(2, 9)
        if arrival.triage_category is None:
            triaged_at = arrival.arrived_at + timedelta(minutes=triage_delay)
            if triaged_at > self.now:
                return steps
            triage(arrival, category, nurse, reason="Initial assessment", assessed_at=triaged_at)
            steps += 1

        base, jitter = SEEN_AFTER[category]
        wait = base + rng.randint(0, jitter)
        # A few standard patients run well past target — the breach counter
        # should read something, not a flattering zero — and some of those
        # give up and go home before anyone calls them.
        slow = category >= 4 and rng.random() < 0.35
        if slow:
            wait += rng.randint(60, 100)
        gives_up = slow and rng.random() < 0.3
        treatment = rng.randint(35, 90)

        if arrival.first_seen_at is None:
            if gives_up:
                left_at = arrival.arrived_at + timedelta(minutes=wait - 10)
                if left_at <= self.now:
                    dispose(arrival, Disposition.LWBS, nurse, notes="Not present when called twice.")
                    self._restamp_disposition(arrival, left_at)
                    steps += 1
                return steps
            seen_at = arrival.arrived_at + timedelta(minutes=wait)
            if seen_at > self.now:
                return steps
            mark_seen(arrival, doctor, at=seen_at)
            steps += 1

        # Discharged, for the minor cases, once treatment has run its course.
        # The sick ones stay: they are waiting for a bed.
        if category >= 3:
            closed_at = arrival.first_seen_at + timedelta(minutes=treatment)
            if closed_at <= self.now:
                dispose(arrival, Disposition.DISCHARGED, doctor, notes="Treated and discharged.")
                self._restamp_disposition(arrival, closed_at)
                steps += 1
        return steps

    def _restamp_disposition(self, arrival, at) -> None:
        """`dispose` stamps now; the day says when it happened."""
        from apps.emergency.models import Arrival
        from apps.encounters.models import Encounter

        Arrival.objects.filter(pk=arrival.pk).update(disposition_at=at)
        if arrival.encounter_id:
            Encounter.objects.filter(pk=arrival.encounter_id).update(ended_at=at)

    # -- the outpatient queue ----------------------------------------------

    def _queue(self, organization, reception, doctor) -> None:
        from apps.scheduling.models import QueueStatus, QueueToken
        from apps.scheduling.services import complete_service, issue_token, start_service

        facility = self._facility("clinic")
        opened = self._opening()
        today = QueueToken.objects.filter(facility=facility, queue_date=self.today)
        shortfall = self._target(5, 6, 36, opened) - today.count()
        self.stdout.write(f"\n  Outpatient queue — {facility.name}")

        if shortfall > 0:
            latest = today.aggregate(latest=Max("issued_at"))["latest"]
            start = latest if latest and latest > opened else opened
            for issued_at, patient in zip(self._spread(shortfall, start), self._patients(shortfall)):
                token = issue_token(
                    organization=organization, patient=patient,
                    facility=facility, actor=reception,
                )
                QueueToken.objects.filter(pk=token.pk).update(issued_at=issued_at)

        # Served in order, one at a time: a token's consultation starts when
        # the previous one ends, or when the patient has been checked in for
        # five minutes, whichever is later.
        cursor = opened
        for token in today.order_by("issued_at"):
            if token.status == QueueStatus.COMPLETED:
                cursor = max(cursor, token.completed_at or cursor)
                continue
            if token.status not in (QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.IN_SERVICE):
                continue
            rng = random.Random(str(token.uuid))
            begins = token.service_started_at or max(
                token.issued_at + timedelta(minutes=5), cursor
            )
            # Twelve to twenty minutes a consultation — slower than tokens are
            # issued, as every Nepali OPD is, so a queue builds through the
            # morning rather than the doctor keeping up with the door.
            ends = begins + timedelta(minutes=rng.randint(12, 20))
            if begins > self.now:
                break
            if token.status != QueueStatus.IN_SERVICE:
                start_service(token, actor=doctor)
            stamps = {"called_at": token.called_at or begins, "service_started_at": begins}
            if ends <= self.now:
                complete_service(token, actor=doctor)
                stamps["completed_at"] = ends
            QueueToken.objects.filter(pk=token.pk).update(**stamps)
            cursor = ends
            if ends > self.now:
                break  # with the doctor now; everyone after is waiting

        counts = {
            status: today.filter(status=status).count()
            for status in (QueueStatus.COMPLETED, QueueStatus.IN_SERVICE, QueueStatus.WAITING)
        }
        self.stdout.write(
            f"    {today.count()} tokens: {counts[QueueStatus.COMPLETED]} seen, "
            f"{counts[QueueStatus.IN_SERVICE]} with the doctor, "
            f"{counts[QueueStatus.WAITING]} waiting"
        )

    # -- the counter -------------------------------------------------------

    def _counter(self, organization, cashier) -> None:
        from apps.pharmacy.models import Product, StockLocation
        from apps.pharmacy.services import PharmacyError, stock_on_hand
        from apps.pos.models import CounterSession, Sale
        from apps.pos.services import PosError, create_sale, open_session

        facility = self._facility("pharmacy")
        location = StockLocation.objects.filter(facility=facility, is_dispensable=True).first()
        if location is None:
            self.stdout.write("\n  Counter — no dispensary here; run seed_pharmacy_demo.")
            return
        self.stdout.write(f"\n  Counter — {facility.name}")

        opened = self._opening()
        today = Sale.objects.filter(facility=facility, sold_at__gte=self.midnight)
        shortfall = self._target(4, 8, 44, opened) - today.count()
        if shortfall <= 0:
            self.stdout.write(f"    {today.count()} sales today; nothing to add")
            return

        counter = "COUNTER-1"
        session = CounterSession.objects.filter(
            facility=facility, counter=counter, status="open",
        ).first() or open_session(
            organization=organization, facility=facility, location=location,
            counter=counter, cashier=cashier, opening_float=Decimal("2000"),
        )

        products = [
            product
            for product in Product.objects.filter(is_active=True, requires_prescription=False)
            if stock_on_hand(product, location) >= Decimal("12")
        ]
        if not products:
            self.stdout.write("    no over-the-counter stock on the shelf; nothing sold")
            return

        latest = today.aggregate(latest=Max("sold_at"))["latest"]
        start = latest if latest and latest > opened else opened
        methods = [method for method, weight in TENDERS for _ in range(weight)]
        made = 0
        for sold_at in self._spread(shortfall, start):
            basket = self.random.sample(
                products, min(len(products), self.random.choice([1, 1, 2, 2, 3]))
            )
            method = self.random.choice(methods)
            payment = {"method": method}
            if method != "cash":
                payment["reference"] = f"{method.upper()}{self.random.randint(10**7, 10**8 - 1)}"
            try:
                # A tender with no amount settles the balance — the only way to
                # match a rupee-rounded total without guessing at it.
                sale = create_sale(
                    organization=organization,
                    session=session,
                    items=[
                        {"product": product, "quantity": self._counter_quantity(product)}
                        for product in basket
                    ],
                    actor=cashier,
                    customer_name="Walk-in customer",
                    payments=[payment],
                )
            except (PharmacyError, PosError) as problem:
                self.stdout.write(f"    skipped a sale: {problem}")
                continue
            Sale.objects.filter(pk=sale.pk).update(sold_at=sold_at)
            made += 1
        self.stdout.write(f"    {today.count()} sales today ({made} new)")

    def _counter_quantity(self, product) -> Decimal:
        """What somebody actually buys of this, in base units.

        Tablets go by the strip — a pack of ten is ten tablets in the ledger —
        and occasionally half of one; a bottle, a tube or a thermometer goes
        one at a time; sachets and masks by the handful.
        """
        pack = max(1, product.pack_size or 1)
        if product.base_unit in ("tablet", "capsule") and pack > 1:
            return Decimal(self.random.choice([pack, pack, pack, pack // 2 or 1, pack * 2]))
        if product.category == "consumable":
            return Decimal(self.random.choice([2, 5, 5, 10]))
        if product.base_unit == "sachet":
            return Decimal(self.random.choice([2, 3, 5]))
        return Decimal(1)

    # -- the wards -----------------------------------------------------------

    def _wards(self, organization, clerk, nurse, doctor) -> None:
        from apps.inpatient.models import IN_HOUSE_STATUSES, Admission, Bed, BedStatus, Ward
        from apps.tenancy.management.commands.seed_demo_population import GENERATED_WARDS

        hospital = self._facility("hospital")
        wards = list(Ward.objects.filter(facility=hospital, code__in=GENERATED_WARDS))
        if not wards:
            self.stdout.write("\n  Wards — none generated here; run seed_demo_population.")
            return
        self.stdout.write(f"\n  Wards — {hospital.name}")

        def in_house():
            return Admission.objects.filter(
                status__in=IN_HOUSE_STATUSES,
                bed_assignments__vacated_at__isnull=True,
                bed_assignments__ward__in=wards,
            ).distinct()

        home = self._discharge_due(in_house(), clerk, nurse, doctor)
        cleaned = self._housekeeping(wards)
        admitted = self._admit_to_target(organization, hospital, wards, clerk, doctor)
        rounds = self._rounds(in_house(), nurse)
        self._assign_shift(wards, nurse)

        beds = Bed.objects.filter(ward__in=wards, is_active=True)
        self.stdout.write(
            f"    {in_house().count()} in {beds.count()} beds · {admitted} admitted, "
            f"{home} home, {cleaned} back from cleaning, {rounds} observed this round · "
            f"{beds.filter(status=BedStatus.CLEANING).count()} being cleaned"
        )

    def _at(self, day, hour: int, minute: int = 0):
        return timezone.make_aware(datetime.combine(day, time(hour, 0))) + timedelta(minutes=minute)

    def _discharge_due(self, stays, clerk, nurse, doctor) -> int:
        """Everyone whose expected day home has come.

        On the day: the consultant says "home today" mid-morning, the ward
        signs its clearances, and the patient leaves in the afternoon once
        billing and records have signed theirs — the hours between are the
        discharge lounge every hospital has. A day overdue: they went home
        that afternoon, and the run that should have sent them simply was not
        there to see it.
        """
        from apps.inpatient.models import AdmissionStatus, Bed, BedAssignment, ClearanceKind
        from apps.inpatient.services import clear, discharge, initiate_discharge

        done = 0
        for stay in stays.filter(expected_discharge__lte=self.today).order_by("expected_discharge"):
            rng = random.Random(f"home:{stay.reference}")
            day = stay.expected_discharge
            decided = self._at(day, 9, rng.randint(15, 90))
            leaves = self._at(day, 13, rng.randint(0, 200))
            if decided > self.now:
                continue
            if stay.status == AdmissionStatus.ADMITTED:
                initiate_discharge(stay, actor=doctor, notes="Consultant: home today.")
            for kind in (ClearanceKind.CLINICAL, ClearanceKind.NURSING, ClearanceKind.PHARMACY):
                clear(stay, kind, actor=nurse)
            if leaves > self.now:
                continue
            # Billing signs off only once the account is actually settled —
            # the product refuses a discharge with charges uninvoiced or a
            # balance owed, and the first version of this generator, which
            # signed the clearance and walked on, was refused by it.
            try:
                self._settle(stay, clerk)
            except DomainError as problem:
                self.stdout.write(f"    {stay.reference} not settled: {problem}")
                continue
            for kind in (ClearanceKind.BILLING, ClearanceKind.RECORDS):
                clear(stay, kind, actor=clerk)
            assignment = stay.bed_assignments.filter(vacated_at__isnull=True).first()
            try:
                discharge(
                    stay, actor=doctor,
                    summary=f"{stay.admitting_diagnosis}: treated, clinically improved.",
                    advice="Complete the prescribed course. Return if symptoms recur.",
                    follow_up_on=day + timedelta(days=7),
                )
            except DomainError as problem:
                # Say which patient and why, and carry on with the rest of the
                # day: one refused discharge must not stop the ward's round.
                self.stdout.write(f"    {stay.reference} not discharged: {problem}")
                continue
            # `discharge` stamps now; the day says when they left.
            type(stay).objects.filter(pk=stay.pk).update(discharged_at=leaves)
            if assignment is not None:
                BedAssignment.objects.filter(pk=assignment.pk).update(vacated_at=leaves)
                Bed.objects.filter(pk=assignment.bed_id).update(status_changed_at=leaves)
            done += 1
        return done

    def _settle(self, stay, clerk) -> None:
        """What the billing desk does before a patient leaves: invoice every
        charge the stay has run up, and take the balance.

        Paid the way Nepali inpatient bills are — mostly cash or bank
        transfer, some by wallet — against the deposit that was asked for at
        admission. Nothing is waived or written off to make the discharge go
        through; if the service layer refuses, the patient stays.
        """
        from apps.billing.models import Charge, ChargeStatus, Invoice, InvoiceStatus
        from apps.billing.services import create_invoice, record_payment

        if Charge.objects.filter(encounter=stay.encounter, status=ChargeStatus.PENDING).exists():
            create_invoice(
                self.organization, stay.patient, stay.facility, actor=clerk, encounter=stay.encounter,
                notes=f"Final bill, {stay.reference}",
            )
        rng = random.Random(f"pay:{stay.reference}")
        for invoice in Invoice.objects.filter(encounter=stay.encounter).exclude(
            status__in=[InvoiceStatus.DRAFT, InvoiceStatus.PAID, InvoiceStatus.CANCELLED,
                        InvoiceStatus.CREDITED, InvoiceStatus.WRITTEN_OFF]
        ):
            if invoice.balance_due > 0:
                method = rng.choice(["cash", "cash", "bank_transfer", "esewa"])
                record_payment(
                    invoice, invoice.balance_due, method, actor=clerk,
                    reference="" if method == "cash" else f"{method.upper()}{rng.randint(10**7, 10**8 - 1)}",
                    notes="Settled at discharge",
                )

    def _housekeeping(self, wards) -> int:
        """Beds that have been cleaned since their patient left.

        Seventy-five minutes from vacated to ready — optimistic for a busy day,
        but the board should show turnaround, not a ward that never gets its
        beds back.
        """
        from apps.inpatient.models import Bed, BedStatus
        from apps.inpatient.services import set_bed_status

        ready = 0
        for bed in Bed.objects.filter(ward__in=wards, status=BedStatus.CLEANING):
            finished = bed.status_changed_at + timedelta(minutes=75)
            if finished <= self.now:
                set_bed_status(bed, BedStatus.AVAILABLE, reason="Cleaned and made up")
                Bed.objects.filter(pk=bed.pk).update(status_changed_at=finished)
                ready += 1
        return ready

    def _age(self, patient) -> int:
        if patient.date_of_birth:
            return (self.today - patient.date_of_birth).days // 365
        return patient.stated_age_years or 40

    def _fits(self, ward, bed, patient) -> bool:
        """Whether this patient belongs in this bed, as a bed manager would see it."""
        age = self._age(patient)
        if bed.gender_restriction in ("male", "female") and patient.gender != bed.gender_restriction:
            return False
        if ward.code == "PAED":
            return age < 14
        if ward.code == "MAT":
            return patient.gender == "female" and 18 <= age <= 42
        return age >= 14

    def _admit_to_target(self, organization, hospital, wards, clerk, doctor) -> int:
        from apps.inpatient.models import Bed, BedAssignment, BedStatus
        from apps.inpatient.services import InpatientError, admit

        usable = Bed.objects.filter(ward__in=wards, is_active=True).exclude(
            status__in=[BedStatus.MAINTENANCE, BedStatus.BLOCKED, BedStatus.RESERVED]
        )
        occupied = BedAssignment.objects.filter(ward__in=wards, vacated_at__isnull=True).count()
        shortfall = round(usable.count() * OCCUPANCY) - occupied
        if shortfall <= 0:
            return 0

        # An empty estate is being filled for the first time: those patients
        # came in over the past week. Otherwise they are today's admissions.
        first_fill = occupied == 0
        free = list(usable.filter(status=BedStatus.AVAILABLE).select_related("ward").order_by("code"))
        self.random.shuffle(free)
        made = 0
        for bed in free:
            if made >= shortfall:
                break
            ward = bed.ward
            patient = next((p for p in self._deck if self._fits(ward, bed, p)), None)
            if patient is None:
                continue
            self._deck.remove(patient)
            rng = random.Random(f"stay:{bed.code}:{patient.mrn}")
            diagnoses, (low, high) = WARD_CASES[ward.code]
            if first_fill:
                admitted_at = self.now - timedelta(hours=rng.randint(4, 24 * 6))
            else:
                # Admissions come up from emergency at any hour, so the last
                # six hours — not the clinic's opening, which at night lies
                # in the future.
                admitted_at = self._spread(1, max(self.midnight, self.now - timedelta(hours=6)))[0]
            expected = timezone.localtime(admitted_at).date() + timedelta(days=rng.randint(low, high))
            if expected < self.today:
                expected = self.today + timedelta(days=rng.randint(0, 2))
            try:
                stay = admit(
                    organization, patient, hospital, actor=clerk, bed=bed,
                    source=rng.choice(["emergency", "emergency", "opd", "referral"]),
                    consultant=doctor if ward.code == "MW" else None,
                    consultant_name=CONSULTANTS.get(ward.code, ""),
                    admitting_diagnosis=rng.choice(diagnoses),
                    expected_discharge=expected,
                    deposit_expected=Decimal("50000") if ward.code == "HDU" else Decimal("10000"),
                    admitted_at=admitted_at,
                    attendant_relation=rng.choice(
                        ["Spouse", "Son", "Daughter", "Mother", "Father", "Brother"]
                    ),
                )
            except InpatientError as problem:
                self.stdout.write(f"    skipped an admission: {problem}")
                continue
            # `assign_bed` and the encounter stamp now; the stay began earlier.
            BedAssignment.objects.filter(admission=stay).update(occupied_at=admitted_at)
            if stay.encounter_id:
                type(stay.encounter).objects.filter(pk=stay.encounter_id).update(
                    started_at=admitted_at
                )
            made += 1
        return made

    def _observations(self, stay, at) -> dict:
        """A set of observations for this patient at this moment.

        Each patient has a course, drawn once from their admission reference:
        most are stable, some are being watched, a few are deteriorating. The
        numbers jitter round to round the way real observations do, so a
        chart of them looks like a person rather than a constant.
        """
        course = random.Random(f"course:{stay.reference}").random()
        rng = random.Random(f"obs:{stay.reference}:{at:%Y%m%d%H}")
        if course < 0.78:      # stable — NEWS2 0 to 2
            obs = dict(
                temperature_c=Decimal(str(round(rng.uniform(36.4, 37.4), 1))),
                pulse_bpm=rng.randint(64, 90), respiratory_rate=rng.randint(13, 19),
                systolic_bp=rng.randint(112, 138), diastolic_bp=rng.randint(68, 86),
                spo2_percent=rng.randint(96, 99), pain_score=rng.randint(0, 3),
            )
        elif course < 0.94:    # watched — NEWS2 3 to 4
            obs = dict(
                temperature_c=Decimal(str(round(rng.uniform(38.1, 38.7), 1))),
                pulse_bpm=rng.randint(92, 105), respiratory_rate=rng.randint(21, 23),
                systolic_bp=rng.randint(104, 118), diastolic_bp=rng.randint(62, 74),
                spo2_percent=rng.randint(94, 95), pain_score=rng.randint(3, 6),
            )
        else:                  # deteriorating — NEWS2 5 and above
            obs = dict(
                temperature_c=Decimal(str(round(rng.uniform(38.8, 39.4), 1))),
                pulse_bpm=rng.randint(112, 128), respiratory_rate=rng.randint(24, 27),
                systolic_bp=rng.randint(92, 100), diastolic_bp=rng.randint(52, 60),
                spo2_percent=rng.randint(91, 93), pain_score=rng.randint(5, 8),
                on_room_air=False, oxygen_flow_lpm=Decimal("2"),
            )
        obs["intake_ml"] = rng.choice([250, 300, 400, 500])
        obs["output_ml"] = rng.choice([200, 250, 300, 350])
        return obs

    def _rounds(self, stays, nurse) -> int:
        """This round's observations, for everyone who has not had them.

        One round per run — the most recent that has fallen due. A ward whose
        last recorded observations are from three days ago is not being
        nursed, and the workspace would say so in every card.
        """
        from apps.encounters.models import VitalSigns
        from apps.inpatient.models import NursingRound
        from apps.inpatient.nursing_services import record_bedside_round

        due = [
            self._at(self.today, hour) for hour in ROUND_HOURS
            if self._at(self.today, hour) <= self.now
        ] or [self._at(self.today - timedelta(days=1), ROUND_HOURS[-1])]
        round_at = due[-1]

        done = 0
        for stay in stays.select_related("encounter"):
            if stay.admitted_at > round_at or not stay.encounter_id:
                continue
            last = (
                stay.rounds.order_by("-recorded_at")
                .values_list("recorded_at", flat=True).first()
            )
            if last and last >= round_at - timedelta(minutes=5):
                continue
            at = min(
                round_at + timedelta(minutes=random.Random(stay.reference).randint(0, 35)),
                self.now,
            )
            result = record_bedside_round(stay, nurse, **self._observations(stay, round_at))
            NursingRound.objects.filter(uuid=result["round_uuid"]).update(recorded_at=at)
            latest = (
                VitalSigns.objects.filter(encounter=stay.encounter)
                .order_by("-created_at").first()
            )
            if latest is not None:
                VitalSigns.objects.filter(pk=latest.pk).update(recorded_at=at)
            done += 1
        return done

    def _assign_shift(self, wards, nurse) -> None:
        """The duty nurse's patients for this shift: the women's bay of the
        medical ward, six beds, as a staffing sheet would give one nurse."""
        from apps.inpatient.nursing_models import NurseAssignment
        from apps.inpatient.nursing_services import assign_nurse, get_current_shift

        shift = get_current_shift(timezone.localtime(self.now))
        already = NurseAssignment.objects.filter(
            nurse_id=nurse.uuid, assigned_date=self.today, shift=shift, is_active=True,
            ward__in=wards,
        ).count()
        if already >= 6:
            return
        medical = next((ward for ward in wards if ward.code == "MW"), None)
        if medical is None:
            return
        beds = [
            bed for bed in medical.beds.filter(gender_restriction="female").order_by("code")
            if bed.current_assignment
        ][:6]
        for bed in beds:
            assign_nurse(
                ward=medical, nurse_id=nurse.uuid, nurse_name=nurse.full_name,
                assigned_date=self.today, shift=shift, bed=bed,
                notes="Staffing sheet", actor=nurse,
            )

    # -- the laboratory ------------------------------------------------------

    #: (test code, share of orders) — a full blood count is most of any lab's day.
    LAB_MIX = (("CBC", 5), ("RFT", 3), ("RBS", 2))

    def _laboratory(self, organization, doctor, technician, verifier) -> None:
        from apps.diagnostics.models import DiagnosticOrder, OrderPriority, TestDefinition
        from apps.diagnostics.services import DiagnosticsError, place_order
        from apps.inpatient.models import IN_HOUSE_STATUSES, Admission

        tests = {row.code: row for row in TestDefinition.objects.filter(code__in=[c for c, _ in self.LAB_MIX])}
        if len(tests) < len(self.LAB_MIX):
            self.stdout.write("\n  Laboratory — no test catalogue; run seed_diagnostics_demo.")
            return
        hospital = self._facility("hospital")
        self.stdout.write(f"\n  Laboratory — {hospital.name}")

        opened = self._opening()
        today = DiagnosticOrder.objects.filter(
            facility=hospital, ordered_at__gte=self.midnight, test__code__in=list(tests),
        )
        shortfall = self._target(2.5, 6, 28, opened) - today.count()
        if shortfall > 0:
            stays = list(
                Admission.objects.filter(facility=hospital, status__in=IN_HOUSE_STATUSES)
                .select_related("patient", "encounter")
                .order_by("reference")
            )
            self.random.shuffle(stays)
            already = set(today.values_list("patient_id", "test__code"))
            latest = today.aggregate(latest=Max("ordered_at"))["latest"]
            start = latest if latest and latest > opened else opened
            codes = [code for code, weight in self.LAB_MIX for _ in range(weight)]
            placed = 0
            for ordered_at, stay in zip(self._spread(shortfall, start), stays):
                code = self.random.choice(codes)
                if (stay.patient_id, code) in already:
                    continue
                stat = self._course(stay) == "deteriorating"
                try:
                    order = place_order(
                        organization, stay.patient, hospital, tests[code], actor=doctor,
                        encounter=stay.encounter,
                        priority=OrderPriority.STAT if stat else OrderPriority.ROUTINE,
                        clinical_indication=stay.admitting_diagnosis if stat else "",
                    )
                except DiagnosticsError as problem:
                    self.stdout.write(f"    skipped an order: {problem}")
                    continue
                turnaround = timedelta(minutes=tests[code].turnaround_minutes or 120)
                DiagnosticOrder.objects.filter(pk=order.pk).update(
                    ordered_at=ordered_at, due_at=ordered_at + turnaround,
                )
                placed += 1

        steps = 0
        for order in today.select_related("test", "patient", "encounter").order_by("ordered_at"):
            steps += self._advance_order(order, technician, verifier)

        counts = {}
        for status in today.values_list("status", flat=True):
            counts[status] = counts.get(status, 0) + 1
        self.stdout.write(
            f"    {today.count()} orders today, {steps} steps moved on · "
            + ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
        )

    def _course(self, stay) -> str:
        """The same course `_observations` gives this patient, named."""
        course = random.Random(f"course:{stay.reference}").random()
        return "stable" if course < 0.78 else "watched" if course < 0.94 else "deteriorating"

    def _advance_order(self, order, technician, verifier) -> int:
        from apps.diagnostics.models import DiagnosticOrder, OrderStatus
        from apps.diagnostics.services import (
            DiagnosticsError,
            collect_specimen,
            enter_results,
            receive_specimen,
            verify_order,
        )

        rng = random.Random(order.reference)
        fast = order.priority == "stat"
        collected = order.ordered_at + timedelta(minutes=rng.randint(5, 12) if fast else rng.randint(10, 35))
        received = collected + timedelta(minutes=rng.randint(5, 10) if fast else rng.randint(10, 25))
        resulted = received + timedelta(minutes=rng.randint(15, 30) if fast else rng.randint(25, 70))
        verified = resulted + timedelta(minutes=rng.randint(5, 15) if fast else rng.randint(10, 45))
        stamp = DiagnosticOrder.objects.filter(pk=order.pk)
        steps = 0
        try:
            if order.status == OrderStatus.ORDERED and collected <= self.now:
                collect_specimen(order, actor=technician)
                stamp.update(collected_at=collected)
                order.refresh_from_db()
                steps += 1
            if order.status == OrderStatus.COLLECTED and received <= self.now:
                receive_specimen(order, actor=technician)
                stamp.update(received_at=received)
                order.refresh_from_db()
                steps += 1
            if order.status == OrderStatus.RECEIVED and resulted <= self.now:
                enter_results(order, self._values(order, rng), actor=technician)
                stamp.update(resulted_at=resulted)
                order.refresh_from_db()
                steps += 1
            if order.status == OrderStatus.RESULTED and verified <= self.now:
                verify_order(order, actor=verifier)
                stamp.update(verified_at=verified, released_at=verified)
                steps += 1
        except DiagnosticsError as problem:
            self.stdout.write(f"    {order.reference}: {problem}")
        return steps

    def _values(self, order, rng) -> list:
        """Results that follow the patient.

        Normal for most. The admission's diagnosis moves the analyte it would
        move — platelets in dengue, creatinine in kidney injury, glucose in the
        diabetic — and a deteriorating patient's white count rises. One
        deteriorating patient's renal panel carries a potassium over the
        critical line, which raises its alert through the same path a real
        one takes.
        """
        from apps.inpatient.models import Admission

        stay = Admission.objects.filter(encounter=order.encounter).first() if order.encounter_id else None
        diagnosis = (stay.admitting_diagnosis if stay else "").lower()
        course = self._course(stay) if stay else "stable"
        female = order.patient.gender == "female"

        def num(low, high, places=1):
            return f"{rng.uniform(low, high):.{places}f}"

        code = order.test.code
        if code == "CBC":
            hb = num(10.0, 11.2) if course == "watched" and female else (
                num(11.8, 14.6) if female else num(13.4, 16.2))
            wbc = num(17, 22) if course == "deteriorating" else num(12, 15) if course == "watched" else num(4.8, 9.8)
            plt = num(45, 90, 0) if "dengue" in diagnosis else num(170, 360, 0)
            return [{"analyte_code": "HB", "value": hb}, {"analyte_code": "WBC", "value": wbc},
                    {"analyte_code": "PLT", "value": plt}]
        if code == "RFT":
            kidney = "kidney" in diagnosis or "sepsis" in diagnosis
            potassium = "6.8" if course == "deteriorating" and rng.random() < 0.5 else num(3.7, 4.9)
            return [
                {"analyte_code": "NA", "value": num(133, 143, 0)},
                {"analyte_code": "K", "value": potassium},
                {"analyte_code": "CREAT", "value": num(240, 320, 0) if kidney else num(55, 98, 0)},
                {"analyte_code": "UREA", "value": num(14, 22) if kidney else num(3.0, 7.2)},
            ]
        glucose = num(14, 19) if "diabet" in diagnosis or "ketoacidosis" in diagnosis else num(4.8, 7.6)
        return [{"value": glucose}]
