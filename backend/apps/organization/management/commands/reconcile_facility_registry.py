"""Detect drift between tenant facilities and the control-plane registry."""

import json

from django.core.management.base import BaseCommand

from apps.organization.services import reconcile_registry
from apps.tenancy.models import Organization, OrganizationStatus


class Command(BaseCommand):
    help = "Report facility registry drift for one or all organizations."

    def add_arguments(self, parser):
        parser.add_argument("--slug", help="Limit to one organization.")

    def handle(self, *args, **options):
        queryset = Organization.objects.exclude(status=OrganizationStatus.PENDING)
        if options.get("slug"):
            queryset = queryset.filter(slug=options["slug"])

        drifted = 0
        for organization in queryset:
            try:
                report = reconcile_registry(organization)
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"  {organization.slug}: unreachable ({exc})")
                )
                continue

            if report["is_consistent"]:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {organization.slug}: consistent "
                        f"({report['facility_count']} facilities)"
                    )
                )
            else:
                drifted += 1
                self.stdout.write(self.style.WARNING(f"  {organization.slug}: DRIFT"))
                self.stdout.write(json.dumps(report, indent=2, default=str))

        if drifted:
            self.stdout.write(self.style.WARNING(f"{drifted} organization(s) drifted."))
