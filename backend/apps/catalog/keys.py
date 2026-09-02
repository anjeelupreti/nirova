"""The vocabulary of entitlements: module codes, feature flags and limit keys.

Keys are stored as strings rather than as foreign keys to an enum table, so
a new limit can be introduced by defining a constant and pricing it -- no
migration, no deploy coupling between the commercial team and the schema.
The constants below are the *known* keys; the storage layer accepts others.

Never check `plan.code == "enterprise"` anywhere in the codebase. Ask the
entitlement service about a specific capability instead. Plans get renamed,
merged and discounted; capabilities are what the product actually gates on.
"""


class ModuleCode:
    """Top-level products an organization can be entitled to."""

    CLINIC = "clinic"
    HOSPITAL = "hospital"
    PHARMACY = "pharmacy"
    LABORATORY = "laboratory"
    RADIOLOGY = "radiology"
    BLOOD_BANK = "blood_bank"
    INVENTORY = "inventory"
    PROCUREMENT = "procurement"
    FINANCE = "finance"
    HRMS = "hrms"
    PAYROLL = "payroll"
    CRM = "crm"
    INSURANCE = "insurance"
    ANALYTICS = "analytics"
    ADVANCED_ANALYTICS = "advanced_analytics"
    PATIENT_PORTAL = "patient_portal"
    TELEMEDICINE = "telemedicine"
    MOBILE_APPS = "mobile_apps"
    API_ACCESS = "api_access"
    WAREHOUSE = "warehouse"
    DISTRIBUTION = "distribution"

    ALL = (
        CLINIC, HOSPITAL, PHARMACY, LABORATORY, RADIOLOGY, BLOOD_BANK,
        INVENTORY, PROCUREMENT, FINANCE, HRMS, PAYROLL, CRM, INSURANCE,
        ANALYTICS, ADVANCED_ANALYTICS, PATIENT_PORTAL, TELEMEDICINE,
        MOBILE_APPS, API_ACCESS, WAREHOUSE, DISTRIBUTION,
    )


class LimitKey:
    """Countable ceilings. A value of `None` means unlimited."""

    MAX_FACILITIES = "max_facilities"
    MAX_USERS = "max_users"
    MAX_EMPLOYEES = "max_employees"
    MAX_DEPARTMENTS_PER_FACILITY = "max_departments_per_facility"
    MAX_STORAGE_GB = "max_storage_gb"
    MAX_API_CALLS_PER_MONTH = "max_api_calls_per_month"
    MAX_SMS_PER_MONTH = "max_sms_per_month"
    MAX_PATIENTS = "max_patients"
    MAX_MONTHLY_TRANSACTIONS = "max_monthly_transactions"

    #: Per-facility-type ceilings, e.g. "max_facilities.pharmacy". These sit
    #: *under* MAX_FACILITIES: a customer entitled to 10 facilities of which
    #: at most 2 may be hospitals is a normal, expressible arrangement.
    FACILITY_TYPE_PREFIX = "max_facilities."

    @classmethod
    def for_facility_type(cls, facility_type: str) -> str:
        return f"{cls.FACILITY_TYPE_PREFIX}{facility_type}"

    @classmethod
    def is_facility_type_limit(cls, key: str) -> bool:
        return key.startswith(cls.FACILITY_TYPE_PREFIX)

    @classmethod
    def facility_type_from_key(cls, key: str) -> str | None:
        if not cls.is_facility_type_limit(key):
            return None
        return key[len(cls.FACILITY_TYPE_PREFIX):]


class FeatureFlag:
    """Boolean capabilities that are not themselves countable."""

    MULTI_FACILITY = "multi_facility"
    CENTRAL_PROCUREMENT = "central_procurement"
    CENTRAL_PAYROLL = "central_payroll"
    INTER_FACILITY_TRANSFER = "inter_facility_transfer"
    CUSTOM_REPORTS = "custom_reports"
    SCHEDULED_REPORTS = "scheduled_reports"
    WHITE_LABEL = "white_label"
    SSO = "sso"
    AUDIT_EXPORT = "audit_export"
    OFFLINE_MODE = "offline_mode"
    DICOM_PACS = "dicom_pacs"
    LAB_ANALYZER_INTERFACE = "lab_analyzer_interface"
    FHIR_API = "fhir_api"
    AI_ASSIST = "ai_assist"
    SELF_SERVICE_FACILITY_CREATION = "self_service_facility_creation"


class MeterKey:
    """Metered quantities. Feed usage-based pricing and quota checks alike."""

    ACTIVE_USERS = "active_users"
    ACTIVE_FACILITIES = "active_facilities"
    EMPLOYEES = "employees"
    PATIENTS = "patients"
    APPOINTMENTS = "appointments"
    PHARMACY_SALES = "pharmacy_sales"
    LAB_TESTS = "lab_tests"
    STORAGE_GB = "storage_gb"
    API_CALLS = "api_calls"
    SMS_SENT = "sms_sent"
    EMAIL_SENT = "email_sent"
    WHATSAPP_SENT = "whatsapp_sent"
    AI_TOKENS = "ai_tokens"
    REPORTS_GENERATED = "reports_generated"


#: Which module a facility type requires. Creating a pharmacy branch is not
#: only a question of "how many" -- the organization must have bought the
#: pharmacy module at all.
FACILITY_TYPE_MODULE = {
    "hospital": ModuleCode.HOSPITAL,
    "clinic": ModuleCode.CLINIC,
    "pharmacy": ModuleCode.PHARMACY,
    "laboratory": ModuleCode.LABORATORY,
    "diagnostic": ModuleCode.RADIOLOGY,
    "warehouse": ModuleCode.WAREHOUSE,
    "corporate_office": None,
    "other": None,
}
