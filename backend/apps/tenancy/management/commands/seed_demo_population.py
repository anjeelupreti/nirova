"""The population a demo hospital would already have: people and a shelf.

**The narrative seeds register six patients and stock five products**, because
each was written to demonstrate one mechanism — FEFO needs one antibiotic in
three batches, a drug-allergy check needs one allergic patient — and six people
and five products is enough for a mechanism. It is not enough for a hospital.
A buyer opening the patient index finds a page that ends after six rows; the
stock screen, the expiry report and the reorder list are three near-empty
tables; and a day generated from that pool puts the same six people through
the emergency department, the outpatient queue and the pharmacy counter at the
same time.

This fills in what an established Kathmandu-valley group would plausibly have
on file, **once**, and then leaves it alone:

* **A register of people**, spread across ages, genders, districts and blood
  groups the way a valley OPD's catchment is — including children, the
  elderly, a stated rather than known date of birth, and patients with no
  phone, because those are the records that break forms.
* **A formulary**, with Nepali manufacturers and brands at plausible retail
  prices, stocked in batches through the stock ledger. Some lines are
  deliberately low, some near expiry, one in the cold chain — so the reorder,
  expiry and storage screens each have something true to say.
* **An inpatient estate** at the hospital: medical, surgical, maternity,
  children's and high-dependency wards, fifty-odd beds in gendered bays with
  the equipment each would really have. The narrative seed's three wards and
  thirteen beds demonstrate transfer and discharge; they do not look like a
  hospital. Who is *in* the beds is today's business, and `seed_demo_day`
  keeps it moving; this builds the rooms. A few beds start out of service for
  a stated reason, because a board where every bed is either full or free is a
  board nobody who has worked a ward believes.

**Idempotent up to a floor.** Patients are topped up to a number, never added
to it, and each product and batch is created once by its code. Running it
twice changes nothing; running it after somebody registered real patients in
the demo tenant adds fewer.

**Through the service layer.** Patients go through `register_patient`, which
checks the plan's patient quota and allocates MRNs exactly as the front desk
would; stock goes through `post_movement`, the only way stock enters the
ledger.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.identity.models import User
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization

#: How many people the register should hold at least.
#:
#: Enough for one day to draw on without meeting itself: forty in ward beds,
#: a dozen through the emergency department and as many again through the
#: outpatient queue, with the rest of the register left for the patient list
#: to be a list.
PATIENT_FLOOR = 160

FEMALE = ["Sita", "Gita", "Anjali", "Sunita", "Laxmi", "Sarita", "Kamala",
          "Pooja", "Asmita", "Nirmala", "Radha", "Srijana", "Manisha", "Bishnu",
          "Rekha", "Sabina", "Pratiksha", "Samjhana", "Durga", "Aarati"]
MALE = ["Ram", "Hari", "Krishna", "Bikash", "Suman", "Rajesh", "Dipak",
        "Prakash", "Nabin", "Santosh", "Anil", "Sagar", "Bishal", "Ramesh",
        "Kiran", "Sujan", "Binod", "Gopal", "Arjun", "Mohan"]
MIDDLE_MALE = ["Bahadur", "Prasad", "Kumar", "Raj", "", "", "", ""]
MIDDLE_FEMALE = ["Kumari", "Devi", "Maya", "", "", "", ""]
SURNAMES = ["Shrestha", "Tamang", "Gurung", "Magar", "Rai", "Limbu", "Thapa",
            "Karki", "Adhikari", "Sharma", "Poudel", "Maharjan", "Bajracharya",
            "Shakya", "Khadka", "Basnet", "Lama", "Sherpa", "Yadav", "Chaudhary",
            "Bhandari", "Joshi", "K.C.", "Dahal"]

#: (district, municipality, weight) — the valley first, as a valley group's
#: catchment would be, then the districts people travel in from.
PLACES = [
    ("Kathmandu", "Kathmandu Metropolitan City", 9),
    ("Lalitpur", "Lalitpur Metropolitan City", 5),
    ("Bhaktapur", "Bhaktapur Municipality", 5),
    ("Bhaktapur", "Madhyapur Thimi Municipality", 3),
    ("Kathmandu", "Budhanilkantha Municipality", 3),
    ("Kavrepalanchok", "Banepa Municipality", 3),
    ("Kavrepalanchok", "Dhulikhel Municipality", 2),
    ("Nuwakot", "Bidur Municipality", 1),
    ("Dhading", "Nilakantha Municipality", 1),
    ("Sindhupalchok", "Chautara Sangachokgadhi Municipality", 1),
    ("Chitwan", "Bharatpur Metropolitan City", 1),
    ("Makwanpur", "Hetauda Sub-Metropolitan City", 1),
]

#: Nepal's approximate ABO/Rh distribution. Negative groups are rare here,
#: which is precisely why the blood bank screens care about them.
BLOOD = [("O+", 33), ("B+", 28), ("A+", 26), ("AB+", 9),
         ("O-", 1), ("B-", 1), ("A-", 1), ("AB-", 1)]

#: The formulary.
#:
#: (code, generic, brand, manufacturer, strength, form, base unit, pack size,
#:  therapeutic class, category, schedule, storage, VAT %, reorder level,
#:  price per base unit — cost, selling, MRP)
#:
#: Prices are per *base unit* in rupees, because the ledger is denominated in
#: base units: a strip of ten paracetamol at NPR 2 a tablet is NPR 20 at the
#: counter, which is what it costs in Kathmandu. Medicines are VAT-exempt;
#: devices and cosmetics carry 13%.
FORMULARY = [
    # -- over the counter ----------------------------------------------
    ("OTC-001", "Cetirizine", "Cetzine", "Deurali-Janta Pharmaceuticals", "10 mg",
     "tablet", "tablet", 10, "Antihistamine", "medicine", "none", "ambient", 0, 200,
     "1.60", "3.00", "3.50"),
    ("OTC-002", "Oral rehydration salts", "Jeevan Jal", "Nepal Pharmaceutical Lab",
     "20.5 g", "powder", "sachet", 1, "Rehydration", "medicine", "none", "ambient", 0,
     100, "9.00", "15.00", "16.00"),
    ("OTC-003", "Antacid (aluminium/magnesium)", "Digene", "Abbott", "170 mL",
     "suspension", "bottle", 1, "Antacid", "medicine", "none", "ambient", 0, 20,
     "110.00", "165.00", "180.00"),
    ("OTC-004", "Ibuprofen", "Brufen", "Abbott", "400 mg", "tablet", "tablet", 10,
     "Analgesic", "medicine", "none", "ambient", 0, 200, "2.10", "4.00", "4.50"),
    ("OTC-005", "Multivitamin with zinc", "Zincovit", "Apex Laboratories", "—",
     "tablet", "tablet", 15, "Supplement", "medicine", "none", "ambient", 0, 150,
     "4.50", "7.50", "8.00"),
    ("OTC-006", "Calcium with vitamin D3", "Shelcal", "Torrent", "500 mg",
     "tablet", "tablet", 15, "Supplement", "medicine", "none", "ambient", 0, 150,
     "5.20", "8.50", "9.00"),
    ("OTC-007", "Povidone-iodine", "Betadine", "Win-Medicare", "5%", "ointment",
     "tube", 1, "Antiseptic", "medicine", "none", "ambient", 0, 15,
     "68.00", "110.00", "120.00"),
    ("OTC-008", "Cough syrup (dextromethorphan)", "Benadryl DR", "Johnson & Johnson",
     "100 mL", "syrup", "bottle", 1, "Antitussive", "medicine", "none", "ambient", 0,
     20, "95.00", "150.00", "160.00"),
    ("OTC-009", "Paracetamol paediatric", "Cetamol", "Nepal Pharmaceutical Lab",
     "125 mg/5 mL", "syrup", "bottle", 1, "Analgesic", "medicine", "none", "ambient",
     0, 25, "28.00", "45.00", "48.00"),
    ("OTC-010", "Clotrimazole", "Candid", "Glenmark", "1%", "cream", "tube", 1,
     "Antifungal", "medicine", "none", "ambient", 0, 15, "62.00", "98.00", "105.00"),
    ("OTC-011", "Surgical face mask", "Nirova Care", "Everest Medical Supplies",
     "3-ply", "other", "piece", 50, "Protective", "consumable", "none", "ambient", 13,
     300, "2.50", "5.00", "5.00"),
    ("OTC-012", "Adhesive bandage", "Band-Aid", "Johnson & Johnson", "Assorted",
     "other", "piece", 100, "Wound care", "consumable", "none", "ambient", 13, 200,
     "1.40", "3.00", "3.00"),
    ("OTC-013", "Digital thermometer", "Omron MC-246", "Omron", "—", "other",
     "piece", 1, "Device", "device", "none", "ambient", 13, 5, "420.00", "650.00",
     "700.00"),
    ("OTC-014", "Omeprazole", "Omez", "Dr. Reddy's", "20 mg", "capsule", "capsule",
     10, "Proton pump inhibitor", "medicine", "none", "ambient", 0, 150,
     "2.60", "5.00", "5.50"),
    ("OTC-015", "Loperamide", "Imodium", "Johnson & Johnson", "2 mg", "capsule",
     "capsule", 10, "Antidiarrhoeal", "medicine", "none", "ambient", 0, 50,
     "3.00", "6.00", "6.50"),
    # -- prescription only ---------------------------------------------
    ("RX-001", "Amlodipine", "Amlong", "Micro Labs", "5 mg", "tablet", "tablet", 10,
     "Antihypertensive", "medicine", "prescription_only", "ambient", 0, 300,
     "1.80", "3.50", "4.00"),
    ("RX-002", "Losartan", "Losacar", "Zydus Cadila", "50 mg", "tablet", "tablet", 10,
     "Antihypertensive", "medicine", "prescription_only", "ambient", 0, 300,
     "3.20", "6.00", "6.50"),
    ("RX-003", "Atorvastatin", "Atorva", "Zydus Cadila", "10 mg", "tablet", "tablet",
     10, "Statin", "medicine", "prescription_only", "ambient", 0, 200,
     "3.50", "7.00", "7.50"),
    ("RX-004", "Azithromycin", "Azithral", "Alembic", "500 mg", "tablet", "tablet", 3,
     "Macrolide antibiotic", "medicine", "prescription_only", "ambient", 0, 60,
     "18.00", "32.00", "35.00"),
    ("RX-005", "Ciprofloxacin", "Ciplox", "Cipla", "500 mg", "tablet", "tablet", 10,
     "Fluoroquinolone antibiotic", "medicine", "prescription_only", "ambient", 0, 150,
     "3.40", "6.50", "7.00"),
    ("RX-006", "Salbutamol", "Asthalin", "Cipla", "100 mcg/dose", "inhaler",
     "inhaler", 1, "Bronchodilator", "medicine", "prescription_only", "ambient", 0, 10,
     "150.00", "240.00", "260.00"),
    ("RX-007", "Ceftriaxone", "Monocef", "Aristo", "1 g", "injection", "vial", 1,
     "Cephalosporin antibiotic", "medicine", "prescription_only", "ambient", 0, 40,
     "55.00", "90.00", "98.00"),
    ("RX-008", "Normal saline", "NS 0.9%", "Deurali-Janta Pharmaceuticals", "500 mL",
     "infusion", "bottle", 1, "IV fluid", "medicine", "prescription_only", "ambient",
     0, 60, "38.00", "60.00", "65.00"),
    ("RX-009", "Ringer's lactate", "RL", "Deurali-Janta Pharmaceuticals", "500 mL",
     "infusion", "bottle", 1, "IV fluid", "medicine", "prescription_only", "ambient",
     0, 60, "42.00", "68.00", "72.00"),
    ("RX-010", "Ondansetron", "Emeset", "Cipla", "4 mg", "tablet", "tablet", 10,
     "Antiemetic", "medicine", "prescription_only", "ambient", 0, 80,
     "3.60", "7.00", "7.50"),
    ("RX-011", "Levothyroxine", "Thyronorm", "Abbott", "50 mcg", "tablet", "tablet",
     100, "Thyroid hormone", "medicine", "prescription_only", "protect_light", 0, 200,
     "1.10", "2.20", "2.40"),
    ("RX-012", "Insulin regular", "Actrapid", "Novo Nordisk", "40 IU/mL",
     "injection", "vial", 1, "Insulin", "medicine", "prescription_only", "cold_chain",
     0, 12, "260.00", "380.00", "410.00"),
    ("RX-013", "Tetanus toxoid", "TT", "Serum Institute of India", "0.5 mL",
     "injection", "vial", 1, "Vaccine", "medicine", "prescription_only", "cold_chain",
     0, 20, "38.00", "65.00", "70.00"),
    ("RX-014", "Tramadol", "Contramal", "Abbott", "50 mg", "capsule", "capsule", 10,
     "Opioid analgesic", "medicine", "controlled", "ambient", 0, 50,
     "4.20", "8.00", "8.50"),
]

#: Batches, as (product code, suffix, days to expiry, quantity).
#:
#: Most lines have one healthy batch. The exceptions are the point: two
#: batches where FEFO has a choice, stock under the reorder level where the
#: reorder list should say so, and batches inside the expiry buckets where the
#: expiry report should.
BATCHES = [
    ("OTC-001", "A", 420, 1200), ("OTC-002", "A", 540, 400),
    ("OTC-003", "A", 300, 60), ("OTC-004", "A", 380, 900),
    ("OTC-004", "B", 75, 150),                   # near expiry: sell first
    ("OTC-005", "A", 260, 600), ("OTC-006", "A", 330, 450),
    ("OTC-007", "A", 610, 40), ("OTC-008", "A", 45, 24),   # 45 days left
    ("OTC-009", "A", 400, 80), ("OTC-010", "A", 520, 35),
    ("OTC-011", "A", 900, 1500), ("OTC-012", "A", 700, 800),
    ("OTC-013", "A", 1500, 4),                   # under reorder level of 5
    ("OTC-014", "A", 310, 700), ("OTC-015", "A", 450, 30),  # under 50
    ("RX-001", "A", 480, 1500), ("RX-002", "A", 400, 900),
    ("RX-003", "A", 360, 800), ("RX-004", "A", 280, 45),   # under 60
    ("RX-005", "A", 350, 600), ("RX-006", "A", 500, 18),
    ("RX-007", "A", 330, 120), ("RX-008", "A", 620, 240),
    ("RX-009", "A", 600, 200), ("RX-010", "A", 25, 60),    # 25 days left
    ("RX-010", "B", 390, 300), ("RX-011", "A", 540, 1000),
    ("RX-012", "A", 120, 16), ("RX-013", "A", 200, 30),
    ("RX-014", "A", 430, 120),
]

#: The wards `seed_demo_day` admits to and discharges from. The narrative
#: seed's wards (GW-A, ICU, PVT) are deliberately not among them: their
#: patients are characters in its story, and a generated discharge would walk
#: one out halfway through a scene.
GENERATED_WARDS = ("MW", "SW", "MAT", "PAED", "HDU")

#: (code, name, type, floor, building, patients per nurse, gender-segregated,
#:  bays as (bay, gender restriction, beds, daily rate, equipment))
WARDS = [
    ("MW", "Medical Ward", "general", "2nd floor", "Main block", "6.00", True, [
        ("Bay A · women", "female", 8, "1200", ("oxygen",)),
        ("Bay B · men", "male", 8, "1200", ("oxygen",)),
    ]),
    ("SW", "Surgical Ward", "general", "3rd floor", "Main block", "6.00", True, [
        ("Bay A · women", "female", 6, "1500", ("oxygen", "suction")),
        ("Bay B · men", "male", 6, "1500", ("oxygen", "suction")),
    ]),
    ("MAT", "Maternity Ward", "maternity", "1st floor", "Mother & child block", "5.00", True, [
        ("Postnatal", "female", 8, "1400", ()),
        ("Labour suite", "female", 2, "2500", ("oxygen", "suction", "monitor")),
    ]),
    ("PAED", "Children's Ward", "general", "1st floor", "Mother & child block", "5.00", False, [
        ("Bay", "any", 8, "1000", ("oxygen",)),
    ]),
    ("HDU", "High Dependency Unit", "hdu", "2nd floor", "Main block", "2.00", False, [
        ("HDU", "any", 4, "6000", ("oxygen", "suction", "monitor")),
    ]),
]

#: Beds that begin out of service, and why. Recorded with a reason because
#: `set_bed_status` refuses to take a bed out without one.
OUT_OF_SERVICE = {
    "MW-16": ("maintenance", "Bed rail broken — biomedical engineering called"),
    "SW-12": ("blocked", "Held for isolation: MRSA contact awaiting screen"),
    "MAT-09": ("reserved", "Elective caesarean section, 14:00"),
}

SUPPLIERS = ["Nepal Pharma Distributors", "Himalayan Medical Traders",
             "Kathmandu Drug House", "Sagarmatha Surgicals"]


class Command(BaseCommand):
    help = "Give the demo tenant a register of patients and a stocked formulary."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        slug = options["slug"]
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f"No organization '{slug}'.")

        # A fixed seed, not the date: the register is the same register every
        # time it is built, so a demo script can name a patient and find them.
        self.random = random.Random(2083)
        reception = (
            User.objects.filter(email=f"reception@{slug}.test").first()
            or User.objects.filter(email=f"owner@{slug}.test").first()
        )
        pharmacist = (
            User.objects.filter(email=f"pharmacy@{slug}.test").first()
            or User.objects.filter(email=f"manager@{slug}.test").first()
            or reception
        )

        with tenant_context(context_for_organization(organization)):
            self._register(organization, reception)
            self._formulary(pharmacist)
            self._wards(reception)
            self._cross_site(slug)

    # -- rota --------------------------------------------------------------

    def _cross_site(self, slug):
        """The demo nurse and doctor also work at the hospital.

        Both were rostered at the clinic alone, which is where the outpatient
        queue is — and nowhere near the wards, the emergency department or the
        high-dependency unit, which is where a nurse's and a doctor's day
        mostly is. Signed in, the nurse's workspace showed the clinic's one
        three-bed ward and the hospital's fifty beds were invisible to her.
        Clinicians in a Nepali group commonly cover more than one site; this
        gives them the second assignment an administrator would, through the
        same service, so the grant is audited like any other.
        """
        from apps.organization.models import Facility
        from apps.rbac.models import RoleAssignment
        from apps.rbac.services import assign_role

        hospital = Facility.objects.filter(facility_type="hospital", status="active").first()
        if hospital is None:
            return
        for email, role in ((f"nurse@{slug}.test", "nurse"), (f"doctor@{slug}.test", "doctor")):
            user = User.objects.filter(email=email).first()
            if user is None:
                continue
            if RoleAssignment.objects.filter(
                user_id=user.uuid, role__code=role, facility=hospital, status="active",
            ).exists():
                continue
            assign_role(
                user, role, scope="facility", facility=hospital,
                reason="Covers the hospital wards and emergency department as well as the clinic.",
            )
            self.stdout.write(f"\n  Rota: {user.full_name} also works at {hospital.name}")

    # -- people ------------------------------------------------------------

    def _weighted(self, rows):
        return self.random.choices([row[:-1] for row in rows],
                                   weights=[row[-1] for row in rows])[0]

    def _register(self, organization, actor):
        from apps.organization.models import Facility
        from apps.patients.models import Patient
        from apps.patients.services import register_patient

        present = Patient.objects.filter(merged_into__isnull=True).count()
        wanted = PATIENT_FLOOR - present
        self.stdout.write(f"\n  Register: {present} on file, floor {PATIENT_FLOOR}")
        if wanted <= 0:
            return

        facilities = list(Facility.objects.filter(status="active"))
        today = timezone.localdate()
        made = 0
        for index in range(wanted * 2):
            if made >= wanted:
                break
            female = self.random.random() < 0.52
            first = self.random.choice(FEMALE if female else MALE)
            middle = self.random.choice(MIDDLE_FEMALE if female else MIDDLE_MALE)
            last = self.random.choice(SURNAMES)
            # The age shape of an OPD: children and the elderly over-represented
            # against the census, because they are who is ill.
            age = self.random.choice(
                [self.random.randint(0, 12)] * 2
                + [self.random.randint(13, 40)] * 4
                + [self.random.randint(41, 64)] * 3
                + [self.random.randint(65, 88)] * 2
            )
            born = today - timedelta(days=age * 365 + self.random.randint(0, 364))
            # Same name and birthday already on file: this is a re-run meeting
            # its own earlier output, or an unlucky draw. Either way, skip.
            if Patient.objects.filter(first_name=first, last_name=last,
                                      date_of_birth=born).exists():
                continue

            district, municipality = self._weighted(PLACES)
            data = {
                "first_name": first,
                "middle_name": middle,
                "last_name": last,
                "gender": "female" if female else "male",
                "district": district,
                "municipality": municipality,
                "ward": str(self.random.randint(1, 32)),
            }
            # One in eight gives an age, not a date — common at a Nepali front
            # desk, and the record must carry it honestly as estimated.
            if self.random.random() < 0.125 and age > 20:
                data["stated_age_years"] = age
            else:
                data["date_of_birth"] = born
            # One in ten has no phone; the forms must not require one.
            if self.random.random() > 0.1:
                prefix = self.random.choice(["984", "985", "986", "980", "981", "982"])
                data["phone"] = f"+977-{prefix}{self.random.randint(1000000, 9999999)}"
            if self.random.random() < 0.6:
                data["blood_group"] = self._weighted(BLOOD)[0]

            register_patient(
                organization=organization,
                data=data,
                actor=actor,
                facility=self.random.choice(facilities) if facilities else None,
                force=True,
            )
            made += 1
        self.stdout.write(f"    {made} registered")

    # -- the shelf ---------------------------------------------------------

    def _formulary(self, actor):
        from apps.organization.models import Facility
        from apps.pharmacy.models import Batch, MovementType, Product, StockLocation
        from apps.pharmacy.services import post_movement

        facility = Facility.objects.filter(facility_type="pharmacy", status="active").first()
        location = (
            StockLocation.objects.filter(facility=facility, is_dispensable=True).first()
            if facility else None
        )
        if location is None:
            self.stdout.write("\n  Formulary: no dispensary; run seed_pharmacy_demo first.")
            return
        self.stdout.write(f"\n  Formulary: {location.name}, {facility.name}")

        by_code = {}
        for (code, generic, brand, maker, strength, form, unit, pack, klass,
             category, schedule, storage, vat, reorder, cost, sell, mrp) in FORMULARY:
            product, _ = Product.objects.update_or_create(
                code=code,
                defaults={
                    "generic_name": generic, "brand_name": brand,
                    "manufacturer": maker, "strength": strength,
                    "dosage_form": form, "base_unit": unit, "pack_size": pack,
                    "therapeutic_class": klass, "category": category,
                    "control_schedule": schedule, "storage_condition": storage,
                    "requires_prescription": schedule != "none",
                    "vat_rate": Decimal(vat),
                    "reorder_level": Decimal(reorder),
                    "minimum_stock": Decimal(reorder) / 2,
                    "maximum_stock": Decimal(reorder) * 5,
                    "lead_time_days": 7, "is_active": True,
                },
            )
            by_code[code] = (product, Decimal(cost), Decimal(sell), Decimal(mrp))

        today = timezone.localdate()
        received = 0
        for code, suffix, days, quantity in BATCHES:
            product, cost, sell, mrp = by_code[code]
            number = f"{code.replace('-', '')}-{today.year % 100}{suffix}"
            batch = Batch.objects.filter(product=product, batch_number=number).first()
            if batch is None:
                batch = Batch.objects.create(
                    product=product, batch_number=number,
                    expires_on=today + timedelta(days=days),
                    purchase_price=cost, selling_price=sell, mrp=mrp,
                    supplier_name=self.random.choice(SUPPLIERS),
                    receipt_reference=f"GRN-{number}",
                )
            if batch.entries.exists():
                continue
            post_movement(
                batch=batch, location=location,
                movement_type=MovementType.PURCHASE,
                quantity=Decimal(quantity), actor=actor,
                reason="Opening stock",
                reference_type="goods_receipt",
                reference_id=batch.receipt_reference,
            )
            received += 1
        self.stdout.write(f"    {len(FORMULARY)} lines, {received} batches received")

    # -- the wards ---------------------------------------------------------

    def _wards(self, actor):
        from apps.inpatient.models import Bed, Ward
        from apps.inpatient.services import set_bed_status
        from apps.organization.models import Facility

        hospital = Facility.objects.filter(facility_type="hospital", status="active").first()
        if hospital is None:
            self.stdout.write("\n  Wards: no hospital in this organization; skipped.")
            return
        self.stdout.write(f"\n  Wards: {hospital.name}")

        created_beds = 0
        for code, name, kind, floor, building, ratio, segregated, bays in WARDS:
            ward, _ = Ward.objects.update_or_create(
                facility=hospital, code=code,
                defaults={
                    "name": name, "ward_type": kind, "floor": floor,
                    "building": building,
                    "nurse_to_patient_ratio": Decimal(ratio),
                    "is_gender_segregated": segregated,
                    "visiting_hours": "07:00–09:00, 16:00–18:00",
                    "is_active": True,
                },
            )
            number = 0
            for bay, gender, count, rate, equipment in bays:
                for _ in range(count):
                    number += 1
                    bed_code = f"{code}-{number:02d}"
                    bed, made = Bed.objects.get_or_create(
                        ward=ward, code=bed_code,
                        defaults={
                            "bay": bay,
                            "gender_restriction": gender,
                            "daily_rate": Decimal(rate),
                            "has_oxygen": "oxygen" in equipment,
                            "has_suction": "suction" in equipment,
                            "has_monitor": "monitor" in equipment,
                            # The last bed in the medical ward is the side room.
                            "is_isolation": bed_code == "MW-08",
                        },
                    )
                    if made:
                        created_beds += 1
                        if bed_code in OUT_OF_SERVICE:
                            status, reason = OUT_OF_SERVICE[bed_code]
                            set_bed_status(bed, status, actor=actor, reason=reason)
        total = Bed.objects.filter(ward__facility=hospital, ward__code__in=GENERATED_WARDS).count()
        self.stdout.write(f"    {len(WARDS)} wards, {total} beds ({created_beds} new)")
