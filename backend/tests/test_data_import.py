"""Bringing a practice's existing records in, and refusing to do it badly.

§124. A hospital does not adopt a system empty: it arrives with eight thousand
patients in a spreadsheet somebody has maintained since 2014. Whether that file
can be imported *safely* decides whether the customer can start at all.

**The tests that matter here are the refusals, and for an unusual reason.** A
naive importer passes every happy-path test and is still worse than no importer,
because the damage it does is the one kind that cannot be undone: two records for
the same patient split a clinical history, and by the time anybody notices there
are encounters, prescriptions and invoices hanging off both. So most of what
follows is about what the pipeline declines to do.

Particular attention to two things a real migration always contains and a naive
importer always misses:

- **Duplicates within the file itself.** No database lookup can find these,
  because at validation time neither row exists yet. A decade-old spreadsheet
  has the same person in it three or four times.
- **Committing twice.** The request is slow, the user clicks again, and the
  whole file lands a second time.
"""

import io
import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
OWNER = f"owner@{DEMO}.test"
#: Holds none of `data.import`. Used to prove the guard, not as an afterthought:
#: bulk-creating records is an administrator's authority.
CLERK = f"counter@{DEMO}.test"


def _client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
        raise_request_exception=False,
    )


@pytest.fixture
def admin(tenant):
    client = _client(OWNER, tenant)
    if client is None:
        pytest.skip(f"no {OWNER}; run manage.py bootstrap")
    return client


def _body(response):
    return json.loads(response.content.decode())


def _upload(client, csv_text, *, kind="patients", name="patients.csv"):
    handle = io.BytesIO(csv_text.encode("utf-8"))
    handle.name = name
    return client.post(
        "/api/import/batches/", {"kind": kind, "file": handle}
    )


@pytest.fixture(autouse=True)
def _clean_up(tenant):
    """Delete what each test created, in the tenant it created it in.

    These run against the shared development tenant, so a test that left eight
    imported patients behind would inflate every later count and eventually
    break the duplicate tests -- which is the failure mode this whole feature
    is about, reproduced in its own test suite.
    """
    from apps.dataimport.models import ImportBatch

    before = set(ImportBatch.objects.values_list("pk", flat=True))
    yield
    new_batches = ImportBatch.objects.exclude(pk__in=before)
    created_uuids = [
        uuid for uuid in (
            row.created_uuid
            for batch in new_batches
            for row in batch.rows.all()
        ) if uuid
    ]
    if created_uuids:
        from apps.patients.models import Patient
        from apps.pharmacy.models import Product

        Patient.objects.filter(uuid__in=created_uuids).delete()
        Product.objects.filter(uuid__in=created_uuids).delete()
    new_batches.delete()


# -- the happy path, kept short --------------------------------------------

GOOD_CSV = """Patient Name,Surname,Sex,DOB,Mobile,Blood
Ramesh,Gurung,M,1988-04-12,9841000001,B+
Sita,Shrestha,Female,02/03/1995,9841000002,O positive
Hari,Magar,m,1977-11-30,9841000003,A+ve
"""


def test_a_clean_file_maps_validates_and_imports(admin):
    """Upload, validate, commit -- and the patients exist afterwards.

    Deliberately also checks the *spellings*: `M`, `Female` and `m` must all
    land as a gender, `O positive` and `A+ve` as blood groups, and `02/03/1995`
    as 2 March rather than 3 February. A migration file written by three people
    over ten years contains all of these, and an importer that only reads one
    spelling fails most of the file.
    """
    from apps.patients.models import Patient

    created = _upload(admin, GOOD_CSV)
    assert created.status_code == 201, created.content[:400]
    batch = _body(created)
    reference = batch["reference"]

    # Mapping was suggested from the headers, not from the field names: the file
    # says "Patient Name", "Surname", "Sex", "DOB", "Mobile", "Blood".
    assert batch["column_map"]["first_name"] == "Patient Name"
    assert batch["column_map"]["last_name"] == "Surname"
    assert batch["column_map"]["gender"] == "Sex"
    assert batch["column_map"]["date_of_birth"] == "DOB"
    assert batch["column_map"]["phone"] == "Mobile"
    assert batch["column_map"]["blood_group"] == "Blood"
    assert batch["total_rows"] == 3

    validated = admin.post(f"/api/import/batches/{reference}/validate/")
    assert validated.status_code == 200, validated.content[:400]
    assert _body(validated)["will_create"] == 3, _body(validated)

    committed = admin.post(f"/api/import/batches/{reference}/commit/")
    assert committed.status_code == 200, committed.content[:400]
    assert _body(committed)["created"] == 3

    ramesh = Patient.objects.filter(
        first_name="Ramesh", last_name="Gurung", phone="9841000001"
    ).first()
    assert ramesh is not None
    assert ramesh.gender == "male"
    assert ramesh.blood_group == "B+"
    # The MRN came from the normal sequence, which is the point of going
    # through `register_patient` rather than `Patient.objects.create`.
    assert ramesh.mrn, "the imported patient has no MRN"

    sita = Patient.objects.get(phone="9841000002")
    assert sita.gender == "female"
    assert sita.blood_group == "O+"
    assert (sita.date_of_birth.month, sita.date_of_birth.day) == (3, 2), (
        f"02/03/1995 became {sita.date_of_birth} -- read as month-first, which "
        "moves every Nepali birthday it touches"
    )
    assert Patient.objects.get(phone="9841000003").blood_group == "A+"


# -- what it refuses to do -------------------------------------------------


def test_two_rows_for_the_same_person_in_one_file_are_caught(admin):
    """The duplicate no database lookup can find.

    At validation time neither row exists, so `find_duplicate_candidates`
    returns nothing for both and a naive importer creates two patients. This is
    the single most common defect in a real migration, because the spreadsheet a
    practice has kept for a decade has the same person in it several times.
    """
    csv_text = (
        "First name,Last name,Gender,Mobile,DOB\n"
        "Bikash,Tamang,M,9842000111,1990-01-01\n"
        "Anita,Rai,F,9842000222,1992-02-02\n"
        "Bikash,Tamang,Male,9842000111,1990-01-01\n"
    )
    reference = _body(_upload(admin, csv_text))["reference"]
    preview = _body(admin.post(f"/api/import/batches/{reference}/validate/"))

    assert preview["duplicate_rows"] == 1, preview
    assert preview["will_create"] == 2

    duplicate = next(r for r in preview["sample"] if r["status"] == "duplicate")
    assert duplicate["row_number"] == 4, (
        "the third data row is row 4 of the spreadsheet -- the header is row 1, "
        "and an off-by-one here makes every error message point at the wrong line"
    )
    assert duplicate["duplicate_of_row"] == 2
    assert "same file" in duplicate["duplicate_matched_on"]


def test_a_file_cannot_be_committed_twice(admin):
    """The likeliest way a migration creates duplicates.

    The request is slow because it is creating three thousand patients, the user
    clicks import again, and without this guard the whole file lands twice.
    """
    from apps.patients.models import Patient

    reference = _body(_upload(admin, GOOD_CSV))["reference"]
    admin.post(f"/api/import/batches/{reference}/validate/")
    assert admin.post(f"/api/import/batches/{reference}/commit/").status_code == 200
    before = Patient.objects.count()

    again = admin.post(f"/api/import/batches/{reference}/commit/")
    assert again.status_code == 400
    assert "cannot be imported again" in _body(again)["detail"]
    assert Patient.objects.count() == before, (
        "a second commit created records anyway"
    )


def test_a_row_with_four_problems_reports_four_problems(admin):
    """One upload should tell the user everything wrong with a row.

    Reporting only the first error means the file is corrected one mistake per
    upload, and a 3,000-row migration becomes a week of uploads.
    """
    csv_text = (
        "First name,Last name,Gender,Mobile,Email,DOB\n"
        "Ram,Thapa,alien,12,not-an-email,31/31/2020\n"
    )
    reference = _body(_upload(admin, csv_text))["reference"]
    admin.post(f"/api/import/batches/{reference}/validate/")

    rows = _body(admin.get(f"/api/import/batches/{reference}/rows/"))["results"]
    assert rows[0]["status"] == "invalid"
    fields = {error["field"] for error in rows[0]["errors"]}
    assert {"gender", "phone", "email", "date_of_birth"} <= fields, (
        f"only reported {fields}; a row with four bad cells must report four"
    )


def test_a_patient_with_neither_a_birthday_nor_an_age_is_refused(admin):
    """Not pedantry: it is the field clinical safety depends on.

    Weight-for-age dosing, screening intervals and the age shown beside a name
    all come from one of the two. A record with neither looks complete and
    cannot be prescribed for safely, so the migration is made to confront it
    rather than a clinician six months later.
    """
    csv_text = (
        "First name,Last name,Gender,Mobile\n"
        "Gita,Lama,F,9843000111\n"
    )
    reference = _body(_upload(admin, csv_text))["reference"]
    preview = _body(admin.post(f"/api/import/batches/{reference}/validate/"))
    assert preview["invalid_rows"] == 1
    assert preview["will_create"] == 0

    rows = _body(admin.get(f"/api/import/batches/{reference}/rows/"))["results"]
    message = " ".join(e["message"] for e in rows[0]["errors"])
    assert "age" in message and "date of birth" in message


def test_an_unvalidated_batch_cannot_be_committed(admin):
    """The preview is not optional.

    Committing without validating would mean importing a file nobody has read
    the consequences of, which is the entire thing this pipeline exists to
    prevent.
    """
    reference = _body(_upload(admin, GOOD_CSV))["reference"]
    refused = admin.post(f"/api/import/batches/{reference}/commit/")
    assert refused.status_code == 400
    assert "not been validated" in _body(refused)["detail"]


def test_a_duplicate_with_no_decision_blocks_the_commit(admin):
    """A duplicate resolved by default is a duplicate nobody chose.

    Whichever way the default went it would be wrong somewhere -- skipping
    silently loses a patient who genuinely is a new person, importing silently
    creates the split record this feature exists to avoid. So the commit stops
    and asks.
    """
    csv_text = (
        "First name,Last name,Gender,Mobile,DOB\n"
        "Kiran,Bhandari,M,9844000111,1991-05-05\n"
        "Kiran,Bhandari,M,9844000111,1991-05-05\n"
    )
    reference = _body(_upload(admin, csv_text))["reference"]
    admin.post(f"/api/import/batches/{reference}/validate/")

    refused = admin.post(f"/api/import/batches/{reference}/commit/")
    assert refused.status_code == 400
    assert "no decision" in _body(refused)["detail"]

    decided = admin.post(
        f"/api/import/batches/{reference}/decide/",
        data=json.dumps({"decisions": {"3": "skip"}}),
        content_type="application/json",
    )
    assert decided.status_code == 200, decided.content[:300]
    committed = admin.post(f"/api/import/batches/{reference}/commit/")
    assert committed.status_code == 200, committed.content[:300]
    assert _body(committed)["created"] == 1
    assert _body(committed)["skipped"] == 1


def test_validating_is_refused_after_a_commit(admin):
    """The row statuses are the record of what was imported.

    Re-validating would overwrite them, and the answer to "where did this
    patient come from" would be gone.
    """
    reference = _body(_upload(admin, GOOD_CSV))["reference"]
    admin.post(f"/api/import/batches/{reference}/validate/")
    admin.post(f"/api/import/batches/{reference}/commit/")

    refused = admin.post(f"/api/import/batches/{reference}/validate/")
    assert refused.status_code == 400
    assert "already been imported" in _body(refused)["detail"]


def test_a_file_missing_a_required_column_cannot_be_validated(admin):
    """Said at validation, naming the column, rather than failing per row.

    A file with no gender column produces one problem, not three thousand
    identical ones, and the message names what to add.
    """
    csv_text = "First name,Last name,Mobile\nPrakash,Oli,9845000111\n"
    reference = _body(_upload(admin, csv_text))["reference"]
    refused = admin.post(f"/api/import/batches/{reference}/validate/")
    assert refused.status_code == 400
    assert "Gender" in _body(refused)["detail"]


def test_bulk_import_needs_its_own_permission(tenant):
    """Registering one patient is a clerk's job; creating eight thousand is not.

    The counter assistant holds `patient.create` and legitimately registers
    people all day. `data.import` is separate because the mistake is a different
    size and a different kind.
    """
    clerk = _client(CLERK, tenant)
    if clerk is None:
        pytest.skip(f"no {CLERK}")
    assert clerk.get("/api/import/batches/").status_code == 403
    assert clerk.get("/api/import/kinds/").status_code == 403
    assert _upload(clerk, GOOD_CSV).status_code == 403


# -- the error report ------------------------------------------------------


def test_the_error_report_is_the_original_file_plus_the_problem(admin):
    """Shaped to be corrected and re-uploaded, not merely read.

    The original columns first, with the file's own headers, so the reviewer
    fixes the cells in place. A report of row numbers and messages would have to
    be read beside the original file, which for four hundred rows nobody does.
    """
    csv_text = (
        "First name,Last name,Gender,Mobile,DOB\n"
        "Valid,Person,M,9846000111,1990-01-01\n"
        "Broken,Row,alien,9846000222,1990-01-01\n"
    )
    reference = _body(_upload(admin, csv_text))["reference"]
    admin.post(f"/api/import/batches/{reference}/validate/")

    report = admin.get(f"/api/import/batches/{reference}/errors/")
    assert report.status_code == 200
    assert report["Content-Type"] == "text/csv"
    text = report.content.decode()

    header, *lines = [line for line in text.splitlines() if line.strip()]
    assert header.startswith("First name,Last name,Gender,Mobile,DOB"), header
    assert header.endswith("Row,Outcome,Problem"), header
    assert len(lines) == 1, f"expected only the broken row, got {lines}"
    assert lines[0].startswith("Broken,Row,alien"), lines[0]
    assert "gender" in lines[0]


# -- the other kind, to prove the registry is not patient-shaped -----------


def test_a_medicine_list_imports_through_the_same_pipeline(admin):
    """The pipeline knows nothing about patients.

    Worth a test because a pipeline with one implementation is a pipeline
    shaped around that implementation, and §124 needs a dozen more kinds.
    """
    from apps.pharmacy.models import Product

    csv_text = (
        "Item code,Item name,Strength,Form,Unit,Company\n"
        "IMP-PARA-500,Paracetamol,500mg,Tab,tablet,Nepal Pharma\n"
        "IMP-AMOX-125,Amoxicillin,125mg/5ml,Syrup,ml,Deurali\n"
    )
    reference = _body(_upload(
        admin, csv_text, kind="medicines", name="medicines.csv"
    ))["reference"]

    preview = _body(admin.post(f"/api/import/batches/{reference}/validate/"))
    assert preview["invalid_rows"] == 0, preview
    assert preview["will_create"] == 2

    assert admin.post(f"/api/import/batches/{reference}/commit/").status_code == 200
    syrup = Product.objects.get(code="IMP-AMOX-125")
    assert syrup.dosage_form == "syrup"
    assert syrup.base_unit == "ml"
    assert Product.objects.get(code="IMP-PARA-500").dosage_form == "tablet"


def test_a_syrup_counted_in_tablets_is_refused(admin):
    """Stock is held in the base unit, so the combination has no meaning.

    A syrup whose unit is "tablet" cannot be dispensed -- "give 5 ml" has no
    expressible answer -- and nobody finds out until a pharmacist tries.
    """
    csv_text = (
        "Item code,Item name,Form,Unit\n"
        "IMP-BAD-1,Cough Linctus,Syrup,tablet\n"
    )
    reference = _body(_upload(
        admin, csv_text, kind="medicines", name="bad.csv"
    ))["reference"]
    preview = _body(admin.post(f"/api/import/batches/{reference}/validate/"))
    assert preview["invalid_rows"] == 1, preview

    rows = _body(admin.get(f"/api/import/batches/{reference}/rows/"))["results"]
    assert any("cannot be counted in" in e["message"] for e in rows[0]["errors"])
