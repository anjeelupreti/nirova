"""A patient using the portal, and everything it refuses to show them.

The module is about what may be shown and to whom, so the seed spends most of
its time on the refusals: registering without an invitation, logging in with a
wrong password, a proxy reading a record after consent is withdrawn, and a
critical result held back while somebody rings.

It runs the real service layer and prints what it expects beside what it got.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.identity.models import User
from apps.patients.models import Patient
from apps.portal.models import (
    ABNORMAL_HOLD_HOURS,
    CRITICAL_HOLD_HOURS,
    MAX_FAILED_ATTEMPTS,
    AccountStatus,
    PortalAccount,
    PortalInvitation,
    PortalSession,
    ProxyAccess,
    ProxyRelationship,
)
from apps.portal.services import (
    AuthenticationFailed,
    PortalError,
    accessible_patients,
    access_for,
    adoption,
    appointments_for,
    authenticate,
    grant_proxy,
    home,
    invite,
    invoices_for,
    note_access,
    prescriptions_for,
    proxy_review,
    register,
    results_for,
    revoke_all_sessions,
    revoke_proxy,
    revoke_session,
    send_message,
    session_for,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Seed portal accounts, proxy access, and what the portal will not show."

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
        except (PortalError, AuthenticationFailed) as error:
            self.say(f"   Refused: {error}")

    def run(self, organization):
        now = timezone.now()
        actor = User.objects.filter(email="owner@manakamana.test").first()
        patients = list(
            Patient.objects.filter(merged_into__isnull=True)
            .exclude(first_name__startswith="Unknown")
            .order_by("id")[:6]
        )
        if len(patients) < 3:
            self.say(self.style.WARNING("   Not enough patients seeded."))
            return

        patient, relative, other = patients[0], patients[1], patients[2]

        self.step(1, "Registration needs an invitation")
        self.refused(
            "registering with a guessed code",
            lambda: register(
                patient, "00000000", "+977-9800000001", "correct horse battery",
            ),
        )
        self.say("   Without this the portal is 'type an MRN and a date of "
                 "birth', and both are printed on every document the patient")
        self.say("   carries. That is an enumeration attack with a login at "
                 "the end of it.")

        self.step(2, "An invitation issued at the desk")
        account = getattr(patient, "portal_account", None)
        if account is None or account.status != AccountStatus.ACTIVE:
            invitation, code = invite(
                patient, actor,
                delivered_by="read aloud at the desk",
                delivered_to="the patient in person",
            )
            self.say(f"   Code issued, hint {invitation.code_hint}, expires "
                     f"{invitation.expires_at:%d %b %Y}.")
            self.say("   Returned once and stored hashed: an invitation list "
                     "readable from the database would be a list of working")
            self.say("   credentials for other people's medical records.")

            self.refused(
                "a password of six characters",
                lambda: register(
                    patient, code, "+977-9800000001", "short",
                ),
            )
            account = register(
                patient, code, "+977-9800000001", "correct horse battery",
                email="sita@example.np",
            )
            self.expect("the account", "active", account.status)

            invitation.refresh_from_db()
            self.expect("the invitation after use", True,
                        invitation.used_at is not None)
            self.refused(
                "using the same code twice",
                lambda: register(
                    other, code, "+977-9800000002", "correct horse battery",
                ),
            )
        else:
            self.say(f"   {patient.full_name} already has an account "
                     f"({account.login_identifier}).")
            self.refused(
                "issuing a second invitation to an active account",
                lambda: invite(patient, actor),
            )

        self.step(3, "Signing in, and what the failure message says")
        self.refused(
            "a login for an identifier that does not exist",
            lambda: authenticate("+977-9999999999", "anything"),
        )
        self.refused(
            "a wrong password",
            lambda: authenticate("+977-9800000001", "wrong password"),
        )
        self.say("   The same sentence for both. A form that says 'no such "
                 "account' is a tool for finding out who is a patient here,")
        self.say("   and that is a disclosure before anybody guesses a "
                 "password.")

        signed_in, session, token = authenticate(
            "+977-9800000001", "correct horse battery",
            device="Samsung A15", ip="10.0.0.4",
        )
        self.expect("a session was issued", True, session.is_live)
        self.expect("the token resolves back to it", str(session.uuid),
                    str(session_for(token).uuid))

        self.step(4, "Lockout, and that it expires on its own")
        account.refresh_from_db()
        for _ in range(MAX_FAILED_ATTEMPTS):
            try:
                authenticate("+977-9800000001", "still wrong")
            except AuthenticationFailed:
                pass
        account.refresh_from_db()
        self.expect(f"locked after {MAX_FAILED_ATTEMPTS} failures", True,
                    account.is_locked)
        self.refused(
            "the correct password while locked",
            lambda: authenticate("+977-9800000001", "correct horse battery"),
        )
        if account.locked_until:
            self.say(f"   Until {account.locked_until:%H:%M}. A lockout that "
                     "never expires is a support call rather than a security")
            self.say("   control, so it recovers on its own.")

        account.locked_until = None
        account.save(update_fields=["locked_until"])

        self.step(5, "Signing out means something")
        # Clear what earlier runs left signed in, so the count below is about
        # this run rather than about how many times the seed has been run.
        cleared = revoke_all_sessions(account, reason="Seed reset")
        self.say(f"   {cleared} session(s) from earlier runs ended.")
        first_session = authenticate(
            "+977-9800000001", "correct horse battery", device="Samsung A15",
        )[1]
        second = authenticate(
            "+977-9800000001", "correct horse battery", device="Library PC",
        )[1]
        self.expect("live sessions", 2, account.sessions.filter(
            revoked_at__isnull=True, expires_at__gt=now,
        ).count())
        revoke_session(second, reason="Signed out from the library")
        second.refresh_from_db()
        self.expect("that one after signing out", False, second.is_live)
        self.say("   Sessions are rows precisely so this works. 'Log out "
                 "everywhere' that invalidates nothing is the commonest lie")
        self.say("   in a consumer account screen, and on a medical record it "
                 "matters.")

        self.step(6, "Proxy access, with consent and an expiry")
        self.refused(
            "granting access to somebody's own record",
            lambda: grant_proxy(
                account, patient, ProxyRelationship.SPOUSE, actor,
                consent_evidence="n/a",
            ),
        )
        self.refused(
            "granting access with no evidence of consent",
            lambda: grant_proxy(
                account, relative, ProxyRelationship.SPOUSE, actor,
                consent_evidence="",
            ),
        )

        grant = ProxyAccess.objects.filter(
            account=account, patient=relative, revoked_at__isnull=True,
        ).first()
        if grant is None:
            grant = grant_proxy(
                account, relative, ProxyRelationship.SPOUSE, actor,
                consent_evidence="Signed consent form dated 12 Bhadra, on file.",
                expires_at=now + timedelta(days=365),
                can_see_results=False,
                can_see_invoices=True,
            )
        self.say(f"   {account.patient.full_name} may see "
                 f"{relative.full_name}'s record: invoices yes, results no.")
        self.say("   Narrower than their own view by default. A spouse "
                 "arranging appointments does not need the notes.")

        self.refused(
            "a second live grant over the same record",
            lambda: grant_proxy(
                account, relative, ProxyRelationship.CARER, actor,
                consent_evidence="Another form.",
            ),
        )

        reachable = accessible_patients(account)
        self.expect("records this account may open", 2, len(reachable))
        for row in reachable:
            self.say(f"     {row['patient'].full_name[:22]:22} "
                     f"{row['relationship']:8} "
                     f"results={row['can_see_results']} "
                     f"invoices={row['can_see_invoices']}")

        self.step(7, "A proxy's reads are logged; the patient's own are not")
        before_own = account.access_log.filter(patient=patient).count()
        before_proxy = account.access_log.filter(patient=relative).count()
        note_access(account, patient, "results", "Own record")
        note_access(account, relative, "invoices", "Spouse's invoices")
        self.expect(
            "new log entries for the patient's own record", 0,
            account.access_log.filter(patient=patient).count() - before_own,
        )
        self.expect(
            "new log entries for the spouse's record", 1,
            account.access_log.filter(patient=relative).count() - before_proxy,
        )
        self.say("   Logging somebody reading their own record produces a "
                 "table nobody can search. For a proxy it is the only way to")
        self.say("   answer the question that eventually gets asked.")

        self.step(8, "Withdrawing consent stops it immediately")
        revoke_proxy(grant, actor, "Consent withdrawn by the patient.")
        self.expect("records this account may open now", 1,
                    len(accessible_patients(account)))
        self.refused(
            "reading the spouse's record after consent is withdrawn",
            lambda: access_for(account, relative),
        )
        self.say("   Checked at query time, never cached on the session. "
                 "Consent withdrawn at ten o'clock stops working at ten")
        self.say("   o'clock, not at the proxy's next sign-in.")

        self.step(9, "What the portal will and will not show")
        # The seeded results were all released long ago, so nothing would be
        # inside the hold window and the branch that matters would go
        # undemonstrated. One order is given a critical flag and a release
        # time of a moment ago — which is the situation the rule exists for.
        from apps.diagnostics.models import DiagnosticOrder, ResultFlag

        fresh = (
            DiagnosticOrder.objects.filter(
                patient=patient, released_at__isnull=False,
            )
            .order_by("-ordered_at")
            .first()
        )
        if fresh is not None:
            fresh.released_at = now - timedelta(hours=1)
            fresh.save(update_fields=["released_at"])
            value = fresh.results.first()
            if value is not None and not value.is_critical:
                value.flag = ResultFlag.CRITICAL_HIGH
                value.save(update_fields=["flag"])

        rows = results_for(patient)
        visible = [row for row in rows if row["visible"]]
        held = [row for row in rows if not row["visible"]]
        self.say(f"   {len(rows)} results: {len(visible)} shown, "
                 f"{len(held)} held.")
        self.expect("at least one result is held back", True, len(held) >= 1)
        for row in held[:3]:
            self.say(f"     {row['test'][:30]:30} {row['message']}")
        self.say(f"   Critical results are held for {CRITICAL_HOLD_HOURS} "
                 f"hours and abnormal ones for {ABNORMAL_HOLD_HOURS}, so a")
        self.say("   clinician can ring first. A patient reading 'potassium "
                 "7.1' from a phone at eleven at night, with nobody to ask,")
        self.say("   is a harm the system caused.")
        self.say("   Held is not hidden: the patient is told a result is "
                 "ready and that somebody will be in touch. A gap they do not")
        self.say("   know about is worse than a delay they do — and an "
                 "indefinite hold is a result they never learn about at all.")

        self.step(10, "The rest of their record")
        money = invoices_for(patient)
        self.say(f"   Invoices: {len(money['invoices'])}, outstanding "
                 f"Rs {money['outstanding']}.")
        self.say("   Only issued documents. A draft invoice is a working note "
                 "inside the hospital, and showing one invites an argument")
        self.say("   about a number nobody has agreed yet.")
        self.say(f"   Appointments: {len(appointments_for(patient))}")
        self.say(f"   Prescriptions: {len(prescriptions_for(patient))}")

        self.step(11, "The first screen")
        first = home(account)
        for key in (
            "patient", "via_proxy", "upcoming_appointments", "results_ready",
            "results_being_discussed", "outstanding", "unread_messages",
        ):
            self.say(f"   {key}: {first[key]}")
        self.say("   Held results are counted separately, so the screen can "
                 "say a result is ready and being discussed rather than")
        self.say("   showing a list with an unexplained gap in it.")

        self.step(12, "Messages, and what the portal says they are not")
        message = send_message(
            account, patient,
            "Repeat prescription",
            "Could I have another three months of the metformin, please?",
        )
        self.expect("the message direction", "from_patient", message.direction)
        self.say("   Not a clinical channel, and the portal says so beside "
                 "the box. A patient who describes chest pain here and waits")
        self.say("   is a foreseeable harm, and accepting the message without "
                 "saying so has invited it.")

        self.step(13, "Who is using it")
        stats = adoption()
        for key, value in stats.items():
            self.say(f"   {key}: {value}")
        self.say("   Invitations issued against accounts registered is the "
                 "number that says whether the desk is offering it or quietly")
        self.say("   skipping it — invisible if only active accounts are "
                 "counted.")

        self.step(14, "Proxy grants nobody has revisited")
        for row in proxy_review(days=0):
            self.say(f"   {row['proxy'][:20]:20} → {row['patient'][:20]:20} "
                     f"{row['relationship']:8} granted {row['days_old']}d ago"
                     f"{'  results' if row['can_see_results'] else ''}")
        if not proxy_review(days=0):
            self.say("   None live.")
        self.say("   Consent given once and never revisited is how an "
                 "estranged relative keeps reading somebody's results for")
        self.say("   years. The list exists so that somebody can be asked.")

        self.say("")
        self.say(self.style.SUCCESS("Portal seed complete."))
