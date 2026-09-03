"""A year of claims, narrated.

Three payers that behave differently on purpose — an insurer, a TPA and the
Health Insurance Board — and a set of claims that go the way claims actually
go: approved, cut, queried, rejected, appealed, settled late and written off.

The seed runs the real service layer and prints what it expects beside what it
got. It contradicts itself out loud when the arithmetic is wrong.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceStatus
from apps.identity.models import User
from apps.insurance.models import (
    Claim,
    ClaimStatus,
    Payer,
    PayerKind,
    Policy,
    PolicyStatus,
    PreAuthStatus,
    PreAuthorisation,
    SchemePackage,
)
from apps.insurance.services import (
    InsuranceError,
    NotCovered,
    appeal_claim,
    check_eligibility,
    claims_ageing,
    create_claim,
    deduction_analysis,
    estimate,
    expiring_preauthorisations,
    package_margin,
    package_rate,
    payer_performance,
    preauth_warnings,
    rebuild_utilisation,
    record_preauth_response,
    record_response,
    request_preauthorisation,
    settle_claim,
    submission_deadline,
    submit_claim,
    write_off_claim,
)
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Seed payers, policies, pre-authorisations and a year of claims."

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

    def run(self, organization):
        actor = User.objects.filter(email="owner@manakamana.test").first()
        facility = Facility.objects.filter(facility_type="hospital").first()
        today = timezone.localdate()

        self.step(1, "The module has to be bought")
        # Claims are an add-on, not part of the Professional plan. A hospital
        # that starts dealing with insurers subscribes to it, and the seed
        # does the same rather than reaching around the entitlement engine —
        # which would make the fail-closed check untested in the one place it
        # is easiest to test.
        from apps.catalog.models import AddOn
        from apps.subscriptions.models import Subscription, SubscriptionAddOn

        subscription = Subscription.objects.filter(
            organization=organization, status="active",
        ).first()
        addon = AddOn.objects.filter(code="module_insurance").first()
        if subscription and addon:
            link, was_new = SubscriptionAddOn.objects.get_or_create(
                subscription=subscription, addon=addon,
                defaults={"quantity": 1, "unit_price": addon.unit_price,
                          "source_reference": "seed_insurance_demo"},
            )
            self.say(f"   {addon.name} "
                     f"{'attached' if was_new else 'already attached'} at "
                     f"Rs {link.unit_price}/month.")
        else:
            self.say(self.style.WARNING(
                "   No active subscription or no insurance add-on in the "
                "catalogue — run seed_catalog first."
            ))
            return

        self.step(2, "Three payers that behave differently")
        insurer, _ = Payer.objects.get_or_create(
            code="SHIKHAR",
            defaults={
                "name": "Shikhar Insurance",
                "kind": PayerKind.INSURER,
                "submission_window_days": 90,
                "settlement_days": 45,
                "requires_preauthorisation": True,
                "preauthorisation_threshold": Decimal("25000.00"),
                "contact_phone": "+977-1-4444555",
            },
        )
        tpa, _ = Payer.objects.get_or_create(
            code="MEDISAVE",
            defaults={
                "name": "MediSave TPA",
                "kind": PayerKind.TPA,
                "administers_for": insurer,
                "submission_window_days": 30,
                "settlement_days": 60,
                "requires_preauthorisation": True,
                "preauthorisation_threshold": Decimal("10000.00"),
            },
        )
        board, _ = Payer.objects.get_or_create(
            code="HIB",
            defaults={
                "name": "Health Insurance Board",
                "name_nepali": "स्वास्थ्य बीमा बोर्ड",
                "kind": PayerKind.GOVERNMENT,
                "submission_window_days": 15,
                "settlement_days": 90,
                "requires_preauthorisation": False,
            },
        )
        for payer in (insurer, tpa, board):
            self.say(f"   {payer.name} ({payer.get_kind_display()}): "
                     f"{payer.submission_window_days} days to submit, "
                     f"{payer.settlement_days} to pay.")
        self.say("   A TPA administers somebody else's risk and is the party "
                 "the hospital actually deals with; the Board pays fixed")
        self.say("   packages whatever the treatment cost. One 'insurance "
                 "company' model with optional fields would have three")
        self.say("   unreachable branches.")

        self.step(3, "Policies, and the date that matters")
        patients = list(
            Patient.objects.filter(merged_into__isnull=True).order_by("id")[:6]
        )
        if len(patients) < 4:
            self.say(self.style.WARNING("   Not enough patients seeded."))
            return

        current, _ = Policy.objects.get_or_create(
            payer=insurer,
            policy_number="SHK-2026-88412",
            patient=patients[0],
            defaults={
                "valid_from": today - timedelta(days=200),
                "valid_to": today + timedelta(days=165),
                "sum_insured": Decimal("500000.00"),
                "deductible": Decimal("5000.00"),
                "co_payment_percent": Decimal("10.00"),
                "sub_limits": {"room": 4000, "icu": 12000},
                "relationship": "self",
            },
        )
        # A policy that has since lapsed. The whole point of the next step.
        lapsed, _ = Policy.objects.get_or_create(
            payer=tpa,
            policy_number="MED-2025-01193",
            patient=patients[1],
            defaults={
                "valid_from": today - timedelta(days=400),
                "valid_to": today - timedelta(days=35),
                "sum_insured": Decimal("300000.00"),
                "co_payment_percent": Decimal("20.00"),
                "status": PolicyStatus.LAPSED,
                "relationship": "spouse",
                "principal_name": "Bishnu Prasad Sharma",
            },
        )
        scheme, _ = Policy.objects.get_or_create(
            payer=board,
            policy_number="HIB-3-04-118276",
            patient=patients[2],
            defaults={
                "valid_from": today - timedelta(days=120),
                "valid_to": today + timedelta(days=245),
                "sum_insured": Decimal("100000.00"),
                "relationship": "self",
                "card_number": "118276",
            },
        )
        waiting, _ = Policy.objects.get_or_create(
            payer=insurer,
            policy_number="SHK-2026-90551",
            patient=patients[3],
            defaults={
                "valid_from": today - timedelta(days=40),
                "valid_to": today + timedelta(days=325),
                "sum_insured": Decimal("200000.00"),
                "waiting_period_until": today + timedelta(days=50),
                "exclusions": ["Pre-existing diabetes", "Maternity"],
                "relationship": "self",
            },
        )
        self.say(f"   {Policy.objects.count()} policies across "
                 f"{Payer.objects.count()} payers.")

        self.step(4, "Cover is checked on the date of service, not today")
        service_date = today - timedelta(days=60)
        today_answer = check_eligibility(lapsed.patient)
        then_answer = check_eligibility(lapsed.patient, on_date=service_date)
        self.expect(
            f"is {lapsed.patient.full_name} covered today?",
            False, today_answer["any_eligible"],
        )
        self.expect(
            f"were they covered on {service_date}?",
            True, then_answer["any_eligible"],
        )
        for row in today_answer["policies"]:
            for problem in row["problems"]:
                self.say(f"     today: {problem}")
        self.say("   The policy lapsed 35 days ago. It did not lapse before "
                 "the admission sixty days ago, and a system that asks")
        self.say("   'is this active' answers the wrong question on every "
                 "claim submitted late.")

        waiting_answer = check_eligibility(waiting.patient)
        self.say(f"   {waiting.patient.full_name}: "
                 f"{waiting_answer['policies'][0]['problems']}")

        self.step(5, "What the patient will owe, before the treatment")
        quote = estimate(
            current,
            Decimal("120000.00"),
            {"room": 28000, "icu": 36000, "investigation": 22000},
        )
        self.say(f"   Billed Rs {quote['billed']}: the payer covers "
                 f"Rs {quote['payer_pays']}, the patient Rs "
                 f"{quote['patient_pays']}.")
        for reduction in quote["reductions"]:
            self.say(f"     −Rs {reduction['amount']:>10}  "
                     f"{reduction['reason']}: {reduction['detail']}")
        self.expect(
            "does the split add back to the bill",
            quote["billed"],
            quote["payer_pays"] + quote["patient_pays"],
        )
        self.say("   Applied in the order a payer applies them: sub-limits, "
                 "then deductible, then co-payment, then the remaining sum")
        self.say("   insured. A co-payment taken before the deductible gives a "
                 "different and smaller number, and the patient will have")
        self.say("   been told the wrong one.")

        self.step(6, "Pre-authorisation, and what it is worth")
        request = PreAuthorisation.objects.filter(
            policy=current, planned_treatment="Laparoscopic cholecystectomy",
        ).first()
        request = request or request_preauthorisation(
            organization, current, facility,
            treatment="Laparoscopic cholecystectomy",
            amount=Decimal("95000.00"),
            actor=actor,
            diagnosis="Symptomatic gallstones",
            diagnosis_code="K80.2",
            planned_on=today + timedelta(days=10),
            estimated_days=3,
        )
        self.say(f"   {request.reference}: asked for Rs "
                 f"{request.estimated_amount}.")

        if request.status == PreAuthStatus.REQUESTED:
            record_preauth_response(
                request, approved=True, actor=actor,
                approved_amount=Decimal("62000.00"),
                payer_reference="SHK/PA/2026/7741",
                valid_until=today + timedelta(days=5),
                conditions="Package rate applies. Consumables excluded.",
            )
        self.expect(
            "approving less than was asked gives",
            "partially_approved", request.status,
        )
        self.say("   Not 'approved'. A hospital proceeding on a 62,000 "
                 "approval against a 95,000 estimate is carrying 33,000 of")
        self.say("   risk, and the word 'approved' does not say that.")

        for warning in preauth_warnings(request, spent_so_far=Decimal("78000")):
            self.say(f"     ! {warning}")
        self.say("   Produced before the operation, not after the claim is "
                 "cut. Both failures are entirely predictable a week ahead.")

        self.step(7, "Building claims from real invoices")
        # Only invoices with a patient: a counter sale has nobody for an
        # insurer to check a policy against, and the service refuses it.
        invoices = list(
            Invoice.objects.filter(
                status__in=(
                    InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID,
                    InvoiceStatus.PAID,
                ),
                is_credit_note=False,
                patient__isnull=False,
            ).select_related("patient", "facility").order_by("-issued_at")[:8]
        )
        if not invoices:
            self.say(self.style.WARNING(
                "   No issued invoices with a patient to claim for."
            ))
            return

        made = []
        payers = [insurer, board]
        for index, invoice in enumerate(invoices):
            # The policy must belong to the invoice's own patient. Anything
            # else is one patient's treatment billed to another's cover.
            # Alternating payers on purpose. A patient may hold cover with
            # more than one, and the scheme claims are needed to measure the
            # package margin — which behaves quite differently from a policy.
            payer = payers[index % len(payers)]
            policy = Policy.objects.filter(
                patient=invoice.patient, payer=payer,
            ).first()
            if policy is None:
                policy = Policy.objects.create(
                    payer=payer,
                    policy_number=f"{payer.code}-AUTO-{invoice.patient_id:05d}",
                    patient=invoice.patient,
                    valid_from=today - timedelta(days=300),
                    valid_to=today + timedelta(days=65),
                    sum_insured=Decimal("400000.00"),
                    co_payment_percent=(
                        Decimal("0.00") if payer.is_scheme else Decimal("10.00")
                    ),
                    relationship="self",
                )
            existing = Claim.objects.filter(
                invoice=invoice, payer=policy.payer,
            ).first()
            if existing:
                made.append(existing)
                continue
            try:
                made.append(create_claim(
                    organization, invoice, policy, actor=actor,
                    diagnosis="Acute cholecystitis",
                    diagnosis_code="K81.0",
                    service_date=invoice.issued_at.date(),
                ))
            except (InsuranceError, NotCovered) as error:
                self.say(f"     {invoice.number}: {error}")
        self.say(f"   {len(made)} claims built from {len(invoices)} invoices.")
        if not made:
            return

        first = made[0]
        self.say(f"   {first.reference}: Rs {first.claimed_amount} across "
                 f"{first.lines.count()} lines, patient liability "
                 f"Rs {first.patient_liability}.")
        self.say("   The lines are copied, not referenced. The invoice is a "
                 "statutory document that cannot change; the claim is a")
        self.say("   negotiation, and the payer's decision has to live "
                 "somewhere that is allowed to change.")

        self.step(8, "A second claim on the same invoice is refused")
        try:
            create_claim(organization, first.invoice, first.policy, actor=actor)
            self.say("   <-- DISAGREES: a duplicate claim was accepted")
        except InsuranceError as error:
            self.say(f"   Refused: {error}")
        self.say("   Payers reject duplicates and some penalise them. The "
                 "constraint is on (invoice, payer), so it holds however the")
        self.say("   claim is created.")

        self.step(9, "The submission deadline")
        deadline = submission_deadline(first)
        self.say(f"   {first.payer.name} allows "
                 f"{deadline['window_days']} days from "
                 f"{first.service_date}; that closes {deadline['deadline']}, "
                 f"{deadline['days_left']} days from now.")

        # A claim deliberately older than its payer's window.
        stale = Claim.objects.filter(
            payer=board, status=ClaimStatus.DRAFT,
        ).first()
        if stale:
            stale.service_date = today - timedelta(days=40)
            stale.save(update_fields=["service_date"])
            try:
                submit_claim(stale, actor=actor)
                self.say("   <-- DISAGREES: a late claim was accepted")
            except InsuranceError as error:
                self.say(f"   Refused: {error}")
            self.say("   A refusal rather than a warning. A claim submitted "
                     "past the window is not a claim; it is a rejection with")
            self.say("   extra steps, and the hospital would believe it is "
                     "owed money it is not.")

        self.step(10, "Submitting, and the pre-authorisation rule")
        submitted = []
        for claim in made:
            if claim.status != ClaimStatus.DRAFT:
                submitted.append(claim)
                continue
            if claim.id == getattr(stale, "id", None):
                continue
            needs = (
                claim.payer.requires_preauthorisation
                and claim.claimed_amount > claim.payer.preauthorisation_threshold
            )
            if needs and claim.preauthorisation is None:
                claim.preauthorisation = request
                claim.save(update_fields=["preauthorisation"])
            try:
                submitted.append(submit_claim(
                    claim, actor=actor,
                    payer_reference=f"{claim.payer.code}/2026/{claim.id:05d}",
                ))
            except InsuranceError as error:
                self.say(f"     {claim.reference}: {error}")
        self.say(f"   {len(submitted)} claims submitted.")

        self.step(11, "What the payers did about them")
        outcomes = [
            ("full", "Approved in full"),
            ("cut", "Cut, with reasons"),
            ("query", "Queried"),
            ("reject", "Rejected"),
        ]
        for index, claim in enumerate(submitted[:6]):
            if claim.status != ClaimStatus.SUBMITTED:
                continue
            kind = outcomes[index % len(outcomes)][0]

            if kind == "full":
                record_response(claim, actor=actor)
            elif kind == "cut":
                lines = list(claim.lines.all())
                deductions = []
                for line in lines[:2]:
                    deductions.append({
                        "line": line,
                        "amount": (line.claimed_amount * Decimal("0.25")).quantize(
                            Decimal("0.01")
                        ),
                        "reason": (
                            "package_inclusive" if line.category == "drug"
                            else "above_sub_limit"
                        ),
                        "notes": "Above the agreed room rate.",
                    })
                record_response(claim, actor=actor, deductions=deductions)
            elif kind == "query":
                from apps.insurance.services import raise_query
                raise_query(
                    claim,
                    "Discharge summary and operation notes not attached.",
                    actor=actor,
                )
            else:
                record_response(
                    claim, actor=actor, approved_amount=Decimal("0"),
                    rejection_reason=(
                        "Treatment not covered: condition within the "
                        "waiting period."
                    ),
                )

        for claim in submitted[:6]:
            claim.refresh_from_db()
            self.say(f"     {claim.reference}  {claim.status:20} "
                     f"claimed {claim.claimed_amount:>10} "
                     f"approved {claim.approved_amount:>10} "
                     f"deducted {claim.deducted_amount:>8}")

        self.step(12, "A deduction with no reason is refused")
        candidate = next(
            (c for c in submitted if c.status == ClaimStatus.SUBMITTED), None,
        )
        if candidate:
            line = candidate.lines.first()
            try:
                record_response(candidate, actor=actor, deductions=[
                    {"line": line, "amount": Decimal("500.00"), "reason": ""},
                ])
                self.say("   <-- DISAGREES: a reasonless deduction was accepted")
            except InsuranceError as error:
                self.say(f"   Refused: {str(error)[:150]}…")
            self.say("   'Rs 500 deducted' is not actionable. 'Rs 500 "
                     "deducted: consumables not covered' is a policy the")
            self.say("   hospital can change.")

        self.step(13, "Appealing, and settling")
        cut = next(
            (c for c in submitted
             if c.status == ClaimStatus.PARTIALLY_APPROVED), None,
        )
        if cut:
            appeal_claim(
                cut,
                "Room rate was pre-agreed in the tariff dated 12 Shrawan.",
                actor=actor,
            )
            self.expect("the claim's state after appealing", "appealed",
                        cut.status)
            self.say("   Its own state, so the appeal rate is countable. A "
                     "hospital that never appeals is one whose deductions are")
            self.say("   never tested.")

        approved = [c for c in submitted if c.status == ClaimStatus.APPROVED]
        for claim in approved[:2]:
            half = (claim.approved_amount / 2).quantize(Decimal("0.01"))
            settle_claim(claim, half, actor=actor,
                         payment_reference="NABIL/TT/44192")
            claim.refresh_from_db()
            self.expect(
                f"{claim.reference} after a part settlement",
                "approved", claim.status,
            )
            settle_claim(claim, claim.approved_amount - claim.settled_amount,
                         actor=actor, payment_reference="NABIL/TT/44880")
            claim.refresh_from_db()
            self.expect(f"{claim.reference} once whole", "settled", claim.status)

        if approved:
            try:
                settle_claim(approved[0], Decimal("1.00"), actor=actor)
                self.say("   <-- DISAGREES: over-settlement was accepted")
            except InsuranceError as error:
                self.say(f"   Over-settling refused: {str(error)[:120]}…")

        self.step(14, "The policy's utilisation is a cache, not a counter")
        rebuilt = rebuild_utilisation(current)
        by_hand = sum(
            (c.approved_amount for c in current.claims.filter(
                status__in=(
                    ClaimStatus.APPROVED, ClaimStatus.PARTIALLY_APPROVED,
                    ClaimStatus.SETTLED,
                )
            )),
            Decimal("0.00"),
        )
        self.expect("utilisation rebuilt from the claims", by_hand, rebuilt)
        self.say(f"   Rs {rebuilt} of the Rs {current.sum_insured} sum "
                 f"insured used; Rs {current.remaining} left.")
        self.say("   Rebuilt rather than incremented, so a corrected claim "
                 "cannot leave it drifting.")

        self.step(15, "The government scheme pays a package, not a bill")
        package, _ = SchemePackage.objects.get_or_create(
            payer=board, code="HIB-SURG-014",
            effective_from=today - timedelta(days=300),
            defaults={
                "name": "Cholecystectomy, laparoscopic",
                "category": "General surgery",
                "package_amount": Decimal("42000.00"),
                "includes": "Theatre, anaesthesia, three bed-days, medicines.",
                "excludes": "Implants, ICU beyond one day.",
            },
        )
        rate = package_rate(board, "HIB-SURG-014")
        scheme_claim = next(
            (c for c in made if c.payer_id == board.id), None,
        )
        if scheme_claim:
            margin = package_margin(scheme_claim, rate)
            self.say(f"   {margin['package_name']}: billed Rs "
                     f"{margin['billed']}, package pays Rs "
                     f"{margin['package_amount']}, margin Rs "
                     f"{margin['margin']} ({margin['margin_percent']}%).")
            self.say(f"   Loss-making: {margin['loss_making']}")
            self.say("   The number a scheme hospital lives or dies by, and "
                     "one no insurance-shaped model produces: the package")
            self.say("   pays a fixed amount whatever happened.")

        self.step(16, "Writing one off")
        rejected = next(
            (c for c in submitted if c.status == ClaimStatus.REJECTED), None,
        )
        if rejected:
            write_off_claim(
                rejected,
                "Appeal refused twice; the amount is below the cost of "
                "pursuing it.",
                actor=actor,
            )
            self.expect("written off", "written_off", rejected.status)
            self.say("   An explicit outcome. A claim quietly abandoned is "
                     "revenue nobody records losing, and the annual write-off")
            self.say("   per payer is what decides whether to keep the "
                     "contract.")

        self.step(17, "What is owed, and by whom")
        ageing = claims_ageing()
        self.say(f"   Rs {ageing['total']} outstanding across "
                 f"{len(ageing['claims'])} claims, "
                 f"Rs {ageing['overdue']} past the payer's own promise.")
        for bucket, amount in ageing["buckets"].items():
            self.say(f"     {bucket:10} days  Rs {amount}")
        for row in ageing["claims"][:5]:
            self.say(f"     {row['claim']}  {row['payer'][:20]:20} "
                     f"{row['days']:>3}d of {row['promised_days']}  "
                     f"Rs {row['outstanding']}"
                     f"{'  OVERDUE' if row['past_promise'] else ''}")
        self.say("   Aged against each payer's own promised days rather than "
                 "a generic thirty, so 'overdue' means the payer broke its")
        self.say("   own terms.")

        self.step(18, "Why claims are being cut")
        analysis = deduction_analysis()
        self.say(f"   Rs {analysis['total_deducted']} deducted since "
                 f"{analysis['since']}.")
        for row in analysis["by_reason"]:
            self.say(f"     {row['reason']:22} Rs {row['amount']:>10}  "
                     f"{row['share_percent']}%  ({row['lines']} lines)")
        self.say("   The point of the whole module. A hospital that learns "
                 "40% of its deductions are one thing can change what it")
        self.say("   bills; one with a thousand free-text reasons can change "
                 "nothing.")

        self.step(19, "Which payers are worth dealing with")
        for row in payer_performance():
            self.say(
                f"   {row['payer'][:24]:24} {row['claims']:>3} claims  "
                f"claimed {row['claimed']:>11}  approved {row['approved']:>11}  "
                f"{row['approval_percent']}% approved  "
                f"{row['rejection_percent']}% rejected  "
                f"outstanding {row['outstanding']:>11}"
            )
        self.say("   A contract is renegotiated on these numbers, and a "
                 "hospital that cannot produce them renegotiates on")
        self.say("   impressions.")

        self.step(20, "Approvals about to become worthless")
        expiring = expiring_preauthorisations(within_days=14)
        for row in expiring:
            self.say(f"   {row['reference']}  {row['patient'][:22]:22} "
                     f"{row['treatment'][:28]:28} expires {row['valid_until']} "
                     f"({row['days_left']} days)")
        if not expiring:
            self.say("   None in the next fortnight.")
        self.say("   An approval that expires while the patient waits for a "
                 "theatre slot is a claim that will be rejected as")
        self.say("   unauthorised — and it is predictable a week ahead.")

        self.say("")
        self.say(self.style.SUCCESS("Insurance seed complete."))
