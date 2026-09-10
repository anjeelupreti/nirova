"""Which roles can open which screen, read off the navigation and the roles.

**Written because "every refusal is correct" was a claim I could not support.**
`audit_screens` compares what the sidebar offers against what the API allows and
reports where they disagree. `test_nav.py` enforces the same agreement. Both are
consistency checks -- and consistency is not correctness. When a screen's `needs`
and its endpoints agree on a permission that is *too coarse*, everything passes
and every doctor in the hospital can read the general ledger.

That is what had happened. `report.read` gated laboratory turnaround (which a
doctor needs) and the chart of accounts, bank statements and VAT return (which
they do not), so the Finance entry appeared in a doctor's sidebar and every
endpoint behind it answered 200. Nothing was inconsistent. Everything was wrong.

This command cannot make that judgement -- "should a pharmacist see the theatre
list" is a question about a hospital, not about code. What it removes is the
*looking*: it prints the screen-by-role matrix so somebody can read it once and
say which cells are wrong, instead of discovering one cell at a time.

    manage.py audit_access                 # every screen, every role
    manage.py audit_access --role doctor   # what one role can open
    manage.py audit_access --screen Finance
"""

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: `{ to: "/finance", label: "Finance", icon: Scale, needs: "finance.read", scope: "facility" },`
NAV_ENTRY = re.compile(
    r'\{\s*to:\s*"(?P<to>/[^"]*)"\s*,\s*label:\s*"(?P<label>[^"]*)"'
    r'(?P<rest>[^}]*)\}'
)
NEEDS = re.compile(r'needs:\s*"([^"]+)"')
SCOPE = re.compile(r'scope:\s*"([^"]+)"')


class Command(BaseCommand):
    help = "Print which roles can open which screen."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="manakamana")
        parser.add_argument("--role", help="Only this role code.")
        parser.add_argument("--screen", help="Only entries matching this label.")

    def handle(self, *args, **options):
        entries = self._nav()
        if not entries:
            self.stdout.write(self.style.ERROR("No navigation entries found."))
            return

        organization = Organization.objects.filter(slug=options["org"]).first()
        if organization is None:
            self.stdout.write(self.style.ERROR(f"No organization {options['org']}."))
            return

        with tenant_context(context_for_organization(organization)):
            from apps.rbac.models import Role

            roles = [
                role for role in Role.objects.filter(is_active=True).order_by("code")
                # The superuser role holds everything by construction and would
                # be a column of ticks, saying nothing.
                if not role.is_superuser_role
            ]
            if options.get("role"):
                roles = [r for r in roles if r.code == options["role"]]
                if not roles:
                    self.stdout.write(
                        self.style.ERROR(f"No role {options['role']}.")
                    )
                    return

            self._report(entries, roles, options.get("screen"))

    # -- internals --------------------------------------------------------

    def _nav(self) -> list:
        """Every sidebar entry, with the permission it is gated on.

        Read out of `App.tsx` for the reason every audit here reads the source:
        a hand-kept list of screens and their permissions would drift, and it
        would drift silently.
        """
        app = Path(settings.BASE_DIR).parent / "frontend" / "src" / "App.tsx"
        if not app.exists():
            return []

        source = app.read_text(encoding="utf-8")

        # `platformOnly` groups are hidden from tenant users by a separate
        # mechanism -- `isPlatformStaff`, not a permission -- so listing the
        # console as "open to anybody signed in" would be untrue in the one
        # direction that matters. Collected by name and skipped.
        platform_only = set()
        for group in re.finditer(
            r"platformOnly:\s*true(?P<body>.*?)\],", source, re.S
        ):
            platform_only.update(
                re.findall(r'to:\s*"(/[^"]*)"', group.group("body"))
            )

        entries = []
        for match in NAV_ENTRY.finditer(source):
            if match.group("to") in platform_only:
                continue
            rest = match.group("rest")
            needs = NEEDS.search(rest)
            scope = SCOPE.search(rest)
            entries.append({
                "to": match.group("to"),
                "label": match.group("label"),
                "needs": needs.group(1) if needs else "",
                "scope": scope.group(1) if scope else "own",
            })
        return entries

    def _report(self, entries, roles, only_screen) -> None:
        shown = [
            entry for entry in entries
            if not only_screen or only_screen.lower() in entry["label"].lower()
        ]

        width = max(len(e["label"]) for e in shown) + 2
        header = " ".join(f"{r.code[:9]:>9}" for r in roles)
        self.stdout.write("")
        self.stdout.write(f"{'screen':<{width}}{'permission':<26}{header}")

        open_to_all = []
        for entry in shown:
            needs = entry["needs"]
            cells = []
            holders = 0
            for role in roles:
                if not needs:
                    cells.append(self.style.WARNING(f"{'open':>9}"))
                    holders += 1
                elif needs in role.permissions:
                    cells.append(self.style.SUCCESS(f"{'yes':>9}"))
                    holders += 1
                else:
                    cells.append(f"{'-':>9}")

            if not needs:
                open_to_all.append(entry["label"])

            self.stdout.write(
                f"{entry['label']:<{width}}"
                f"{(needs or 'anyone signed in'):<26}"
                + " ".join(cells)
            )

        self.stdout.write("")
        self.stdout.write(
            f"{len(shown)} screen(s), {len(roles)} role(s). "
            "A tick is not an endorsement -- it is what the sidebar will show."
        )
        # Without this the `data.import` row is a line of dashes and reads as
        # "nobody can do this", when what it means is "only the organization
        # administrator can" -- which for a bulk import is the intent.
        self.stdout.write(
            "The organization administrator is not a column: it holds every "
            "permission by construction, so a row of dashes means 'only the "
            "administrator', not 'nobody'."
        )
        if open_to_all:
            self.stdout.write(
                self.style.WARNING(
                    "Open to anybody signed in: " + ", ".join(open_to_all)
                    + ". Right for self-service; worth a second look for "
                    "anything else."
                )
            )
        self.stdout.write(
            "Read the rows, not the totals. The question this cannot answer is "
            "whether a role *should* hold the permission a screen asks for -- "
            "that is a question about a hospital."
        )
