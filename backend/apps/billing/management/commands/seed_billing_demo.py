"""Seed the service catalogue and run the billing cycle end to end.

Exercises, through the real service layer:

1. A service catalogue and two price lists — a general one and a discounted
   corporate rate.
2. Charge capture, showing that a corporate patient is priced differently
   from a general one for the same service.
3. Invoice, issue with a gapless number, and part payment then settlement.
4. A credit note reversing an issued invoice.
5. A refund blocked by segregation of duties, then allowed with a second
   approver.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.billing.fiscal import fiscal_year_for
from apps.billing.models import (
    PriceList,
    PriceListItem,
    ServiceCategory,
    ServiceItem,
    TaxTreatment,
)
from apps.billing.services import (
    capture_charge,
    create_invoice,
    credit_invoice,
    daily_collection,
    patient_account,
    record_payment,
    refund_payment,
)
from apps.common.exceptions import SegregationOfDutiesViolation
from apps.identity.models import User
from apps.organization.models import Department, Facility
from apps.patients.models import Patient, PatientStatus
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: (code, name, category, price, tax treatment, max discount %)
#:
#: Most clinical services in Nepal are VAT-exempt. Non-clinical ones -- an
#: ambulance hire, a private room -- are not, which is why the treatment is
#: per service rather than a global switch.
SERVICES = [
    ("REG-001", "New patient registration", ServiceCategory.REGISTRATION,
     "150.00", TaxTreatment.EXEMPT, "100.00"),
    ("CON-001", "General consultation", ServiceCategory.CONSULTATION,
     "800.00", TaxTreatment.EXEMPT, "20.00"),
    ("CON-002", "Specialist consultation", ServiceCategory.CONSULTATION,
     "1500.00", TaxTreatment.EXEMPT, "15.00"),
    ("CON-003", "Follow-up consultation", ServiceCategory.CONSULTATION,
     "400.00", TaxTreatment.EXEMPT, "50.00"),
    ("PRO-001", "Wound dressing", ServiceCategory.PROCEDURE,
     "500.00", TaxTreatment.EXEMPT, "20.00"),
    ("PRO-002", "Nebulisation", ServiceCategory.PROCEDURE,
     "350.00", TaxTreatment.EXEMPT, "20.00"),
    ("PRO-003", "Intramuscular injection", ServiceCategory.PROCEDURE,
     "200.00", TaxTreatment.EXEMPT, "20.00"),
    ("LAB-001", "Complete blood count", ServiceCategory.LABORATORY,
     "600.00", TaxTreatment.EXEMPT, "15.00"),
    ("LAB-002", "Random blood sugar", ServiceCategory.LABORATORY,
     "250.00", TaxTreatment.EXEMPT, "15.00"),
    ("LAB-003", "Liver function test", ServiceCategory.LABORATORY,
     "1200.00", TaxTreatment.EXEMPT, "15.00"),
    ("RAD-001", "Chest X-ray", ServiceCategory.RADIOLOGY,
     "900.00", TaxTreatment.EXEMPT, "15.00"),
    ("AMB-001", "Ambulance, within valley", ServiceCategory.AMBULANCE,
     "3000.00", TaxTreatment.STANDARD, "10.00"),
]

#: The corporate scheme pays less per item. Modelled as its own price list
#: rather than a blanket discount, because negotiated rates differ per service
#: -- a scheme may get 20% off consultations and nothing off laboratory work.
CORPORATE_PRICES = {
    "CON-001": "650.00",
    "CON-002": "1200.00",
    "CON-003": "320.00",
    "LAB-001": "500.00",
    "RAD-001": "750.00",
}


class Command(BaseCommand):
    help = "Seed the service catalogue and run a billing cycle."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError(f"No organization '{options['slug']}'.")

        cashier = User.objects.filter(email=f"manager@{options['slug']}.test").first()
        supervisor = User.objects.filter(email=f"owner@{options['slug']}.test").first()

        with tenant_context(context_for_organization(organization)):
            facility = Facility.objects.filter(facility_type="clinic").first()
            if facility is None:
                raise CommandError("No clinic facility. Run `seed_demo` first.")

            self.stdout.write(f"Fiscal year: {fiscal_year_for()}")
            services = self._catalogue(facility)
            self._price_lists(facility, services)
            self._general_patient(organization, facility, services, cashier)
            self._corporate_patient(organization, facility, services, cashier)
            self._credit_and_refund(
                organization, facility, services, cashier, supervisor
            )
            self._cash_up(facility)

    # -- catalogue -------------------------------------------------------

    def _catalogue(self, facility):
        department = Department.objects.filter(facility=facility, code="OPD").first()
        services = {}
        for code, name, category, price, tax, max_discount in SERVICES:
            service, _ = ServiceItem.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "department": department,
                    "default_price": Decimal(price),
                    "tax_treatment": tax,
                    "tax_rate": Decimal("13.00")
                    if tax == TaxTreatment.STANDARD
                    else Decimal("0.00"),
                    "max_discount_percent": Decimal(max_discount),
                    "is_active": True,
                },
            )
            services[code] = service
        self.stdout.write(f"  {len(services)} services in the catalogue")
        return services

    def _price_lists(self, facility, services):
        general, _ = PriceList.objects.update_or_create(
            code="general-2083",
            defaults={
                "name": "General price list",
                "patient_category": "",
                "effective_from": "2026-07-16",
                "priority": 100,
                "is_active": True,
            },
        )
        for code, service in services.items():
            PriceListItem.objects.update_or_create(
                price_list=general,
                service=service,
                defaults={"price": service.default_price},
            )

        corporate, _ = PriceList.objects.update_or_create(
            code="corporate-ntc-2083",
            defaults={
                "name": "Nepal Telecom corporate rates",
                "patient_category": "corporate",
                "payer_reference": "Nepal Telecom",
                "effective_from": "2026-07-16",
                # Higher priority so it wins over the general list for a
                # corporate patient.
                "priority": 200,
                "is_active": True,
            },
        )
        for code, price in CORPORATE_PRICES.items():
            PriceListItem.objects.update_or_create(
                price_list=corporate,
                service=services[code],
                defaults={"price": Decimal(price)},
            )
        self.stdout.write("  2 price lists: general, and a corporate rate")

    # -- 1. a general patient --------------------------------------------

    def _general_patient(self, organization, facility, services, cashier):
        patient = _live("Sita")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n1. General patient - {patient.full_name} ({patient.mrn})"))

        for code, quantity in [("CON-001", 1), ("LAB-001", 1), ("PRO-002", 2)]:
            charge = capture_charge(
                organization, patient, facility, services[code],
                actor=cashier, quantity=Decimal(quantity),
            )
            self.stdout.write(
                f"   {charge.service_code}  x{charge.quantity}  "
                f"@ {charge.unit_price}  = {charge.total}   [{charge.price_source}]"
            )

        invoice = create_invoice(
            organization, patient, facility, actor=cashier, issue=True
        )
        self.stdout.write(self.style.SUCCESS(
            f"   {invoice.number}  subtotal {invoice.subtotal}  "
            f"rounding {invoice.rounding_adjustment}  total {invoice.total}"))

        # Part payment, then the rest by wallet -- the common pattern.
        record_payment(invoice, Decimal("1000.00"), "cash", actor=cashier,
                       counter="Counter 1")
        invoice.refresh_from_db()
        self.stdout.write(f"   paid 1000 cash, balance {invoice.balance_due}, "
                          f"status {invoice.status}")

        record_payment(invoice, invoice.balance_due, "esewa", actor=cashier,
                       reference="ESW-77120034", counter="Counter 1")
        invoice.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f"   settled by eSewa, status {invoice.status}"))

    # -- 2. a corporate patient, same services, different price ----------

    def _corporate_patient(self, organization, facility, services, cashier):
        patient = _live("Bishnu")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n2. Corporate patient - {patient.full_name} "
            f"({patient.category}, {patient.corporate_account})"))

        for code in ("CON-001", "LAB-001"):
            charge = capture_charge(
                organization, patient, facility, services[code], actor=cashier
            )
            self.stdout.write(
                f"   {charge.service_code}  @ {charge.unit_price} "
                f"(list price {services[code].default_price})   "
                f"[{charge.price_source}]"
            )

        invoice = create_invoice(
            organization, patient, facility, actor=cashier, issue=True
        )
        self.stdout.write(self.style.SUCCESS(
            f"   {invoice.number}  total {invoice.total} — billed to "
            f"{invoice.payer_reference}"))
        record_payment(invoice, invoice.total, "credit", actor=cashier,
                       notes="On the corporate account")
        self.stdout.write("   settled on account")

    # -- 3. credit note, and a refund that duties block ------------------

    def _credit_and_refund(self, organization, facility, services, cashier,
                           supervisor):
        patient = _live("Kamala")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n3. Correction - {patient.full_name} ({patient.mrn})"))

        # Charged the wrong consultation type.
        capture_charge(organization, patient, facility, services["CON-002"],
                       actor=cashier)
        invoice = create_invoice(
            organization, patient, facility, actor=cashier, issue=True
        )
        payment = record_payment(invoice, invoice.total, "cash", actor=cashier,
                                 counter="Counter 1")
        self.stdout.write(f"   {invoice.number} raised for {invoice.total} "
                          f"and paid")

        credit = credit_invoice(
            invoice,
            reason="Charged as a specialist consultation in error; the "
                   "patient was seen by a general physician.",
            actor=supervisor,
        )
        invoice.refresh_from_db()
        self.stdout.write(self.style.WARNING(
            f"   {credit.number} credits {invoice.number} for {credit.total}; "
            f"original is now {invoice.status}"))

        # The cashier who took the money must not approve its return.
        try:
            refund_payment(payment, reason="Invoice credited in error.",
                           actor=cashier, approved_by=cashier)
            self.stdout.write(self.style.ERROR(
                "   BUG: the cashier refunded their own payment"))
        except SegregationOfDutiesViolation:
            self.stdout.write(
                "   refund by the same cashier correctly refused")

        refund = refund_payment(
            payment,
            reason="Invoice credited; consultation type corrected.",
            actor=cashier, approved_by=supervisor,
        )
        self.stdout.write(self.style.SUCCESS(
            f"   {refund.receipt_number} refunds {refund.amount} "
            f"(approved by the supervisor)"))

        account = patient_account(patient)
        self.stdout.write(f"   account: billed {account['total_billed']}, "
                          f"paid {account['total_paid']}, "
                          f"outstanding {account['outstanding']}")

    # -- 4. end of day ---------------------------------------------------

    def _cash_up(self, facility):
        report = daily_collection(facility)
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. End-of-day cash-up"))
        self.stdout.write(
            f"   gross {report['gross_collected']}, "
            f"refunded {report['refunded']}, net {report['net_collected']}")
        for method, row in report["by_method"].items():
            self.stdout.write(f"     {row['label']:<16} {row['total']}")
        self.stdout.write(
            f"   {report['invoices_issued']} invoices, "
            f"{report['credit_notes_issued']} credit notes, "
            f"{report['payment_count']} payments")


def _live(first_name: str):
    """The active record for a demo patient, never a merged tombstone."""
    return (
        Patient.objects.exclude(status=PatientStatus.MERGED)
        .filter(first_name=first_name)
        .order_by("registered_on")
        .first()
    )
