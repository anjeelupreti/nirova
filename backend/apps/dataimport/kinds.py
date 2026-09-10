"""What each kind of import expects, and how it creates a record.

One `Importer` per kind, declaring four things: the columns it understands, how
to turn a row of strings into typed values, how to recognise that a row is
somebody already on file, and which service creates the record.

**Adding a kind means adding an importer, not editing the pipeline.**
`services.py` knows about validation, duplicates, previews and savepoints and
nothing about patients. That separation is the reason this can grow to the
fifteen or so kinds §124 eventually needs without the pipeline becoming a
switch statement.

**`create` is always an existing service, never a model.** `register_patient`
allocates the MRN, checks the entitlement quota, writes the audit event and
meters the record; `Patient.objects.create` does none of those. An importer that
reached for the model would look like it worked and would produce duplicate
MRNs, an unmetered tenant and no audit trail -- three failures that surface
weeks later and separately.
"""

from dataclasses import dataclass, field
from typing import Callable

from apps.dataimport import columns as col
from apps.dataimport.models import ImportKind


@dataclass(frozen=True)
class Column:
    """One column an importer understands.

    `aliases` are the header spellings seen in real files. They drive automatic
    mapping, which matters more than it sounds: a 40-column spreadsheet mapped
    by hand is twenty minutes of tedium per attempt, and somebody doing a
    migration attempts it several times.
    """

    field: str
    label: str
    required: bool = False
    aliases: tuple[str, ...] = ()
    help_text: str = ""


@dataclass(frozen=True)
class Importer:
    kind: str
    label: str
    #: What this creates, in the sentence a reviewer reads: "1,204 patients".
    noun: str
    columns: tuple[Column, ...]
    #: `(mapped_row) -> (normalised dict, [errors])`. Never raises: a row with
    #: four bad fields should report four problems, not the first one.
    normalise: Callable
    #: `(normalised) -> (uuid, label, score, matched_on) | None` -- an existing
    #: record this row looks like.
    find_existing: Callable
    #: `(normalised) -> hashable | None` -- the key that makes two rows *in the
    #: same file* the same record. None means "cannot tell", which is not the
    #: same as "not a duplicate" and must not be treated as one.
    same_file_key: Callable
    #: `(organization, normalised, actor, facility) -> object`
    create: Callable
    #: The entitlement quota this consumes, checked once for the whole batch.
    quota_key: str = ""
    notes: str = ""

    def required_fields(self) -> tuple[str, ...]:
        return tuple(c.field for c in self.columns if c.required)


def _collect(values: dict, *, spec: dict) -> tuple[dict, list]:
    """Run each field's coercer, gathering every error rather than the first.

    `spec` maps a field name to a callable taking the raw value. A coercer
    raising `FieldError` records the problem against that field and leaves the
    field out of the result; everything else still gets normalised, so one
    upload tells the user everything wrong with the row.
    """
    out, errors = {}, []
    for name, coerce in spec.items():
        raw = values.get(name)
        try:
            coerced = coerce(raw)
        except col.FieldError as error:
            errors.append({"field": name, "message": str(error)})
            continue
        if coerced is not None:
            out[name] = coerced
    return out, errors


def _require(normalised: dict, required: tuple[str, ...], errors: list) -> None:
    """Add an error for each required field that ended up empty.

    Checked after coercion rather than before, so a required field holding
    `"N/A"` is reported as missing -- which is what it is -- rather than as
    unparseable.
    """
    for name in required:
        if not normalised.get(name):
            errors.append({"field": name, "message": "is required and is empty."})


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

PATIENT_COLUMNS = (
    Column("first_name", "First name", required=True,
           aliases=("firstname", "given name", "name", "patient name", "fname")),
    Column("middle_name", "Middle name", aliases=("middlename", "mname")),
    Column("last_name", "Last name", required=True,
           aliases=("lastname", "surname", "family name", "lname", "thar")),
    Column("full_name_nepali", "Name in Nepali",
           aliases=("nepali name", "name nepali", "नाम")),
    Column("gender", "Gender", required=True, aliases=("sex", "लिङ्ग")),
    Column("date_of_birth", "Date of birth",
           aliases=("dob", "birth date", "birthdate", "date of birth (ad)"),
           help_text="Blank is allowed; a stated age can be given instead."),
    Column("stated_age_years", "Age in years",
           aliases=("age", "age (years)", "years"),
           help_text="Used when the date of birth is unknown."),
    Column("phone", "Telephone", aliases=("mobile", "contact", "phone number",
                                          "mobile no", "contact no", "cell")),
    Column("alternate_phone", "Other telephone",
           aliases=("alternate phone", "secondary phone", "phone 2")),
    Column("email", "Email", aliases=("e-mail", "email address")),
    Column("blood_group", "Blood group", aliases=("blood", "bloodgroup")),
    Column("marital_status", "Marital status", aliases=("marital",)),
    Column("occupation", "Occupation", aliases=("job", "profession")),
    Column("province", "Province", aliases=("state", "प्रदेश")),
    Column("district", "District", aliases=("जिल्ला",)),
    Column("municipality", "Municipality",
           aliases=("vdc", "municipality/vdc", "palika", "नगरपालिका")),
    Column("ward", "Ward number", aliases=("ward no", "ward number", "वडा")),
    Column("tole", "Street or locality", aliases=("street", "locality", "area")),
    Column("guardian_name", "Guardian name",
           aliases=("guardian", "next of kin", "father name", "husband name")),
    Column("guardian_phone", "Guardian telephone", aliases=("guardian contact",)),
    Column("guardian_relationship", "Relationship to guardian",
           aliases=("relation", "relationship")),
)


def _normalise_patient(values: dict) -> tuple[dict, list]:
    out, errors = _collect(values, spec={
        "first_name": lambda v: col.text(v, max_length=128),
        "middle_name": lambda v: col.text(v, max_length=128),
        "last_name": lambda v: col.text(v, max_length=128),
        "full_name_nepali": lambda v: col.text(v, max_length=255),
        "gender": lambda v: col.choice(v, options=col.GENDERS, default=""),
        "date_of_birth": col.on_date,
        "stated_age_years": lambda v: col.integer(v, minimum=0, maximum=130),
        "phone": col.phone,
        "alternate_phone": col.phone,
        "email": col.email,
        "blood_group": lambda v: col.choice(
            v, options=col.BLOOD_GROUPS, default="unknown"
        ),
        "marital_status": lambda v: col.choice(
            v, options=col.MARITAL_STATUSES, default="unknown"
        ),
        "occupation": lambda v: col.text(v, max_length=128),
        "province": lambda v: col.text(v, max_length=64),
        "district": lambda v: col.text(v, max_length=64),
        "municipality": lambda v: col.text(v, max_length=128),
        "ward": lambda v: col.text(v, max_length=16),
        "tole": lambda v: col.text(v, max_length=128),
        "guardian_name": lambda v: col.text(v, max_length=255),
        "guardian_phone": col.phone,
        "guardian_relationship": lambda v: col.text(v, max_length=64),
    })
    _require(out, ("first_name", "last_name", "gender"), errors)

    # **Neither a date of birth nor an age is an error, and it is this one that
    # matters clinically.** Paediatric dosing, adult screening intervals and
    # the age shown beside a name all come from one of the two. A patient with
    # neither is a record that looks complete and cannot be prescribed for
    # safely, so the migration is made to confront it rather than the clinician
    # six months later.
    if not out.get("date_of_birth") and out.get("stated_age_years") is None:
        errors.append({
            "field": "date_of_birth",
            "message": (
                "give either a date of birth or an age in years. A patient "
                "with neither cannot be dosed by weight-for-age or screened by "
                "age."
            ),
        })
    return out, errors


def _find_patient(normalised: dict):
    from apps.patients.services import find_duplicate_candidates

    candidates = find_duplicate_candidates(
        first_name=normalised.get("first_name", ""),
        last_name=normalised.get("last_name", ""),
        phone=normalised.get("phone", ""),
        date_of_birth=normalised.get("date_of_birth"),
        limit=1,
    )
    if not candidates:
        return None
    best = candidates[0]
    patient = best["patient"]
    return (
        patient.uuid,
        f"{patient.full_name} ({patient.mrn})",
        best["score"],
        best["matched_on"],
    )


def _patient_same_file_key(normalised: dict):
    """What makes two rows of one spreadsheet the same person.

    Phone first, because it is the strongest thing a file reliably carries and
    a family sharing a number is caught by the name half as well. Falls back to
    name and date of birth. Returns None when there is neither a phone nor a
    date of birth -- two rows reading "Ram Bahadur Thapa, male" may genuinely be
    two people, and guessing they are one would *silently drop a patient*, which
    is worse than importing a duplicate somebody can merge.
    """
    first = normalised.get("first_name", "").lower()
    last = normalised.get("last_name", "").lower()
    if phone := normalised.get("phone"):
        return ("phone", phone, first, last)
    if dob := normalised.get("date_of_birth"):
        return ("dob", first, last, dob.isoformat())
    return None


def _create_patient(organization, normalised: dict, actor, facility):
    from apps.patients.services import register_patient

    # `force=True` because duplicate detection has already run, in
    # `validate_batch`, and a reviewer has already seen the match and decided.
    # Leaving it False would make the service raise `DuplicatePatientWarning`
    # at commit time for a row somebody deliberately chose to import -- the
    # review would be meaningless.
    return register_patient(
        organization, dict(normalised), actor=actor, facility=facility, force=True
    )


PATIENTS = Importer(
    kind=ImportKind.PATIENTS,
    label="Patients",
    noun="patients",
    columns=PATIENT_COLUMNS,
    normalise=_normalise_patient,
    find_existing=_find_patient,
    same_file_key=_patient_same_file_key,
    create=_create_patient,
    quota_key="max_patients",
    notes=(
        "Registers through the normal registration service, so every patient "
        "gets an MRN from the same sequence as one registered at the counter."
    ),
)


# ---------------------------------------------------------------------------
# Medicines and products
# ---------------------------------------------------------------------------

MEDICINE_COLUMNS = (
    Column("code", "Code", required=True,
           aliases=("item code", "product code", "sku")),
    # **`generic_name` is the required one, not a brand name.** That is the
    # model's decision and it is the right one: prescribing, substitution and
    # the formulary all work on the molecule, and a stock list that knows only
    # "Calpol" cannot tell a pharmacist it is the same thing as "Paracetamol
    # 500". A migration file usually has the brand in its "name" column, so
    # both spellings alias here and the brand is a separate column.
    Column("generic_name", "Generic name", required=True,
           aliases=("generic", "molecule", "salt", "composition",
                    "name", "item name", "medicine", "description", "product")),
    Column("brand_name", "Brand name",
           aliases=("brand", "trade name")),
    Column("strength", "Strength", aliases=("dose", "mg", "potency")),
    Column("dosage_form", "Form",
           aliases=("form", "dosage form", "type", "presentation")),
    Column("manufacturer", "Manufacturer", aliases=("company", "maker", "mfg")),
    Column("country_of_origin", "Country of origin",
           aliases=("origin", "country")),
    Column("therapeutic_class", "Therapeutic class",
           aliases=("class", "drug class")),
    Column("category", "Category",
           aliases=("item type", "product type", "group")),
    Column("base_unit", "Stock unit", required=True,
           aliases=("unit", "uom", "unit of measure", "base unit"),
           help_text="The unit stock is counted in: tablet, vial, millilitre."),
    Column("pack_size", "Pack size",
           aliases=("pack", "units per pack", "qty per pack"),
           help_text="How many stock units are in one purchased pack."),
    Column("barcode", "Barcode", aliases=("ean", "upc", "bar code")),
)

#: Dosage forms as files write them. Only spellings that map to exactly one
#: form: `tab` is a tablet everywhere, whereas `sol` could be a syrup, a
#: suspension or an injection, so it is left out and reported as unrecognised
#: rather than resolved by guessing.
DOSAGE_FORMS = {
    "tablet": "tablet", "tab": "tablet", "tabs": "tablet", "tablets": "tablet",
    "capsule": "capsule", "cap": "capsule", "caps": "capsule",
    "syrup": "syrup", "syp": "syrup", "liquid": "syrup",
    "suspension": "suspension", "susp": "suspension",
    "injection": "injection", "inj": "injection", "vial": "injection",
    "ampoule": "injection", "amp": "injection",
    "infusion": "infusion", "iv": "infusion", "drip": "infusion",
    "cream": "cream",
    "ointment": "ointment", "oint": "ointment", "gel": "ointment",
    "drops": "drops", "drop": "drops", "eye drops": "drops",
    "ear drops": "drops",
    "inhaler": "inhaler", "puff": "inhaler", "mdi": "inhaler",
    "suppository": "suppository", "supp": "suppository",
    "powder": "powder", "sachet": "powder",
    "patch": "patch",
    "other": "other", "misc": "other",
}

PRODUCT_CATEGORIES = {
    "medicine": "medicine", "drug": "medicine", "medicines": "medicine",
    "pharmaceutical": "medicine",
    "consumable": "consumable", "consumables": "consumable",
    "disposable": "consumable",
    "device": "device", "equipment": "device", "instrument": "device",
    "surgical": "surgical", "surgical item": "surgical", "suture": "surgical",
    "reagent": "reagent", "lab": "reagent", "laboratory": "reagent",
    "lab reagent": "reagent",
    "other": "other", "misc": "other", "general": "other",
}


def _normalise_medicine(values: dict) -> tuple[dict, list]:
    out, errors = _collect(values, spec={
        "code": lambda v: col.text(v, max_length=32),
        "generic_name": lambda v: col.text(v, max_length=255),
        "brand_name": lambda v: col.text(v, max_length=255),
        "strength": lambda v: col.text(v, max_length=64),
        "dosage_form": lambda v: col.choice(
            v, options=DOSAGE_FORMS, default="tablet"
        ),
        "manufacturer": lambda v: col.text(v, max_length=255),
        "country_of_origin": lambda v: col.text(v, max_length=64),
        "therapeutic_class": lambda v: col.text(v, max_length=128),
        "category": lambda v: col.choice(
            v, options=PRODUCT_CATEGORIES, default="medicine"
        ),
        "base_unit": lambda v: col.text(v, max_length=32),
        "pack_size": lambda v: col.integer(v, minimum=1),
        "barcode": lambda v: col.text(v, max_length=64),
    })
    _require(out, ("code", "generic_name", "base_unit"), errors)

    # **A liquid counted in tablets is a real error, not a tidy-up.** Stock is
    # held in the base unit, so a syrup whose unit is "tablet" cannot be
    # dispensed at all -- "give 5 ml" has no expressible answer -- and the
    # mistake is invisible until a pharmacist tries. It arises exactly when the
    # form is defaulted while the unit came from the file.
    form = out.get("dosage_form", "")
    unit = out.get("base_unit", "").lower()
    liquids = {"syrup", "suspension", "injection", "infusion", "drops"}
    if form in liquids and unit in {"tablet", "tab", "capsule"}:
        errors.append({
            "field": "base_unit",
            "message": (
                f"a {form} cannot be counted in {unit}s. Stock is held in this "
                "unit, so dispensing a volume would have no answer. Use ml, "
                "vial or bottle."
            ),
        })
    return out, errors


def _find_medicine(normalised: dict):
    from apps.pharmacy.models import Product

    code = normalised.get("code", "")
    if code:
        existing = Product.objects.filter(code__iexact=code).first()
        if existing:
            # A code match is not a resemblance: this row *is* that product.
            # Scored at the top so a reviewer reads it as settled rather than
            # as something to weigh up.
            return (existing.uuid, f"{existing.generic_name} ({existing.code})",
                    100, ["code"])

    # Generic name *with* strength and form, never the name alone.
    # "Paracetamol" matching "Paracetamol 500mg tablet" would merge a
    # paediatric syrup into an adult tablet -- different stock, different
    # price, and a dosing error waiting behind it.
    generic = normalised.get("generic_name", "")
    if generic:
        existing = Product.objects.filter(
            generic_name__iexact=generic,
            strength__iexact=normalised.get("strength", ""),
            dosage_form=normalised.get("dosage_form", "tablet"),
        ).first()
        if existing:
            return (existing.uuid, f"{existing.generic_name} ({existing.code})",
                    70, ["generic_name", "strength", "dosage_form"])
    return None


def _medicine_same_file_key(normalised: dict):
    code = normalised.get("code", "")
    return ("code", code.lower()) if code else None


def _create_medicine(organization, normalised: dict, actor, facility):
    from apps.pharmacy.models import Product

    # No registration service for a product: creation is a plain write with no
    # sequence, quota or metering behind it, so the model is the right caller
    # here. Said out loud because the rule everywhere else in this file is the
    # opposite, and a reader should not have to wonder whether this is an
    # oversight.
    return Product.objects.create(
        created_by_id=getattr(actor, "uuid", None), **normalised
    )


MEDICINES = Importer(
    kind=ImportKind.MEDICINES,
    label="Medicines and products",
    noun="products",
    columns=MEDICINE_COLUMNS,
    normalise=_normalise_medicine,
    find_existing=_find_medicine,
    same_file_key=_medicine_same_file_key,
    create=_create_medicine,
    notes=(
        "Prices and stock are not set here. A product is a catalogue entry; "
        "what it costs and how much there is of it are separate imports, "
        "because they are separate decisions with separate approvals."
    ),
)


#: Every importer, by kind. The pipeline looks kinds up here and nowhere else.
REGISTRY: dict[str, Importer] = {
    PATIENTS.kind: PATIENTS,
    MEDICINES.kind: MEDICINES,
}


def importer_for(kind: str) -> Importer:
    try:
        return REGISTRY[kind]
    except KeyError:
        raise ValueError(
            f"No importer for '{kind}'. Available: "
            f"{', '.join(sorted(REGISTRY))}."
        ) from None
