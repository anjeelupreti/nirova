"""Refresh the system roles in every tenant against the current catalogue.

**A permission added to the catalogue did not reach anybody.** `PERMISSIONS` in
`apps/rbac/permissions.py` is the list of what exists; a `Role` row holds the
list of what that role *was granted*, copied at seeding time. `seed_system_roles`
runs during provisioning, so a new permission reaches tenants created afterwards
and no others -- including every existing customer. The symptom is a feature that
works for the organization owner, who bypasses permission checks entirely, and
answers 403 for the administrator who is supposed to use it. Easy to misread as
a bug in the feature.

Found while adding `data.import`: the owner could import and the organization
administrator could not.

Idempotent, by `seed_system_roles`'s own contract: it refreshes the roles marked
`is_system` and leaves roles the customer created, and permissions they have
deliberately removed from a custom role, alone.

    manage.py sync_roles             # every tenant
    manage.py sync_roles --org x     # one
    manage.py sync_roles --dry-run   # what would change, changing nothing
"""

from django.core.management.base import BaseCommand

from apps.rbac.permissions import PERMISSION_CODES
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Refresh system roles in every tenant against the permission catalogue."

    def add_arguments(self, parser):
        parser.add_argument("--org", help="Only this organization slug.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report which roles would gain or lose permissions.",
        )

    def handle(self, *args, **options):
        organizations = Organization.objects.all()
        if options.get("org"):
            organizations = organizations.filter(slug=options["org"])
        if not organizations:
            self.stdout.write(self.style.ERROR("No matching organizations."))
            return

        changed_total = 0
        for organization in organizations:
            try:
                context = context_for_organization(organization)
            except Exception as error:  # noqa: BLE001 - an unprovisioned tenant
                self.stdout.write(
                    self.style.WARNING(f"  skipped {organization.slug}: {error}")
                )
                continue

            with tenant_context(context):
                changed_total += self._sync_one(organization, options["dry_run"])

        self.stdout.write("")
        if options["dry_run"]:
            self.stdout.write(
                f"{changed_total} role(s) would change. Re-run without "
                "--dry-run to apply."
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"{changed_total} role(s) updated."))

    def _sync_one(self, organization, dry_run: bool) -> int:
        from apps.rbac.models import Role
        from apps.rbac.services import SYSTEM_ROLES, seed_system_roles

        before = {
            role.code: set(role.permissions)
            for role in Role.objects.filter(is_system=True)
        }
        wanted = {
            spec["code"]: set(spec["permissions"]) for spec in SYSTEM_ROLES
        }

        differences = []
        for code, codes in wanted.items():
            held = before.get(code)
            if held is None:
                differences.append((code, sorted(codes), [], True))
                continue
            gained = sorted(codes - held)
            # A permission the role holds and the catalogue no longer grants.
            # Reported as well as the additions, because that is a *removal* of
            # authority and is the half somebody needs to approve rather than
            # skim.
            lost = sorted(held - codes)
            if gained or lost:
                differences.append((code, gained, lost, False))

        if not differences:
            self.stdout.write(f"  {organization.slug}: already current")
            return 0

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(organization.slug))
        for code, gained, lost, is_new in differences:
            label = f"    {code}" + (" (new role)" if is_new else "")
            self.stdout.write(label)
            if gained:
                self.stdout.write(self.style.SUCCESS(f"      + {', '.join(gained)}"))
            if lost:
                self.stdout.write(self.style.WARNING(f"      - {', '.join(lost)}"))

        # A permission in a role that is not in the catalogue at all means the
        # catalogue lost a code that a tenant still references. Worth saying
        # loudly: the role will keep granting a permission nothing checks, which
        # looks like authority and is not.
        orphans = {
            code for codes in before.values() for code in codes
        } - set(PERMISSION_CODES)
        if orphans:
            self.stdout.write(
                self.style.ERROR(
                    f"    these are granted but no longer exist in the "
                    f"catalogue: {', '.join(sorted(orphans))}"
                )
            )

        if not dry_run:
            seed_system_roles()
        return len(differences)
