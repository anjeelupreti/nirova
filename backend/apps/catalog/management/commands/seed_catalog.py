"""Seed the commercial catalogue: modules, features, plans and add-ons.

Prices are illustrative NPR figures for the Nepal market and are meant to be
replaced by whatever the commercial team actually decides. The *shape* is the
part that matters: plans carry limits per facility type, and add-ons exist so
a customer who needs one more pharmacy buys one more pharmacy rather than
being pushed onto a tier built for someone else.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.keys import FeatureFlag, LimitKey, MeterKey, ModuleCode
from apps.catalog.models import (
    AddOn,
    AddOnKind,
    BillingInterval,
    Enforcement,
    Feature,
    Module,
    Plan,
    PlanFeature,
    PlanLimit,
    PlanModule,
    UsageMeterDefinition,
)

MODULES = [
    (ModuleCode.CLINIC, "Clinic OS", "Registration, appointments, OPD and EMR.", True),
    (ModuleCode.HOSPITAL, "Hospital OS", "IPD, wards, emergency, theatre and ICU.", False),
    (ModuleCode.PHARMACY, "Pharmacy OS", "Dispensing, POS, batches and expiry.", False),
    (ModuleCode.LABORATORY, "Laboratory / LIMS", "Samples, results and quality control.", False),
    (ModuleCode.RADIOLOGY, "Radiology / RIS", "Modalities, worklists and reporting.", False),
    (ModuleCode.BLOOD_BANK, "Blood Bank", "Donors, components and cross-matching.", False),
    (ModuleCode.INVENTORY, "Inventory", "Stock, batches, transfers and counts.", True),
    (ModuleCode.PROCUREMENT, "Procurement", "Requisitions, purchase orders and receipts.", False),
    (ModuleCode.FINANCE, "Finance", "Ledger, receivables, payables and tax.", False),
    (ModuleCode.HRMS, "HRMS", "Employees, attendance, leave and rosters.", False),
    (ModuleCode.PAYROLL, "Payroll", "Nepal payroll, SSF, PF, CIT and TDS.", False),
    (ModuleCode.CRM, "Patient CRM", "Feedback, campaigns and follow-up.", False),
    (ModuleCode.INSURANCE, "Insurance / TPA", "Policies, pre-authorisation and claims.", False),
    (ModuleCode.ANALYTICS, "Analytics", "Standard dashboards and reports.", True),
    (ModuleCode.ADVANCED_ANALYTICS, "Advanced Analytics", "Custom reports and forecasting.", False),
    (ModuleCode.PATIENT_PORTAL, "Patient Portal", "Self-service records and appointments.", False),
    (ModuleCode.TELEMEDICINE, "Telemedicine", "Remote consultations.", False),
    (ModuleCode.MOBILE_APPS, "Mobile Apps", "Doctor, nurse, pharmacist and patient apps.", False),
    (ModuleCode.API_ACCESS, "API Access", "REST API, webhooks and FHIR.", False),
    (ModuleCode.WAREHOUSE, "Warehouse", "Central stores and inter-branch supply.", False),
    (ModuleCode.DISTRIBUTION, "Distribution", "Wholesale and dealer management.", False),
]

MODULE_DEPENDENCIES = {
    ModuleCode.PAYROLL: [ModuleCode.HRMS],
    ModuleCode.PHARMACY: [ModuleCode.INVENTORY],
    ModuleCode.LABORATORY: [ModuleCode.INVENTORY],
    ModuleCode.BLOOD_BANK: [ModuleCode.LABORATORY],
    ModuleCode.ADVANCED_ANALYTICS: [ModuleCode.ANALYTICS],
    ModuleCode.DISTRIBUTION: [ModuleCode.WAREHOUSE, ModuleCode.INVENTORY],
    ModuleCode.WAREHOUSE: [ModuleCode.INVENTORY],
}

FEATURES = [
    (FeatureFlag.MULTI_FACILITY, "Multiple facilities", None),
    (FeatureFlag.SELF_SERVICE_FACILITY_CREATION, "Self-service facility opening", None),
    (FeatureFlag.CENTRAL_PROCUREMENT, "Central procurement", ModuleCode.PROCUREMENT),
    (FeatureFlag.CENTRAL_PAYROLL, "Central payroll", ModuleCode.PAYROLL),
    (FeatureFlag.INTER_FACILITY_TRANSFER, "Inter-facility stock transfer", ModuleCode.INVENTORY),
    (FeatureFlag.CUSTOM_REPORTS, "Custom report builder", ModuleCode.ADVANCED_ANALYTICS),
    (FeatureFlag.SCHEDULED_REPORTS, "Scheduled reports", ModuleCode.ANALYTICS),
    (FeatureFlag.WHITE_LABEL, "White labelling", None),
    (FeatureFlag.SSO, "Single sign-on", None),
    (FeatureFlag.AUDIT_EXPORT, "Audit log export", None),
    (FeatureFlag.OFFLINE_MODE, "Offline / degraded mode", None),
    (FeatureFlag.DICOM_PACS, "DICOM and PACS", ModuleCode.RADIOLOGY),
    (FeatureFlag.LAB_ANALYZER_INTERFACE, "Analyser interfacing", ModuleCode.LABORATORY),
    (FeatureFlag.FHIR_API, "FHIR API", ModuleCode.API_ACCESS),
    (FeatureFlag.AI_ASSIST, "AI assistance", None),
]

#: (code, name, tagline, price, trial, modules, features, limits)
#:
#: Limits are where the facility rules live. `None` means unlimited; an
#: absent per-type key inherits the overall facility ceiling, so a plan only
#: has to state the types it wants to treat differently.
PLANS = [
    {
        "code": "starter",
        "name": "Starter",
        "tagline": "One clinic or one pharmacy, up and running.",
        "price": Decimal("4500.00"),
        "trial_days": 30,
        "modules": [ModuleCode.CLINIC, ModuleCode.PHARMACY, ModuleCode.INVENTORY,
                    ModuleCode.ANALYTICS],
        "features": [FeatureFlag.SELF_SERVICE_FACILITY_CREATION],
        "limits": {
            LimitKey.MAX_FACILITIES: 1,
            LimitKey.MAX_USERS: 10,
            LimitKey.MAX_STORAGE_GB: 20,
            LimitKey.MAX_PATIENTS: 5000,
            LimitKey.for_facility_type("hospital"): 0,
            LimitKey.for_facility_type("laboratory"): 0,
            LimitKey.for_facility_type("warehouse"): 0,
        },
    },
    {
        "code": "professional",
        "name": "Professional",
        "tagline": "A growing practice with a few branches.",
        "price": Decimal("16000.00"),
        "trial_days": 21,
        "modules": [ModuleCode.CLINIC, ModuleCode.PHARMACY, ModuleCode.LABORATORY,
                    ModuleCode.INVENTORY, ModuleCode.PROCUREMENT, ModuleCode.FINANCE,
                    ModuleCode.HRMS, ModuleCode.ANALYTICS, ModuleCode.CRM,
                    ModuleCode.PATIENT_PORTAL, ModuleCode.MOBILE_APPS],
        "features": [FeatureFlag.MULTI_FACILITY, FeatureFlag.SELF_SERVICE_FACILITY_CREATION,
                     FeatureFlag.INTER_FACILITY_TRANSFER, FeatureFlag.SCHEDULED_REPORTS,
                     FeatureFlag.AUDIT_EXPORT],
        "limits": {
            LimitKey.MAX_FACILITIES: 5,
            LimitKey.MAX_USERS: 60,
            LimitKey.MAX_STORAGE_GB: 200,
            LimitKey.MAX_PATIENTS: 50000,
            LimitKey.for_facility_type("hospital"): 0,
            LimitKey.for_facility_type("pharmacy"): 3,
            LimitKey.for_facility_type("laboratory"): 2,
            LimitKey.for_facility_type("warehouse"): 1,
        },
    },
    {
        "code": "hospital",
        "name": "Hospital",
        "tagline": "A full hospital, with wards, theatre and diagnostics.",
        "price": Decimal("55000.00"),
        "trial_days": 14,
        "modules": [ModuleCode.CLINIC, ModuleCode.HOSPITAL, ModuleCode.PHARMACY,
                    ModuleCode.LABORATORY, ModuleCode.RADIOLOGY, ModuleCode.BLOOD_BANK,
                    ModuleCode.INVENTORY, ModuleCode.PROCUREMENT, ModuleCode.FINANCE,
                    ModuleCode.HRMS, ModuleCode.PAYROLL, ModuleCode.INSURANCE,
                    ModuleCode.CRM, ModuleCode.ANALYTICS, ModuleCode.PATIENT_PORTAL,
                    ModuleCode.TELEMEDICINE, ModuleCode.MOBILE_APPS,
                    ModuleCode.WAREHOUSE],
        "features": [FeatureFlag.MULTI_FACILITY, FeatureFlag.INTER_FACILITY_TRANSFER,
                     FeatureFlag.CENTRAL_PROCUREMENT, FeatureFlag.CENTRAL_PAYROLL,
                     FeatureFlag.SCHEDULED_REPORTS, FeatureFlag.AUDIT_EXPORT,
                     FeatureFlag.DICOM_PACS, FeatureFlag.LAB_ANALYZER_INTERFACE,
                     FeatureFlag.OFFLINE_MODE],
        "limits": {
            LimitKey.MAX_FACILITIES: 12,
            LimitKey.MAX_USERS: 400,
            LimitKey.MAX_STORAGE_GB: 2000,
            LimitKey.MAX_PATIENTS: 500000,
            LimitKey.for_facility_type("hospital"): 2,
            LimitKey.for_facility_type("pharmacy"): 4,
            LimitKey.for_facility_type("laboratory"): 3,
            LimitKey.for_facility_type("warehouse"): 2,
        },
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "tagline": "Healthcare groups and chains, negotiated per contract.",
        "price": Decimal("180000.00"),
        "trial_days": 0,
        "is_public": False,
        "modules": ModuleCode.ALL,
        "features": [f[0] for f in FEATURES],
        "limits": {
            # Unlimited overall, but hospitals stay countable: they are the
            # expensive thing to support, and a contract that says
            # "unlimited everything" is a contract nobody can price.
            LimitKey.MAX_FACILITIES: None,
            LimitKey.MAX_USERS: None,
            LimitKey.MAX_PATIENTS: None,
            LimitKey.MAX_STORAGE_GB: 20000,
            LimitKey.for_facility_type("hospital"): 10,
        },
    },
]

ADDONS = [
    ("extra_clinic", "Additional clinic", AddOnKind.LIMIT_INCREMENT,
     LimitKey.for_facility_type("clinic"), 1, Decimal("3500.00")),
    ("extra_pharmacy", "Additional pharmacy", AddOnKind.LIMIT_INCREMENT,
     LimitKey.for_facility_type("pharmacy"), 1, Decimal("3000.00")),
    ("extra_laboratory", "Additional laboratory", AddOnKind.LIMIT_INCREMENT,
     LimitKey.for_facility_type("laboratory"), 1, Decimal("4500.00")),
    ("extra_hospital", "Additional hospital", AddOnKind.LIMIT_INCREMENT,
     LimitKey.for_facility_type("hospital"), 1, Decimal("28000.00")),
    ("extra_warehouse", "Additional warehouse", AddOnKind.LIMIT_INCREMENT,
     LimitKey.for_facility_type("warehouse"), 1, Decimal("2500.00")),
    ("facility_pack_5", "Five additional facilities", AddOnKind.LIMIT_INCREMENT,
     LimitKey.MAX_FACILITIES, 5, Decimal("12000.00")),
    ("user_pack_25", "Twenty-five additional users", AddOnKind.LIMIT_INCREMENT,
     LimitKey.MAX_USERS, 25, Decimal("5000.00")),
    ("storage_100gb", "100 GB additional storage", AddOnKind.LIMIT_INCREMENT,
     LimitKey.MAX_STORAGE_GB, 100, Decimal("1500.00")),
    ("module_hospital", "Hospital module", AddOnKind.MODULE,
     ModuleCode.HOSPITAL, 1, Decimal("32000.00")),
    ("module_clinic", "Clinic module", AddOnKind.MODULE,
     ModuleCode.CLINIC, 1, Decimal("6000.00")),
    ("module_pharmacy", "Pharmacy module", AddOnKind.MODULE,
     ModuleCode.PHARMACY, 1, Decimal("7000.00")),
    ("module_laboratory", "Laboratory module", AddOnKind.MODULE,
     ModuleCode.LABORATORY, 1, Decimal("9000.00")),
    ("module_warehouse", "Warehouse module", AddOnKind.MODULE,
     ModuleCode.WAREHOUSE, 1, Decimal("5000.00")),
    ("module_payroll", "Payroll module", AddOnKind.MODULE,
     ModuleCode.PAYROLL, 1, Decimal("8000.00")),
    ("module_radiology", "Radiology module", AddOnKind.MODULE,
     ModuleCode.RADIOLOGY, 1, Decimal("12000.00")),
    ("module_insurance", "Insurance and TPA module", AddOnKind.MODULE,
     ModuleCode.INSURANCE, 1, Decimal("9000.00")),
    ("module_blood_bank", "Blood bank module", AddOnKind.MODULE,
     ModuleCode.BLOOD_BANK, 1, Decimal("11000.00")),
]

METERS = [
    (MeterKey.ACTIVE_USERS, "Active users", "users", LimitKey.MAX_USERS, False),
    (MeterKey.ACTIVE_FACILITIES, "Active facilities", "facilities",
     LimitKey.MAX_FACILITIES, False),
    (MeterKey.PATIENTS, "Patients", "patients", LimitKey.MAX_PATIENTS, False),
    (MeterKey.APPOINTMENTS, "Appointments", "count", "", False),
    (MeterKey.PHARMACY_SALES, "Pharmacy sales", "count", "", False),
    (MeterKey.LAB_TESTS, "Laboratory tests", "count", "", False),
    (MeterKey.STORAGE_GB, "Storage used", "GB", LimitKey.MAX_STORAGE_GB, True),
    (MeterKey.API_CALLS, "API calls", "count", LimitKey.MAX_API_CALLS_PER_MONTH, True),
    (MeterKey.SMS_SENT, "SMS sent", "count", LimitKey.MAX_SMS_PER_MONTH, True),
]


#: Which limits block, and which merely warn or bill. See the comment in
#: _seed_plans for the reasoning behind each.
SOFT_LIMITS = {LimitKey.MAX_PATIENTS}
METERED_LIMITS = {LimitKey.MAX_STORAGE_GB}


def _enforcement_for(key: str) -> str:
    if key in METERED_LIMITS:
        return Enforcement.METERED
    if key in SOFT_LIMITS:
        return Enforcement.SOFT
    return Enforcement.HARD


class Command(BaseCommand):
    help = "Seed modules, features, plans, add-ons and usage meters."

    @transaction.atomic
    def handle(self, *args, **options):
        modules = self._seed_modules()
        features = self._seed_features(modules)
        self._seed_plans(modules, features)
        self._seed_addons()
        self._seed_meters()
        self.stdout.write(self.style.SUCCESS("Catalogue seeded."))

    def _seed_modules(self):
        modules = {}
        for order, (code, name, description, is_core) in enumerate(MODULES, start=1):
            module, _ = Module.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "description": description,
                    "is_core": is_core,
                    "display_order": order * 10,
                    "is_active": True,
                },
            )
            modules[code] = module

        for code, dependencies in MODULE_DEPENDENCIES.items():
            modules[code].depends_on.set([modules[d] for d in dependencies])

        self.stdout.write(f"  modules: {len(modules)}")
        return modules

    def _seed_features(self, modules):
        features = {}
        for code, name, module_code in FEATURES:
            feature, _ = Feature.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "module": modules.get(module_code) if module_code else None,
                    "is_active": True,
                },
            )
            features[code] = feature
        self.stdout.write(f"  features: {len(features)}")
        return features

    def _seed_plans(self, modules, features):
        for order, spec in enumerate(PLANS, start=1):
            plan, _ = Plan.objects.update_or_create(
                code=spec["code"],
                defaults={
                    "name": spec["name"],
                    "tagline": spec["tagline"],
                    "base_price": spec["price"],
                    "currency": "NPR",
                    "billing_interval": BillingInterval.MONTHLY,
                    "trial_days": spec["trial_days"],
                    "grace_days": 7,
                    "is_public": spec.get("is_public", True),
                    "is_active": True,
                    "display_order": order * 10,
                },
            )

            PlanModule.objects.filter(plan=plan).hard_delete()
            for module_code in spec["modules"]:
                PlanModule.objects.create(
                    plan=plan, module=modules[module_code], is_included=True
                )

            PlanFeature.objects.filter(plan=plan).hard_delete()
            for feature_code in spec["features"]:
                PlanFeature.objects.create(
                    plan=plan, feature=features[feature_code], is_enabled=True
                )

            PlanLimit.objects.filter(plan=plan).hard_delete()
            for key, value in spec["limits"].items():
                PlanLimit.objects.create(
                    plan=plan,
                    key=key,
                    value=value,
                    # Not every ceiling is a wall, and which ones are is a
                    # clinical decision as much as a commercial one.
                    #
                    #   storage  -> METERED. Refusing to save a scan because a
                    #               customer is 2 GB over is not a call a
                    #               healthcare system should make on its own.
                    #   patients -> SOFT. A clinic that has outgrown its plan
                    #               must still be able to register the sick
                    #               person in front of them. The overage is
                    #               flagged for the account team, who can have
                    #               a commercial conversation the next morning.
                    #   facilities and users -> HARD. Both are deliberate,
                    #               reversible administrative acts with nobody
                    #               waiting on them.
                    enforcement=_enforcement_for(key),
                    overage_unit_price=self._overage_price_for(key),
                    warn_at_percent=80,
                )
            self.stdout.write(f"  plan: {plan.code} ({len(spec['limits'])} limits)")

    @staticmethod
    def _overage_price_for(key):
        return Decimal("20.00") if key == LimitKey.MAX_STORAGE_GB else None

    def _seed_addons(self):
        for code, name, kind, target, increment, price in ADDONS:
            AddOn.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "kind": kind,
                    "target_key": target,
                    "increment": increment,
                    "unit_price": price,
                    "currency": "NPR",
                    "billing_interval": BillingInterval.MONTHLY,
                    # Facility add-ons are approved by platform staff, since
                    # they are attached as part of deciding a facility
                    # request rather than bought self-service.
                    "requires_approval": kind == AddOnKind.LIMIT_INCREMENT,
                    "is_active": True,
                },
            )
        self.stdout.write(f"  add-ons: {len(ADDONS)}")

    def _seed_meters(self):
        for key, name, unit, limit_key, is_billable in METERS:
            UsageMeterDefinition.objects.update_or_create(
                key=key,
                defaults={
                    "name": name,
                    "unit": unit,
                    "limit_key": limit_key,
                    "is_billable": is_billable,
                    "is_active": True,
                },
            )
        self.stdout.write(f"  meters: {len(METERS)}")
