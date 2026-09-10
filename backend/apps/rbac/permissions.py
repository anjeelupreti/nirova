"""The permission catalogue and the scopes permissions are granted within.

Permissions are declared in code, not stored as rows to be invented at
runtime. A permission is a promise the application makes about what it
checks; letting an administrator type a new one would create a permission
nothing enforces. Roles -- which bundle permissions -- *are* data, and
customers create as many as they like.

Naming is `<resource>.<action>`, always lowercase, always singular resource.
"""

from dataclasses import dataclass


class Scope:
    """How far a granted permission reaches.

    The same permission means very different things at different scopes:
    `patient.read` at OWN_PATIENTS is a doctor seeing their own caseload; at
    ORGANIZATION it is a medical director seeing every patient in a hospital
    group. Scope is checked at query time, not just at the endpoint, so a
    scoped user gets a filtered list rather than a refusal.

    Ordered weakest to strongest; a stronger scope subsumes a weaker one.
    """

    OWN = "own"
    OWN_PATIENTS = "own_patients"
    UNIT = "unit"
    DEPARTMENT = "department"
    FACILITY = "facility"
    MULTI_FACILITY = "multi_facility"
    ORGANIZATION = "organization"

    ORDER = [OWN, OWN_PATIENTS, UNIT, DEPARTMENT, FACILITY, MULTI_FACILITY, ORGANIZATION]
    CHOICES = [
        (OWN, "Own records"),
        (OWN_PATIENTS, "Own patients"),
        (UNIT, "Own unit"),
        (DEPARTMENT, "Own department"),
        (FACILITY, "Own facility"),
        (MULTI_FACILITY, "Assigned facilities"),
        (ORGANIZATION, "Whole organization"),
    ]

    @classmethod
    def covers(cls, granted: str, required: str) -> bool:
        """Whether `granted` is at least as broad as `required`."""
        try:
            return cls.ORDER.index(granted) >= cls.ORDER.index(required)
        except ValueError:
            return False


@dataclass(frozen=True)
class PermissionDef:
    code: str
    label: str
    group: str
    description: str = ""
    #: Marks permissions that must not be held together with their
    #: counterpart by the same person -- the maker-checker rule. Enforced by
    #: `apps.rbac.services.check_segregation_of_duties`.
    conflicts_with: tuple = ()
    #: Actions on patient-identifiable data. Every use is written to the
    #: audit log with the record touched, regardless of other settings.
    is_sensitive: bool = False


def _p(code, label, group, description="", conflicts_with=(), is_sensitive=False):
    return PermissionDef(code, label, group, description, conflicts_with, is_sensitive)


PERMISSIONS: tuple[PermissionDef, ...] = (
    # -- organization & administration ----------------------------------
    _p("organization.read", "View organization", "Administration"),
    _p("organization.update", "Edit organization", "Administration"),
    _p("facility.read", "View facilities", "Administration"),
    _p("facility.request_change", "Request a facility change", "Administration",
       "Raise a request to open, close or convert a facility."),
    _p("facility.approve_change", "Approve a facility change", "Administration",
       "Decide facility change requests on behalf of the organization.",
       conflicts_with=("facility.request_change",)),
    _p("department.read", "View departments", "Administration"),
    _p("department.manage", "Manage departments", "Administration"),
    _p("config.read", "View configuration", "Administration"),
    _p("config.update", "Change configuration", "Administration"),
    # Maintaining a catalogue is not the same authority as changing the
    # organization's configuration, and conflating them was making the
    # write guards either useless or absurd: routing the product master
    # through `config.update` left **only the organization administrator**
    # able to add a medicine, which a pharmacy manager does weekly. A
    # permission that nobody appropriate holds is a workflow somebody will
    # route around.
    _p("catalog.manage", "Maintain catalogues: products, services, tests",
       "Administration"),
    # Bulk import is its own authority and deliberately not `catalog.manage` or
    # `patient.create`. Registering one patient at the counter is a clerk's job;
    # creating eight thousand from a spreadsheet is a migration, it happens two
    # or three times in a system's life, and a mistake in it is the hardest kind
    # to undo -- duplicate records with clinical history hanging off both.
    # Sensitive, so it shows in the sensitive-permission report and needs a
    # deliberate grant rather than arriving with a bundle.
    _p("data.import", "Import data in bulk", "Administration",
       "Upload, map, validate and commit a file of existing records.",
       is_sensitive=True),

    # -- identity & access ----------------------------------------------
    _p("user.read", "View users", "Access control"),
    _p("user.invite", "Invite users", "Access control"),
    _p("user.update", "Edit users", "Access control"),
    _p("user.deactivate", "Deactivate users", "Access control"),
    _p("role.read", "View roles", "Access control"),
    _p("role.manage", "Create and edit roles", "Access control"),
    _p("role.assign", "Assign roles to users", "Access control",
       conflicts_with=("role.manage",)),

    # -- clinical ---------------------------------------------------------
    # The three tiers of ACCESS_DESIGN.md. `patient.read` keeps its meaning --
    # identity, which every counter in the group needs in order to establish
    # who is standing in front of them -- and the two acts it used to imply
    # are separated out.
    _p("patient.read", "View patients", "Clinical", is_sensitive=True),
    # Deliberately generous, and what makes the rest safe to restrict: a
    # pharmacist without an allergy list is more dangerous than one who can
    # see too much.
    _p("patient.safety.read",
       "View allergies, active medicines and dosing-relevant conditions",
       "Clinical", is_sensitive=True),
    # The tier the privacy question is actually about, and the one Phase 2
    # puts behind a care relationship.
    _p("patient.clinical.read", "View the clinical record", "Clinical",
       is_sensitive=True),
    _p("patient.create", "Register patients", "Clinical", is_sensitive=True),
    _p("patient.update", "Edit patient records", "Clinical", is_sensitive=True),
    _p("patient.merge", "Merge duplicate patients", "Clinical", is_sensitive=True),
    _p("encounter.read", "View encounters", "Clinical", is_sensitive=True),
    _p("encounter.create", "Record encounters", "Clinical", is_sensitive=True),
    # Booking is a front-desk act, not a clinical one, and it had been borrowing
    # `encounter.create` for want of its own permission. That made the diary
    # unusable by the one role designed for it: `receptionist`'s description
    # reads "Registration, appointments and front-desk billing" and it could
    # not make an appointment. Granting it `encounter.create` instead was not
    # an option -- a permission's scope comes from the *assignment*, so a
    # facility-scoped receptionist would also have been able to record a blood
    # transfusion and run emergency triage, both of which check the same code
    # at facility scope.
    _p("visit.schedule", "Book appointments and issue queue tokens", "Clinical",
       "Give a patient a place to be seen: an appointment for a future date, "
       "or a token in today's queue. Cancelling and recording a no-show are "
       "the same authority."),
    _p("prescription.create", "Write prescriptions", "Clinical", is_sensitive=True),
    _p("prescription.approve", "Approve prescriptions", "Clinical",
       is_sensitive=True, conflicts_with=("prescription.create",)),
    _p("prescription.dispense", "Dispense prescriptions", "Clinical",
       is_sensitive=True),

    # -- inpatient --------------------------------------------------------
    #
    # Forcing past a blocked discharge is a permission of its own, separate
    # from the authority to discharge at all. It is the control that stops a
    # patient leaving with an unreconciled bill, so it is given to few people
    # and every use of it is logged.
    _p("discharge.override", "Override a blocked discharge", "Clinical",
       is_sensitive=True),
    _p("bed.manage", "Manage wards and beds", "Clinical"),
    # Double-booking a theatre is its own authority. It is a real decision an
    # emergency sometimes requires, and one a theatre committee asks about
    # afterwards, so it is given to a coordinator rather than to everybody who
    # can book a case.
    _p("theatre.override", "Double-book a theatre", "Clinical",
       is_sensitive=True),

    # -- laboratory and imaging -------------------------------------------
    #
    # Ordering a test is `encounter.create` -- it is a clinical decision
    # recorded in the encounter. What happens next is a different job done by
    # different people, and until now the whole of it ran on `encounter.read`:
    # collecting the sample, receiving or rejecting it, entering the result
    # and *verifying* it were all open to everybody who could see a diagnostic
    # order, which includes the front desk and a read-only auditor.
    #
    # Split in two because entering a result and releasing it are the
    # maker-checker pair a laboratory is built around. A technician performs
    # and enters; somebody else authorises before the number reaches the
    # chart and somebody treats a patient on it. Small labs in Nepal often
    # give both to a senior technician -- that is a customer's decision to
    # make in a role they create, and it stays visible because it is two
    # permissions rather than one.
    _p("diagnostic.process", "Collect samples and enter results", "Clinical",
       "Collect, receive or reject a sample, and record the result against "
       "the order. Does not release the result -- see `diagnostic.verify`.",
       is_sensitive=True),
    _p("diagnostic.verify", "Verify and release results", "Clinical",
       "Authorise a result so it reaches the patient's chart, and raise or "
       "close a critical-result notification. Deliberately separate from "
       "entering it.",
       is_sensitive=True, conflicts_with=("diagnostic.process",)),

    # -- blood bank -------------------------------------------------------
    #
    # **These exist because the blood bank was asking for a permission that
    # does not exist.** Every write in `apps/bloodbank/api.py` -- registering
    # a donor, grouping, screening, separating, releasing, issuing, discarding
    # and transfusing -- called `require("pharmacy.dispense")`. There is no
    # such code in this catalogue; the codes are `prescription.dispense` and
    # `stock.*`. `require` does not validate that a code exists, so the guard
    # did not fail loudly: it simply refused **everybody, forever**, and the
    # whole module was dead from the outside while its tests, which run as the
    # owner, passed. Found by probing the running stack as an auditor and
    # getting a 403 that was too good to be true.
    #
    # Two permissions rather than one, because a blood bank and a ward are two
    # places doing two jobs. The bank determines and releases; the ward
    # reserves, collects and transfuses. Conflating them would mean the
    # technician who screened a unit could also hang it, which is precisely
    # the separation a transfusion service is built around.
    _p("blood.process", "Run the blood bank", "Clinical",
       "Register and defer donors, collect donations, group, screen, "
       "separate into components, release into stock and discard. The bank's "
       "own work, up to the point a unit becomes available.",
       is_sensitive=True),
    _p("blood.issue", "Reserve, issue and transfuse blood", "Clinical",
       "Cross-match, reserve a unit for a patient, issue it to a ward, take "
       "it back, and record the transfusion and any reaction. The clinical "
       "use of what the bank released.",
       is_sensitive=True),

    # -- inventory --------------------------------------------------------
    _p("stock.read", "View stock", "Inventory"),
    _p("stock.adjust", "Raise stock adjustments", "Inventory"),
    _p("stock.approve_adjustment", "Approve stock adjustments", "Inventory",
       conflicts_with=("stock.adjust",)),
    _p("stock.transfer", "Transfer stock between locations", "Inventory"),
    _p("stock.count", "Perform stock counts", "Inventory"),

    # -- point of sale ----------------------------------------------------
    #
    # Kept apart from `invoice.*` because the counter is where cash is
    # physically handled, and the controls that matter there are about the
    # drawer rather than about the ledger. Three maker-checker pairs: whoever
    # sells cannot void, whoever asks for a return cannot approve it, and
    # whoever counted the till cannot be the one who signs the count off.
    _p("sale.read", "View counter sales", "Point of sale"),
    _p("sale.create", "Sell at the counter", "Point of sale"),
    _p("sale.void", "Void a completed sale", "Point of sale",
       is_sensitive=True, conflicts_with=("sale.create",)),
    _p("sale.return", "Raise a sales return", "Point of sale"),
    _p("sale.return_approve", "Approve a sales return", "Point of sale",
       is_sensitive=True, conflicts_with=("sale.return",)),
    _p("till.open", "Open and close a till session", "Point of sale"),
    _p("till.reconcile", "Sign off a till session", "Point of sale",
       is_sensitive=True, conflicts_with=("till.open",)),

    # -- procurement ------------------------------------------------------
    _p("purchase.read", "View purchases", "Procurement"),
    _p("purchase.create", "Raise purchase orders", "Procurement"),
    _p("purchase.approve", "Approve purchase orders", "Procurement",
       conflicts_with=("purchase.create",)),
    _p("supplier.manage", "Manage suppliers", "Procurement"),

    # -- finance ----------------------------------------------------------
    _p("invoice.read", "View invoices", "Finance"),
    _p("invoice.create", "Raise invoices", "Finance"),
    _p("payment.record", "Record payments", "Finance"),
    _p("refund.create", "Raise refunds", "Finance"),
    _p("refund.approve", "Approve refunds", "Finance",
       conflicts_with=("refund.create",)),
    _p("discount.approve", "Approve discounts beyond limit", "Finance"),
    # Keeping the ledger is not the same authority as raising invoices, and
    # the two in one pair of hands is the oldest fraud in bookkeeping: raise
    # an invoice, take the payment, and post a journal that hides both.
    _p("finance.post", "Post and reverse journal entries", "Finance",
       is_sensitive=True, conflicts_with=("invoice.create", "payment.record")),
    _p("finance.close", "Close and reopen accounting periods", "Finance",
       is_sensitive=True),

    # -- people -----------------------------------------------------------
    _p("employee.read", "View employees", "People", is_sensitive=True),
    _p("employee.manage", "Manage employees", "People", is_sensitive=True),
    # Hiring and separating are singled out from general record maintenance.
    # Correcting a phone number and ending someone's employment are not the
    # same authority, and a role that needs the first should not carry the
    # second by implication.
    _p("employee.hire", "Hire and onboard", "People", is_sensitive=True),
    _p("employee.separate", "End employment", "People", is_sensitive=True),
    _p("employee.transfer", "Transfer and promote", "People"),
    _p("position.manage", "Define positions and headcount", "People"),
    _p("credential.read", "View credentials", "People"),
    # Verification is what turns a claim into a fact, so it is a separate
    # authority from recording the claim -- and never held by the subject.
    _p("credential.verify", "Verify credentials", "People",
       is_sensitive=True, conflicts_with=("employee.manage",)),
    _p("salary.read", "View salaries and contracts", "People",
       is_sensitive=True),
    _p("attendance.read", "View attendance", "People"),
    _p("leave.approve", "Approve leave", "People"),
    _p("payroll.process", "Run payroll", "People"),
    _p("payroll.approve", "Approve payroll", "People",
       conflicts_with=("payroll.process",)),

    # -- notifications ----------------------------------------------------
    # Reading an inbox needs no permission: an inbox is not shared, and every
    # endpoint resolves the recipient from the caller. Broadcasting is the one
    # act that reaches other people, so it is the one that is gated.
    _p("notification.broadcast", "Send an announcement to the organization",
       "Notifications"),

    # -- privacy -----------------------------------------------------------
    # Reviewing emergency access (Phase 2). An override nobody reviews is not
    # a control, it is a log entry.
    _p("privacy.review", "Review emergency access to patient records",
       "Privacy", is_sensitive=True),

    # -- oversight --------------------------------------------------------
    _p("report.read", "View reports", "Oversight",
       "Operational and clinical reports: laboratory turnaround, theatre "
       "utilisation, ward occupancy, queue waits."),
    # **The books are not a report, and `report.read` was letting them be one.**
    # Seven finance endpoints hung off `report.read` -- the chart of accounts,
    # accounting periods, journal entries, bank accounts and their statements,
    # expenses, and the balance sheet, profit and loss, VAT return, trial
    # balance and ageing reports. `doctor` holds `report.read`, entirely
    # reasonably, for laboratory turnaround and theatre utilisation. It meant
    # every doctor in the hospital could read the general ledger and the bank
    # statements.
    #
    # The same defect as `attendance.read` meaning both "my attendance" and
    # "everybody's" (log 255): one permission answering two different
    # questions, and the coarser answer wins.
    _p("finance.read", "Read the books", "Finance",
       "The ledger, the chart of accounts, bank accounts, expenses and the "
       "financial statements. Separate from `report.read`, which is "
       "operational reporting."),
    _p("report.build", "Build custom reports", "Oversight"),
    _p("analytics.read", "View analytics", "Oversight"),
    _p("audit.read", "View the audit log", "Oversight"),
    _p("audit.export", "Export the audit log", "Oversight"),
    _p("subscription.read", "View subscription and usage", "Oversight"),
)

PERMISSION_MAP = {p.code: p for p in PERMISSIONS}
PERMISSION_CODES = frozenset(PERMISSION_MAP)
SENSITIVE_PERMISSIONS = frozenset(p.code for p in PERMISSIONS if p.is_sensitive)


def conflicting_permissions(codes) -> list[tuple[str, str]]:
    """Pairs within `codes` that segregation of duties forbids together."""
    held = set(codes)
    conflicts = []
    for code in held:
        definition = PERMISSION_MAP.get(code)
        if definition is None:
            continue
        for other in definition.conflicts_with:
            if other in held:
                pair = tuple(sorted((code, other)))
                if pair not in conflicts:
                    conflicts.append(pair)
    return conflicts


def grouped_permissions() -> dict:
    """Permissions by group, for rendering the role editor."""
    groups: dict[str, list] = {}
    for definition in PERMISSIONS:
        groups.setdefault(definition.group, []).append(
            {
                "code": definition.code,
                "label": definition.label,
                "description": definition.description,
                "is_sensitive": definition.is_sensitive,
                "conflicts_with": list(definition.conflicts_with),
            }
        )
    return groups
