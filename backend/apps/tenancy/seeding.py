"""The order the demo seeds must run in, in one place.

This list used to live inside `tests/test_seeds.py`, which was fine while the
test suite was its only consumer. The `bootstrap` command needs the same order
-- it builds the same demo estate, just outside pytest -- and two copies of a
dependency order is two things to forget to update. So the order lives here and
both import it.

**Order matters and is deliberate.** Each seed runs against what the previous
ones left behind, because that is where the interactions live: the prescription
collision only appears when the nursing seed runs after the clinical seeds.
"""

#: Seeds that run inside a provisioned tenant, in dependency order.
#:
#: **This order was measured, not reasoned about.** The list this replaced
#: lived in `tests/test_seeds.py` and called itself a dependency order while
#: running billing first and the clinical seeds thirteenth. It passed for a
#: year because the test fixture does not build a tenant -- it attaches to
#: whichever `manakamana` database the developer already has, which by then
#: has patients in it from earlier manual runs. Nothing had ever run these
#: against an genuinely empty tenant until a container did, and the first
#: seed failed on `patient.full_name` where `patient` was None.
#:
#: The order below was established by running the sequence from an empty
#: database until it completed. If you add a seed, add it here and run
#: `manage.py bootstrap` against a fresh database -- not against yours.
TENANT_SEEDS = [
    # Foundations. Staff before anything that assigns work to them, patients
    # before anything that charges, treats or admits one.
    "seed_hr_demo",
    "seed_clinical_demo",
    "seed_consultation_demo",
    # Money. Services and prices must exist before a charge can be captured,
    # and invoices before insurance can claim against them.
    "seed_billing_demo",
    "seed_finance_demo",
    "seed_insurance_demo",
    # Clinical services ordered from a consultation.
    "seed_diagnostics_demo",
    "seed_pharmacy_demo",
    "seed_procurement_demo",
    "seed_pos_demo",
    # Workforce operations, which need the workforce seeded above.
    "seed_attendance_demo",
    "seed_ess_demo",
    "seed_payroll_demo",
    # Inpatient and the departments that hand patients to each other.
    "seed_inpatient_demo",
    "seed_nurse_demo",
    "seed_emergency_demo",
    "seed_icu_demo",
    "seed_theatre_demo",
    "seed_bloodbank_demo",
    "seed_referrals_demo",
    "seed_portal_demo",
    # Late, because it reports on what everything above raised.
    "seed_notifications_demo",
    # Last, and the only one that goes through HTTP. Every other seed runs at
    # the service layer, *below* the permission classes -- so they prove
    # enforcement did not break the domain logic and prove nothing about who
    # can open what. On its first run this found that diagnostic orders were
    # narrowed on retrieve and not on list.
    "seed_access_demo",
]

#: Control-plane seeds, which must run before any tenant exists to be seeded.
#: `seed_catalog` writes the plans and add-ons a subscription refers to;
#: `seed_demo` buys one of those plans and provisions the tenant database.
CONTROL_PLANE_SEEDS = ["seed_catalog", "seed_demo"]
