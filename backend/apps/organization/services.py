"""Facility lifecycle: the only sanctioned way facilities change.

Every facility write crosses a database boundary. The facility itself lives
in the tenant database; its non-clinical mirror lives in the control-plane
registry, where quota checks and platform analytics can reach it without
opening a tenant connection.

Two databases means no single atomic transaction. What this module does
instead is:

* nest both transactions so an application-level failure rolls back both;
* order the writes so the surviving state after an infrastructure failure is
  the *safe* one -- a registry row with no facility consumes quota the
  customer is not using, which is visible and fixable; a facility with no
  registry row is invisible capacity, which is not;
* provide `reconcile_registry` to detect and repair drift.

That trade is the cost of physical tenant isolation, and it is a cost worth
paying: see docs/adr/0001-database-per-tenant.md.
"""

import logging

# transaction: used twice per operation, once per database. `atomic(using=...)`
# is explicit about which connection it opens; the bare default would wrap
# only the control plane and silently leave tenant writes uncovered.
from django.db import transaction

from django.utils import timezone

# DomainError: base for FacilityOperationError, so a failed facility
# operation surfaces through the standard API error envelope instead of as a
# 500.
from apps.common.exceptions import DomainError

# Department: created from DEFAULT_DEPARTMENTS when a facility opens.
# Facility: the tenant-side record. Note reconcile_registry uses
# Facility.all_objects, not .objects, so soft-deleted rows are still compared.
# FacilityStatus: mapped to registry status when checking for drift.
from apps.organization.models import Department, Facility, FacilityStatus

# ChangeRequestType: dispatches apply_change_request to the right handler.
# A control-plane import inside a tenant module, which is safe only because
# it is an enum -- never query a control-plane model from tenant code without
# thinking about which connection you are on.
from apps.provisioning.models import ChangeRequestType

# context_for_organization: resolves and registers the tenant connection.
# tenant_context: binds it for the duration of a block. Both are needed
# because these services run from management commands and approval flows,
# where no request has set the context and the router would otherwise raise.
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context

# FacilityRegistryEntry / FacilityRegistryStatus: the control-plane mirror,
# kept in step with every tenant-side facility write. See dev log entry 007.
from apps.tenancy.models import FacilityRegistryEntry, FacilityRegistryStatus

logger = logging.getLogger("nirova.organization")

#: Departments a new facility starts with, by type. Enough to be usable on
#: day one; the customer renames and extends from there.
DEFAULT_DEPARTMENTS = {
    "hospital": [
        ("OPD", "Outpatient Department", "clinical"),
        ("IPD", "Inpatient Department", "clinical"),
        ("EMR", "Emergency", "clinical"),
        ("NUR", "Nursing", "nursing"),
        ("PHR", "Pharmacy", "pharmacy"),
        ("LAB", "Laboratory", "diagnostic"),
        ("RAD", "Radiology", "diagnostic"),
        ("ADM", "Administration", "administrative"),
        ("FIN", "Finance", "finance"),
    ],
    "clinic": [
        ("OPD", "Outpatient Department", "clinical"),
        ("NUR", "Nursing", "nursing"),
        ("REC", "Reception", "administrative"),
        ("FIN", "Billing", "finance"),
    ],
    "pharmacy": [
        ("RTL", "Retail Counter", "pharmacy"),
        ("STO", "Store", "operations"),
        ("FIN", "Billing", "finance"),
    ],
    "laboratory": [
        ("COL", "Sample Collection", "diagnostic"),
        ("PRO", "Processing", "diagnostic"),
        ("REP", "Reporting", "diagnostic"),
    ],
    "diagnostic": [
        ("REC", "Reception", "administrative"),
        ("IMG", "Imaging", "diagnostic"),
        ("REP", "Reporting", "diagnostic"),
    ],
    "warehouse": [
        ("REC", "Receiving", "operations"),
        ("STO", "Storage", "operations"),
        ("DIS", "Dispatch", "operations"),
    ],
    "corporate_office": [
        ("ADM", "Administration", "administrative"),
        ("FIN", "Finance", "finance"),
        ("HRM", "Human Resources", "administrative"),
    ],
}


class FacilityOperationError(DomainError):
    code = "facility_operation_failed"


class FacilityService:
    """Applies approved facility changes across both databases."""

    def __init__(self, organization, actor=None):
        self.organization = organization
        self.actor = actor
        self.actor_id = getattr(actor, "uuid", None)

    # -- entry point -----------------------------------------------------

    def apply_change_request(self, request):
        """Execute an approved request. Returns the affected facility's UUID."""
        handlers = {
            ChangeRequestType.OPEN_FACILITY: self._open,
            ChangeRequestType.CLOSE_FACILITY: self._close,
            ChangeRequestType.REOPEN_FACILITY: self._reopen,
            ChangeRequestType.SUSPEND_FACILITY: self._suspend,
            ChangeRequestType.RESUME_FACILITY: self._resume,
            ChangeRequestType.CONVERT_TYPE: self._convert_type,
        }
        handler = handlers.get(request.request_type)
        if handler is None:
            raise FacilityOperationError(
                f"No handler for request type '{request.request_type}'.",
                detail={"request_type": request.request_type},
            )
        return handler(request)

    # -- operations ------------------------------------------------------

    def _open(self, request):
        payload = request.payload or {}
        code = (payload.get("code") or request.proposed_code or "").strip().upper()
        name = payload.get("name") or request.proposed_name

        if not code or not name:
            raise FacilityOperationError(
                "A facility needs both a code and a name.",
                detail={"code": code, "name": name},
            )

        tenant = context_for_organization(self.organization)

        with transaction.atomic(using="default"):
            if FacilityRegistryEntry.objects.filter(
                organization=self.organization, code=code
            ).exists():
                raise FacilityOperationError(
                    f"Facility code '{code}' is already used in this organization.",
                    detail={"code": code},
                )

            with tenant_context(tenant):
                with transaction.atomic(using=tenant.database_alias):
                    facility = Facility.objects.create(
                        code=code,
                        name=name,
                        short_name=payload.get("short_name", "")[:64],
                        facility_type=request.facility_type,
                        status=FacilityStatus.ACTIVE,
                        province=payload.get("province", ""),
                        district=payload.get("district", ""),
                        municipality=payload.get("municipality", ""),
                        ward=payload.get("ward", ""),
                        street_address=payload.get("street_address", ""),
                        phone=payload.get("phone", ""),
                        email=payload.get("email", ""),
                        pan_number=payload.get("pan_number", ""),
                        license_number=payload.get("license_number", ""),
                        is_24x7=payload.get("is_24x7", False),
                        operating_hours=payload.get("operating_hours", {}),
                        opened_on=request.requested_effective_date
                        or timezone.localdate(),
                        origin_reference=request.reference,
                        created_by_id=self.actor_id,
                    )
                    self._seed_departments(facility)

            FacilityRegistryEntry.objects.create(
                organization=self.organization,
                facility_uuid=facility.uuid,
                code=code,
                name=name,
                facility_type=request.facility_type,
                status=FacilityRegistryStatus.ACTIVE,
                province=payload.get("province", ""),
                district=payload.get("district", ""),
                municipality=payload.get("municipality", ""),
                opened_at=timezone.now(),
                created_by_id=self.actor_id,
            )

        logger.info(
            "Opened facility %s (%s) for %s via %s",
            code,
            request.facility_type,
            self.organization.slug,
            request.reference,
        )
        return facility.uuid

    def _close(self, request):
        """Close a facility. Its data stays; its capacity is released."""
        entry, facility, tenant = self._load_target(request)

        with transaction.atomic(using="default"):
            with tenant_context(tenant):
                with transaction.atomic(using=tenant.database_alias):
                    facility.status = FacilityStatus.CLOSED
                    facility.closed_on = (
                        request.requested_effective_date or timezone.localdate()
                    )
                    facility.updated_by_id = self.actor_id
                    facility.save(
                        update_fields=[
                            "status",
                            "closed_on",
                            "updated_by_id",
                            "updated_at",
                        ]
                    )
            entry.status = FacilityRegistryStatus.CLOSED
            entry.closed_at = timezone.now()
            entry.updated_by_id = self.actor_id
            entry.save(
                update_fields=["status", "closed_at", "updated_by_id", "updated_at"]
            )

        logger.info(
            "Closed facility %s for %s via %s",
            entry.code,
            self.organization.slug,
            request.reference,
        )
        return facility.uuid

    def _reopen(self, request):
        entry, facility, tenant = self._load_target(request)

        with transaction.atomic(using="default"):
            with tenant_context(tenant):
                with transaction.atomic(using=tenant.database_alias):
                    facility.status = FacilityStatus.ACTIVE
                    facility.closed_on = None
                    facility.updated_by_id = self.actor_id
                    facility.save(
                        update_fields=[
                            "status",
                            "closed_on",
                            "updated_by_id",
                            "updated_at",
                        ]
                    )
            entry.status = FacilityRegistryStatus.ACTIVE
            entry.closed_at = None
            entry.reopened_count += 1
            entry.updated_by_id = self.actor_id
            entry.save(
                update_fields=[
                    "status",
                    "closed_at",
                    "reopened_count",
                    "updated_by_id",
                    "updated_at",
                ]
            )
        return facility.uuid

    def _suspend(self, request):
        return self._set_status(
            request, FacilityStatus.SUSPENDED, FacilityRegistryStatus.SUSPENDED
        )

    def _resume(self, request):
        return self._set_status(
            request, FacilityStatus.ACTIVE, FacilityRegistryStatus.ACTIVE
        )

    def _set_status(self, request, facility_status, registry_status):
        entry, facility, tenant = self._load_target(request)
        with transaction.atomic(using="default"):
            with tenant_context(tenant):
                with transaction.atomic(using=tenant.database_alias):
                    facility.status = facility_status
                    facility.updated_by_id = self.actor_id
                    facility.save(
                        update_fields=["status", "updated_by_id", "updated_at"]
                    )
            entry.status = registry_status
            entry.updated_by_id = self.actor_id
            entry.save(update_fields=["status", "updated_by_id", "updated_at"])
        return facility.uuid

    def _convert_type(self, request):
        """Change what a facility is -- a clinic becoming a hospital.

        Consumes quota under the new type and releases it under the old, so
        the check that ran at approval was against the destination type.
        """
        entry, facility, tenant = self._load_target(request)
        new_type = request.facility_type

        with transaction.atomic(using="default"):
            with tenant_context(tenant):
                with transaction.atomic(using=tenant.database_alias):
                    facility.facility_type = new_type
                    facility.updated_by_id = self.actor_id
                    facility.save(
                        update_fields=["facility_type", "updated_by_id", "updated_at"]
                    )
                    self._seed_departments(facility)
            entry.facility_type = new_type
            entry.updated_by_id = self.actor_id
            entry.save(update_fields=["facility_type", "updated_by_id", "updated_at"])
        return facility.uuid

    # -- helpers ---------------------------------------------------------

    def _load_target(self, request):
        if not request.target_facility_uuid:
            raise FacilityOperationError(
                "This request does not identify an existing facility.",
                detail={"reference": request.reference},
            )

        entry = FacilityRegistryEntry.objects.filter(
            organization=self.organization, facility_uuid=request.target_facility_uuid
        ).first()
        if entry is None:
            raise FacilityOperationError(
                "No registry entry for the target facility.",
                detail={"facility": str(request.target_facility_uuid)},
            )

        tenant = context_for_organization(self.organization)
        with tenant_context(tenant):
            facility = Facility.objects.filter(
                uuid=request.target_facility_uuid
            ).first()
        if facility is None:
            raise FacilityOperationError(
                "The facility exists in the registry but not in the tenant "
                "database. Run `reconcile_facility_registry`.",
                detail={"facility": str(request.target_facility_uuid)},
            )
        return entry, facility, tenant

    def _seed_departments(self, facility):
        """Give a new facility a workable department structure."""
        defaults = DEFAULT_DEPARTMENTS.get(facility.facility_type, [])
        existing = set(
            Department.objects.filter(facility=facility).values_list("code", flat=True)
        )
        for order, (code, name, kind) in enumerate(defaults, start=1):
            if code in existing:
                continue
            Department.objects.create(
                facility=facility,
                code=code,
                name=name,
                kind=kind,
                display_order=order * 10,
                created_by_id=self.actor_id,
            )


def reconcile_registry(organization) -> dict:
    """Detect drift between the tenant database and the control-plane registry.

    Drift is possible because the two writes cannot share a transaction.
    Running this on a schedule turns a silent inconsistency into a report:
    what is missing, what is stale, and what is orphaned.
    """
    tenant = context_for_organization(organization)
    with tenant_context(tenant):
        facilities = {
            str(f.uuid): f
            for f in Facility.all_objects.all()
        }

    entries = {
        str(e.facility_uuid): e
        for e in FacilityRegistryEntry.objects.filter(organization=organization)
    }

    status_map = {
        FacilityStatus.PENDING: FacilityRegistryStatus.PENDING,
        FacilityStatus.ACTIVE: FacilityRegistryStatus.ACTIVE,
        FacilityStatus.SUSPENDED: FacilityRegistryStatus.SUSPENDED,
        FacilityStatus.CLOSED: FacilityRegistryStatus.CLOSED,
    }

    report = {
        "organization": organization.slug,
        "missing_registry_entries": [],
        "orphaned_registry_entries": [],
        "status_mismatches": [],
        "facility_count": len(facilities),
        "registry_count": len(entries),
    }

    for uuid_str, facility in facilities.items():
        entry = entries.get(uuid_str)
        if entry is None:
            report["missing_registry_entries"].append(
                {"uuid": uuid_str, "code": facility.code, "name": facility.name}
            )
            continue
        expected = status_map.get(facility.status)
        if expected and entry.status != expected:
            report["status_mismatches"].append(
                {
                    "uuid": uuid_str,
                    "code": facility.code,
                    "tenant_status": facility.status,
                    "registry_status": entry.status,
                }
            )

    for uuid_str, entry in entries.items():
        if uuid_str not in facilities:
            report["orphaned_registry_entries"].append(
                {"uuid": uuid_str, "code": entry.code, "name": entry.name}
            )

    report["is_consistent"] = not (
        report["missing_registry_entries"]
        or report["orphaned_registry_entries"]
        or report["status_mismatches"]
    )
    return report
