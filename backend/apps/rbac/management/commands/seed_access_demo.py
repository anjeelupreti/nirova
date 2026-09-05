"""What each role can actually reach, asked over HTTP.

The gap this closes is named in `docs/PHASE2.md`: every other seed in this
project runs at the service layer, **below** the permission classes. So a green
suite proved that enforcement did not break the domain logic, and proved
nothing at all about who can open what. The one bug that class of testing would
never have found -- a permission class listed in `permission_classes` and never
invoked, because a plain `APIView` does not call `get_object()` -- was found by
hand instead.

So this drives the real API as real users, with real tokens, and narrates what
it expects beside what it got. It is slower than a unit test and that is the
point: the interesting failures live between the permission class, the
queryset and the router, and every layer removed is a layer that stops being
tested.

Run with the relationship switch in both positions, because "who can see what"
has two answers and shipping only ever exercises one of them.
"""

import json

from django.core.management.base import BaseCommand
from django.test import Client
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.permissions import (
    PRIVACY_NAMESPACE,
    REQUIRE_RELATIONSHIP_KEY,
)
from apps.identity.models import User
from apps.organization.config import config_value, set_config_value
from apps.organization.models import ConfigSetting
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: Each role, and the account that holds it in the demo tenant.
ACTORS = [
    ("organization owner", "owner@manakamana.test"),
    ("doctor", "doctor@manakamana.test"),
    ("pharmacy counter", "counter@manakamana.test"),
]

#: Read endpoints worth asking about. Kept to reads: this seed is about who can
#: *see* what, and a seed that also wrote would change the answers underneath
#: itself between runs.
ENDPOINTS = [
    ("patients", "/api/clinical/patients/"),
    ("encounters", "/api/clinical/encounters/"),
    ("prescriptions", "/api/clinical/prescriptions/"),
    ("diagnostic orders", "/api/diagnostics/orders/"),
    ("appointments", "/api/clinical/appointments/"),
    ("invoices", "/api/billing/invoices/"),
]


class Command(BaseCommand):
    help = "Exercise the API as each role, with and without enforcement."

    def add_arguments(self, parser):
        parser.add_argument("--organization", default="manakamana")

    # -- output ----------------------------------------------------------

    def say(self, text=""):
        self.stdout.write(text)

    def expect(self, label, got, expected):
        ok = got == expected
        line = f"   {'ok ' if ok else 'XX '}{label}: expected {expected}, got {got}"
        self.stdout.write(line if ok else self.style.ERROR(line))
        if not ok:
            raise AssertionError(line)

    # -- helpers ---------------------------------------------------------

    def client_for(self, email, organization):
        user = User.objects.filter(email=email).first()
        if user is None:
            return None, None
        token = RefreshToken.for_user(user).access_token
        return Client(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_ORGANIZATION=organization.slug,
        ), user

    def count(self, client, path):
        """Rows visible, or the status code when the answer is a refusal.

        A refusal and an empty list are different facts and the table has to
        show which is which -- "0" and "403" mean opposite things about whether
        the person is allowed to look.
        """
        response = client.get(path)
        if response.status_code != 200:
            return str(response.status_code)
        try:
            body = json.loads(response.content.decode())
        except ValueError:
            return "?"
        if isinstance(body, dict) and "count" in body:
            return body["count"]
        if isinstance(body, list):
            return len(body)
        return "-"

    # -- the run ---------------------------------------------------------

    def handle(self, *args, **options):
        organization = Organization.objects.get(slug=options["organization"])
        with tenant_context(context_for_organization(organization)):
            original = config_value(
                PRIVACY_NAMESPACE, REQUIRE_RELATIONSHIP_KEY, default=None,
            )
        try:
            self._run(organization)
        finally:
            # Put the tenant back exactly as it was found. A seed that leaves a
            # security control in a different position than it found it in is
            # worse than one that fails.
            with tenant_context(context_for_organization(organization)):
                ConfigSetting.all_objects.filter(
                    namespace=PRIVACY_NAMESPACE, key=REQUIRE_RELATIONSHIP_KEY,
                ).delete()
                if original is not None:
                    set_config_value(
                        PRIVACY_NAMESPACE, REQUIRE_RELATIONSHIP_KEY, original,
                    )

    def _switch(self, organization, value):
        with tenant_context(context_for_organization(organization)):
            ConfigSetting.all_objects.filter(
                namespace=PRIVACY_NAMESPACE, key=REQUIRE_RELATIONSHIP_KEY,
            ).delete()
            if value is not None:
                set_config_value(
                    PRIVACY_NAMESPACE, REQUIRE_RELATIONSHIP_KEY, value,
                )

    def _table(self, organization, actors):
        self.say("   %-20s %s" % ("", "  ".join(
            f"{label:>10.10s}" for label, _ in ENDPOINTS)))
        rows = {}
        for name, client in actors:
            counts = [self.count(client, path) for _, path in ENDPOINTS]
            rows[name] = counts
            self.say("   %-20s %s" % (name, "  ".join(
                f"{str(value):>10s}" for value in counts)))
        return rows

    def _run(self, organization):
        self.say()
        self.say("--- Who can see what, over HTTP ---")

        actors = []
        for name, email in ACTORS:
            client, user = self.client_for(email, organization)
            if client is None:
                self.say(f"   {email} does not exist; run seed_demo")
                return
            actors.append((name, client))

        self.say()
        self.say("1. Enforcement OFF -- the shipping default")
        self._switch(organization, None)
        off = self._table(organization, actors)

        self.say()
        self.say("   Nobody is refused outright. A counter assistant sees every")
        self.say("   prescription in the organization, which is the finding of")
        self.say("   4 September and the reason the rest of this exists.")
        self.expect("counter is not refused prescriptions",
                    isinstance(off["pharmacy counter"][2], int), True)

        self.say()
        self.say("2. Enforcement ON")
        self._switch(organization, True)
        on = self._table(organization, actors)

        self.say()
        self.say("   The owner is exempt -- oversight is the job -- so their")
        self.say("   numbers do not move. The doctor narrows to the patients")
        self.say("   they are treating. The counter narrows to nobody.")
        self.expect("owner unchanged", on["organization owner"][2],
                    off["organization owner"][2])
        self.expect("doctor narrows",
                    on["doctor"][2] < off["doctor"][2], True)
        self.expect("counter browses nothing", on["pharmacy counter"][2], 0)

        self.say()
        self.say("3. Identity and safety stay organization-wide")
        self.say("   Deliberately. A pharmacist who cannot see an allergy list")
        self.say("   is more dangerous than one who can see too much, and a")
        self.say("   counter that cannot identify somebody creates duplicate")
        self.say("   records -- which is how a person is given a drug they are")
        self.say("   allergic to.")
        self.expect("counter still sees the patient list",
                    on["pharmacy counter"][0], off["pharmacy counter"][0])

        self.say()
        self.say("4. Invoices are a branch's own business, either way")
        self.expect("counter invoices unchanged by the switch",
                    on["pharmacy counter"][5], off["pharmacy counter"][5])
        self.expect("and fewer than the owner sees",
                    on["pharmacy counter"][5] < on["organization owner"][5],
                    True)

        self.say()
        self.say("5. A presented reference still opens")
        self._presented(organization)

        self.say()
        self.say(self.style.SUCCESS("Access behaviour verified over HTTP."))

    def _presented(self, organization):
        """The asymmetry: browse narrows, a named record does not.

        The case the whole design turns on, and the one a facility filter would
        have broken -- a patient may take a prescription to any pharmacy.
        """
        counter, _ = self.client_for("counter@manakamana.test", organization)
        with tenant_context(context_for_organization(organization)):
            from apps.prescriptions.models import Prescription

            prescription = (
                Prescription.objects.exclude(status="superseded")
                .select_related("patient")
                .first()
            )
            if prescription is None:
                self.say("   no prescription to present")
                return
            reference = prescription.reference
            uuid = str(prescription.uuid)

        self.expect("browsing", self.count(
            counter, "/api/clinical/prescriptions/"), 0)
        response = counter.get(f"/api/clinical/prescriptions/{uuid}/")
        self.expect(f"opening {reference} by reference",
                    response.status_code, 200)
        self.say("   Presenting the reference is the care relationship and is")
        self.say("   the consent. A pharmacy cannot enumerate the group's")
        self.say("   prescriptions and can still dispense the one in front of")
        self.say("   them.")
