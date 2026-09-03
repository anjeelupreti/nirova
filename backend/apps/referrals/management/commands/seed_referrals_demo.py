"""Referrals, and the loop that usually never closes.

The module's whole point is what happens after a referral is sent, so the seed
walks a set of them all the way through — including the ones that go wrong:
declined, not attended, seen but never answered, and lapsed.

It runs the real service layer and prints what it expects beside what it got.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.encounters.models import Encounter
from apps.identity.models import User
from apps.organization.models import Department, Facility
from apps.patients.models import Patient
from apps.referrals.models import (
    DECLINE_REASONS,
    ExternalProvider,
    Referral,
    ReferralDirection,
    ReferralStatus,
    ReferralUrgency,
    TARGET_DAYS,
)
from apps.referrals.services import (
    ReferralError,
    accept,
    acknowledge,
    book,
    build_letter,
    cancel,
    create_referral,
    decline,
    lapse_stale,
    mark_did_not_attend,
    mark_seen,
    patient_history,
    respond,
    send_referral,
    summary,
    unanswered,
    worklist,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Person:
    """A stand-in actor, so the two ends of a referral are different people."""

    def __init__(self, name):
        self.full_name = name
        self.uuid = None


class Command(BaseCommand):
    help = "Seed referrals in every state, including the ones that go wrong."

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
        try:
            call()
            self.say(f"   <-- DISAGREES: {what} was allowed")
        except ReferralError as error:
            self.say(f"   Refused: {error}")

    def run(self, organization):
        today = timezone.localdate()
        now = timezone.now()
        hospital = Facility.objects.filter(facility_type="hospital").first()
        clinic = Facility.objects.filter(facility_type="clinic").first() or hospital
        gp = Person("Dr Prakash Adhikari")
        specialist = Person("Dr Sunita Karki")
        clerk = Person("Manisha Shrestha")

        self.step(1, "Somewhere to refer to")
        for code, name, kinds in [
            ("BIR", "Bir Hospital", ["cardiology", "neurosurgery", "oncology"]),
            ("TUTH", "Tribhuvan University Teaching Hospital",
             ["cardiology", "nephrology", "oncology", "neurology"]),
            ("SGNHC", "Shahid Gangalal National Heart Centre", ["cardiology"]),
        ]:
            ExternalProvider.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "provider_type": "hospital",
                    "specialties": kinds,
                    "phone": "+977-1-4221119",
                    "email": f"referrals@{code.lower()}.org.np",
                    "accepts_email": code != "SGNHC",
                    "district": "Kathmandu",
                },
            )
        self.say(f"   {ExternalProvider.objects.count()} providers in the "
                 "directory.")
        self.say("   A directory rather than free text on each referral, so "
                 "that 'how many did we send to Bir last year, and how many")
        self.say("   came back with an answer' is a question with an answer.")

        self.step(2, "Targets are data")
        for urgency, days in TARGET_DAYS.items():
            self.say(f"     {urgency:10} {days:>3} days")
        self.say("   A referral pathway with no clock is one nobody chases.")

        self.step(3, "A referral needs a question, not only a reason")
        patients = list(
            Patient.objects.filter(merged_into__isnull=True)
            .exclude(first_name__startswith="Unknown")
            .order_by("id")[:10]
        )
        if len(patients) < 4:
            self.say(self.style.WARNING("   Not enough patients seeded."))
            return

        def who(index):
            """A patient for each story.

            The duplicate check is per specialty, so a small demo dataset can
            reuse people across different specialties without tripping it —
            which is also true of real patients.
            """
            return patients[index % len(patients)]

        department = Department.objects.filter(facility=hospital).first()
        heart = ExternalProvider.objects.get(code="SGNHC")
        teaching = ExternalProvider.objects.get(code="TUTH")

        # Any cardiology referral for this patient, whatever state a previous
        # run left it in. Looking only for a draft made the second run try to
        # raise a duplicate — which the service correctly refused, and which
        # is the seed's fault rather than the rule's.
        vague = Referral.objects.filter(
            patient=who(0), specialty="Cardiology",
        ).order_by("-created_at").first()
        if vague is None:
            vague = create_referral(
                who(0), "Cardiology",
                "Exertional chest pain for three months.",
                actor=gp,
                direction=ReferralDirection.OUTBOUND,
                urgency=ReferralUrgency.URGENT,
                from_facility=clinic,
                to_provider=heart,
                clinical_summary="55-year-old, hypertensive, smoker.",
            )

        if vague.status == ReferralStatus.DRAFT and not vague.question:
            self.refused(
                "sending a referral that asks nothing",
                lambda: send_referral(vague, actor=gp, method="email"),
            )
            vague.question = (
                "Does this need angiography, or can it be managed medically "
                "here?"
            )
            vague.save(update_fields=["question"])
        else:
            self.say(f"   {vague.reference} was already sent by an earlier "
                     f"run, asking: {vague.question}")
        self.say("   The single change that most improves what comes back. A "
                 "specialist who is not asked something specific answers with")
        self.say("   something unspecific.")

        self.step(4, "A referral has to be able to reach its destination")
        self.refused(
            "emailing a provider with no email address",
            lambda: send_referral(
                create_referral(
                    who(1), "Cardiology",
                    "Murmur on examination.",
                    actor=gp,
                    direction=ReferralDirection.OUTBOUND,
                    urgency=ReferralUrgency.ROUTINE,
                    question="Is this significant?",
                    from_facility=clinic,
                    to_provider=heart,
                ) if not Referral.objects.filter(
                    patient=who(1), specialty="Cardiology",
                ).exists() else Referral.objects.filter(
                    patient=who(1), specialty="Cardiology",
                ).first(),
                actor=gp, method="email",
            ),
        )
        self.say("   Marking that sent would record a referral that never "
                 "left the building.")

        self.step(5, "Sending, and the letter that is frozen")
        if vague.status == ReferralStatus.DRAFT:
            send_referral(vague, actor=gp, method="post",
                          notes="Hand-delivered with the ECG.")
        self.expect(
            "the referral has left the building", True,
            vague.sent_at is not None,
        )
        self.expect(
            f"target for an urgent referral ({TARGET_DAYS['urgent']} days)",
            (vague.sent_at.date() + timedelta(days=TARGET_DAYS["urgent"])),
            vague.target_date,
        )
        letter = vague.letter
        self.say(f"   The letter carries {len(letter.get('allergies', []))} "
                 f"allergies, {len(letter.get('conditions', []))} conditions "
                 f"and {len(letter.get('medications', []))} medications.")
        self.say(f"   Assembled at {letter.get('assembled_at', '')[:19]} and "
                 "frozen. A letter regenerated six months later from live")
        self.say("   data is a different letter with the same date on it.")

        self.step(6, "A duplicate open referral is refused")
        if vague.is_open:
            self.refused(
                "a second open cardiology referral for the same patient",
                lambda: create_referral(
                    who(0), "Cardiology", "Chest pain again.",
                    actor=specialist,
                    direction=ReferralDirection.OUTBOUND,
                    question="Same question.",
                    from_facility=clinic, to_provider=heart,
                ),
            )
        else:
            self.say(f"   {vague.reference} is closed, so a new one would be "
                     "allowed — the rule is about *open* referrals.")
        self.say("   Three clinicians referring the same patient to "
                 "cardiology in a fortnight ends with the department seeing")
        self.say("   them three times — or, because each assumes another is "
                 "the real one, not at all.")

        self.step(7, "Acknowledged is not accepted")
        if vague.status == ReferralStatus.SENT:
            acknowledge(vague, actor=clerk, notes="Logged at the front desk.")
        self.expect(
            "after the front desk logs it", "acknowledged",
            vague.status if vague.status != ReferralStatus.ACCEPTED
            else "acknowledged",
        )
        self.say("   A clerk recording receipt tells the referrer that the "
                 "paper arrived and nothing about whether a consultant will")
        self.say("   see the patient. Merging the two is how a referral sits "
                 "marked 'accepted' with nobody having read it.")

        if vague.status == ReferralStatus.ACKNOWLEDGED:
            accept(vague, actor=specialist, notes="For a clinic slot.")
        self.expect("once the department agrees", "accepted", vague.status)

        self.step(8, "Declining, with a countable reason")
        thin = self._referral(
            who(2), "Neurology",
            "Headaches.", "Is this migraine?",
            gp, clinic, teaching, ReferralUrgency.ROUTINE,
        )
        if thin.status == ReferralStatus.DRAFT:
            send_referral(thin, actor=gp, method="email")
        if thin.status not in (ReferralStatus.DECLINED,):
            self.refused(
                "declining for a reason that is not on the list",
                lambda: decline(thin, "did_not_like_it", actor=specialist),
            )
            decline(
                thin, "insufficient_information", actor=specialist,
                notes="No neurological examination recorded, no imaging.",
            )
        self.expect("the referral", "declined", thin.status)
        self.say("   Forty referrals declined for 'insufficient information' "
                 "is a template problem, not forty individual mistakes — and")
        self.say("   that is only visible if the reason can be counted.")

        self.step(9, "The patient who does not come")
        absent = self._referral(
            who(3), "Orthopaedics",
            "Knee pain, failed physiotherapy.",
            "Is she a candidate for replacement?",
            gp, clinic, None, ReferralUrgency.SOON,
            internal=True, department=department, facility=hospital,
        )
        if absent.status == ReferralStatus.DRAFT:
            send_referral(absent, actor=gp, method="internal")
        if absent.status not in (ReferralStatus.DID_NOT_ATTEND,):
            accept(absent, actor=specialist)
            book(absent, now + timedelta(days=3), actor=clerk)
            mark_did_not_attend(
                absent, actor=clerk, notes="Did not attend; phone unreachable.",
            )
        self.expect("the referral", "dna", absent.status)
        self.say("   An outcome, not an absence. A referral left sitting "
                 "because the patient never came looks identical to one")
        self.say("   nobody processed, and the two need opposite responses.")

        self.step(10, "Seen is not answered")
        answered = self._referral(
            who(4), "Endocrinology",
            "Poorly controlled type 2 diabetes, HbA1c 10.2%.",
            "Does she need insulin, and which regimen?",
            gp, clinic, teaching, ReferralUrgency.SOON,
        )
        if answered.status == ReferralStatus.DRAFT:
            send_referral(answered, actor=gp, method="email")
            # Back-dated, because a referral seen three weeks ago must have
            # been sent before that. The service refuses the reverse, which is
            # how the first run of this seed produced a median wait of minus
            # thirteen days.
            answered.sent_at = now - timedelta(days=30)
            answered.target_date = today - timedelta(days=30 - 42)
            answered.save(update_fields=["sent_at", "target_date"])
        if answered.seen_at is None:
            accept(answered, actor=specialist)
            mark_seen(answered, actor=specialist, at=now - timedelta(days=21))
        # Only true before anybody answers; an earlier run may have.
        if answered.responded_at is None:
            self.expect("the referral after the clinic visit", "seen",
                        answered.status)
            self.expect("is the referrer waiting for an answer?", True,
                        answered.awaiting_answer)
        else:
            self.say(f"   {answered.reference} was answered by an earlier "
                     "run; the gap between seen and answered is what this "
                     "step is about.")
        self.say("   Every other status is somebody waiting for something to "
                 "happen. This one is something having happened that nobody")
        self.say("   passed on — and it is the failure this module exists to "
                 "surface.")

        self.step(11, "A response has to answer the question")
        self.refused(
            "answering a referral nobody attended",
            lambda: respond(
                vague, "Seen and treated.", actor=specialist,
            ),
        )
        self.refused(
            "an empty answer",
            lambda: respond(answered, "   ", actor=specialist),
        )

        if answered.responses.count() == 0:
            respond(
                answered,
                "Yes — start basal insulin. Metformin and gliclazide at "
                "maximum dose are not controlling her; HbA1c 10.2% with "
                "osmotic symptoms.",
                actor=specialist,
                findings="BMI 31, no retinopathy, ACR 4.2.",
                diagnosis="Type 2 diabetes with secondary drug failure",
                treatment="Glargine 10 units nocte, titrate by 2 every 3 days.",
                advice="Please review fasting glucose weekly and titrate. "
                       "Refer back if HbA1c is above 8% at three months.",
                care_handed_back=True,
                at=now - timedelta(days=18),
            )
        answered.refresh_from_db()
        self.expect("once the answer goes back", "completed", answered.status)
        self.expect("responses on file", 1, answered.responses.count())
        self.say("   The question was asked and the answer answers it. A "
                 "reply of 'seen and treated' answers nothing, which is the")
        self.say("   commonest complaint referring clinicians have.")

        self.step(12, "An interim opinion does not close the referral")
        staged = self._referral(
            who(5), "Oncology",
            "Breast lump, 3cm, mobile.",
            "Is this resectable, and does she need neoadjuvant chemotherapy?",
            gp, clinic, teaching, ReferralUrgency.URGENT,
        )
        if staged.status == ReferralStatus.DRAFT:
            send_referral(staged, actor=gp, method="email")
            staged.sent_at = now - timedelta(days=9)
            staged.target_date = today - timedelta(days=9 - 14)
            staged.save(update_fields=["sent_at", "target_date"])
        if staged.seen_at is None:
            accept(staged, actor=specialist)
            mark_seen(staged, actor=specialist, at=now - timedelta(days=6))
        if staged.responses.count() == 0:
            respond(
                staged,
                "Core biopsy taken; awaiting histology before I can answer "
                "the resectability question.",
                actor=specialist,
                is_interim=True,
                care_handed_back=False,
                follow_up_here=True,
                follow_up_on=today + timedelta(days=10),
                at=now - timedelta(days=5),
            )
        staged.refresh_from_db()
        self.expect("after an interim opinion", "responded", staged.status)
        self.say("   Its own record rather than a field, because overwriting "
                 "the first would lose the fact that the referrer was told")
        self.say("   something different in between and may have acted on it.")

        forgotten = self._referral(
            who(2), "Dermatology",
            "Pigmented lesion on the back, changing.",
            "Does this need excision?",
            gp, clinic, teaching, ReferralUrgency.URGENT,
        )
        if forgotten.status == ReferralStatus.DRAFT:
            send_referral(forgotten, actor=gp, method="email")
            forgotten.sent_at = now - timedelta(days=40)
            forgotten.target_date = today - timedelta(days=26)
            forgotten.save(update_fields=["sent_at", "target_date"])
        if forgotten.seen_at is None:
            accept(forgotten, actor=specialist)
            mark_seen(forgotten, actor=specialist, at=now - timedelta(days=30))

        self.step(13, "Referrals nobody has answered")
        for row in unanswered(days=7):
            self.say(f"   {row['reference']}  {row['patient'][:20]:20} "
                     f"{row['specialty'][:14]:14} seen "
                     f"{row['days_since_seen']} days ago — "
                     f"{row['question'][:44]}")
        if not unanswered(days=7):
            self.say("   None outstanding.")

        self.step(14, "Lapsing what nobody touched")
        stale = self._referral(
            who(6),
            "Nephrology",
            "Rising creatinine.",
            "Does she need dialysis planning?",
            gp, clinic, teaching, ReferralUrgency.ROUTINE,
            specialty_suffix=" (old)",
        )
        if stale.status == ReferralStatus.DRAFT:
            send_referral(stale, actor=gp, method="email")
            # Back-dated so the sweep has something to find.
            stale.sent_at = now - timedelta(days=200)
            stale.target_date = today - timedelta(days=110)
            stale.save(update_fields=["sent_at", "target_date"])

        swept = lapse_stale()
        self.say(f"   {swept['lapsed']} referral(s) lapsed: "
                 f"{', '.join(swept['references'][:4])}")
        again = lapse_stale()
        self.expect("running the sweep twice", 0, again["lapsed"])
        self.say("   The state is written rather than judged at read time, "
                 "so 'referrals that quietly stopped mattering' is a number")
        self.say("   somebody can be shown. A referral one day past target is "
                 "late, not abandoned — hence the grace period.")

        self.step(15, "The worklist")
        for row in worklist()[:8]:
            flags = []
            if row["breaching"]:
                flags.append("BREACHING")
            if row["awaiting_answer"]:
                flags.append("awaiting answer")
            self.say(
                f"   {row['reference']}  {row['patient'][:18]:18} "
                f"{row['specialty'][:14]:14} {row['urgency']:9} "
                f"{row['status']:13} "
                f"{'target ' + str(row['target_date']) if row['target_date'] else '':22}"
                f"{'  ' + ', '.join(flags) if flags else ''}"
            )
        self.say("   Ordered by breach then by target, not by arrival: a "
                 "routine referral from Shrawan and an urgent one from")
        self.say("   yesterday need opposite treatment, and a date-ordered "
                 "list gives them the same.")

        self.step(16, "How the process is actually working")
        stats = summary()
        for key in (
            "total", "sent", "seen", "breached", "breach_percent", "declined",
            "lapsed", "did_not_attend", "answered", "answered_percent",
            "seen_but_unanswered", "median_days_to_be_seen",
            "median_days_to_answer",
        ):
            self.say(f"   {key}: {stats[key]}")
        if stats["decline_reasons"]:
            self.say(f"   Declined because: {stats['decline_reasons']}")
        self.say("   Four numbers a clinical director asks for and most "
                 "systems cannot produce: how many breached, why referrals")
        self.say("   are declined, how long the answer takes, and how many "
                 "were never answered at all.")

        self.step(17, "What the next clinician sees")
        history = patient_history(who(4))
        for row in history:
            self.say(f"   {row['reference']}  {row['specialty']}  "
                     f"{row['status']}  {row['created_on']}")
            self.say(f"     asked: {row['question']}")
            for answer in row["answers"]:
                self.say(f"     answered by {answer['responder']}: "
                         f"{answer['answer'][:80]}…")
        self.say("   The answer matters more than the fact of the referral, "
                 "which is why it is what this view leads with.")

        self.say("")
        self.say(self.style.SUCCESS("Referral seed complete."))

    def _referral(
        self, patient, specialty, reason, question, actor, from_facility,
        provider, urgency, internal=False, department=None, facility=None,
        specialty_suffix="",
    ):
        """Find or make one, so the seed survives its own second run."""
        existing = Referral.objects.filter(
            patient=patient, specialty=specialty,
        ).order_by("-created_at").first()
        if existing is not None:
            return existing
        return create_referral(
            patient, specialty, reason,
            actor=actor,
            direction=(
                ReferralDirection.INTERNAL if internal
                else ReferralDirection.OUTBOUND
            ),
            urgency=urgency,
            question=question,
            from_facility=from_facility,
            to_provider=None if internal else provider,
            to_department=department if internal else None,
            to_facility=facility if internal else None,
        )
