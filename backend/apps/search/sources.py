"""What the one search box may look in, and what it must refuse to look in.

§104. A global search is the single screen where every access rule in the
system is either enforced or bypassed at once, because it asks *what exists?*
across every domain simultaneously. That question is exactly the **browse** the
Phase 2 design refuses for clinical data, so this module is written around the
refusal rather than around the search.

Five rules, in the order they matter.

**A source runs only if the caller holds its permission.** Not "runs and then
filters" -- the query is never issued. Filtering after fetching is not
filtering: it produces a count that leaks, a log line for a read that should not
have happened, and a timing difference somebody can measure.

**The count is the count of what you may see.** No "42 results, 3 shown". A
number that describes rows you were refused is a disclosure of exactly the thing
the refusal existed to prevent -- it tells you the person is in the system,
which is often the whole secret.

**Clinical sources narrow to the care relationship; patients do not.** This is
the uncomfortable line and it is deliberate. Prescriptions, admissions, orders
and appointments narrow through `narrow_to_relationship`. The *patient* source
stays browsable at the identity tier, because the registration desk searches by
name all day and cannot have a relationship with somebody who has not been
registered yet. `ACCESS_DESIGN.md` accepts that trade explicitly: identity is
browsable, the clinical record is not.

**Search never pre-authorises.** A hit carries a URL, and following it runs the
ordinary check -- including the refusal, including break-glass. Search can tell
you a record exists; it cannot be the door into it. That matters most for
break-glass: **you may not break glass on somebody you found by browsing.**

**One audit event per search, not one per hit.** A search touching twenty-five
patients must not write twenty-five access rows; that drowns the log that
`record_patient_access` exists to keep readable. The search itself is the event,
and it records the term -- "who searched for that name the week the minister was
admitted?" is a question hospitals genuinely have to answer.

**Exact before partial.** Every source tries the identifier match first and the
name match second. Somebody who typed an MRN gets the record, not a page of
people whose phone number contains it -- and the ordering is the browse/lookup
distinction made visible in the results.
"""

from dataclasses import dataclass
from typing import Callable

from django.db.models import Q

#: How many hits one source may contribute. Deliberately small: a global search
#: is a way to find one thing, and a source that can fill the page starves every
#: other source of the space to show that it matched at all.
PER_SOURCE_LIMIT = 8


@dataclass(frozen=True)
class Source:
    """One thing the search box can look in."""

    code: str
    label: str
    #: The permission this source requires. Held, or the query is never issued.
    permission: str
    #: `(term, request, limit) -> list[dict]`.
    find: Callable
    #: Whether hits narrow to the caller's care relationships. Set for anything
    #: that is part of a clinical record rather than a business record.
    is_clinical: bool = False
    #: Whether a hit names a patient. Decides the severity of the audit event:
    #: searching the medicine catalogue is not the same act as searching people.
    about_patients: bool = False


_SOURCES: dict = {}


def register(source: Source) -> Source:
    if source.code in _SOURCES:
        raise ValueError(f"A search source is already registered as '{source.code}'")
    _SOURCES[source.code] = source
    return source


def all_sources() -> list:
    return sorted(_SOURCES.values(), key=lambda s: s.label)


def get_source(code: str) -> Source | None:
    return _SOURCES.get(code)


def _hit(kind, obj, label, sublabel, matched_on, url):
    """One result, in the shape every source returns.

    Uniform on purpose. A result list whose entries have different keys
    depending on what matched forces the caller to special-case each domain,
    which is how a front end ends up rendering a patient's phone number in the
    column headed "reference".
    """
    return {
        "type": kind,
        "uuid": str(obj.uuid),
        "label": label,
        "sublabel": sublabel,
        "matched_on": matched_on,
        # True when this row was found by naming it exactly rather than by
        # browsing towards it -- see `_ranked`. Carried out to the caller so
        # the audit event can say how many results were lookups, which is what
        # distinguishes a pharmacy counter doing its job from somebody walking
        # the reference sequence.
        "by_reference": getattr(obj, "_found_by_reference", False),
        "url": url,
    }


def _ranked(queryset, exact: Q, partial: Q, limit: int, lookup_in=None) -> list:
    """Exact identifier matches, then partial ones, without duplicates.

    Two queries rather than one `Q(...) | Q(...)` with a `Case` ordering,
    because the first is usually indexed and usually answers -- running the
    expensive `icontains` sweep when somebody has already typed an exact MRN is
    work nobody needed.

    `lookup_in` is the whole browse/lookup distinction expressed as an
    argument. Clinical sources pass the **unnarrowed** queryset there and the
    relationship-narrowed one as `queryset`: naming a record exactly is a
    lookup, because you can only have got the reference from the paper in your
    hand, while typing part of a name is a browse. So the exact clause searches
    everything and the partial clause searches only your own patients.

    This widens nothing that was not already open. `retrieve` by UUID is
    deliberately unnarrowed today -- measured, not assumed -- and a pharmacy
    counter handed a printed prescription has a *reference*, never a UUID, so
    without this the documented lookup path could not actually be walked. Every
    row it returns is flagged, counted, and logged.
    """
    source = queryset if lookup_in is None else lookup_in
    found = list(source.filter(exact)[:limit])
    for row in found:
        row._found_by_reference = lookup_in is not None
    if len(found) >= limit:
        return found
    seen = [row.pk for row in found]
    found += list(
        queryset.filter(partial).exclude(pk__in=seen)[: limit - len(found)]
    )
    return found


def load() -> None:
    """Register every source. Called once from the app's `ready()`."""
    if _SOURCES:
        return

    from apps.billing.models import Invoice
    from apps.common.permissions import apply_scope_filter, narrow_to_relationship
    from apps.diagnostics.models import SPECIMEN_MODALITIES, DiagnosticOrder
    from apps.documents.models import Document
    from apps.hr.models import Employee
    from apps.inpatient.models import Admission
    from apps.patients.models import Patient, PatientStatus
    from apps.pharmacy.models import Product
    from apps.prescriptions.models import Prescription
    from apps.procurement.models import Supplier
    from apps.scheduling.models import Appointment

    def _person(obj):
        """A patient's display line: who, and the number to confirm it by.

        The MRN rides along on every clinical hit because two patients share a
        name far more often than anybody designing a search box expects, and
        picking the wrong Ram Bahadur is a clinical error rather than a UI
        annoyance.
        """
        return f"{obj.full_name} - {obj.mrn}"

    def _matched(term, identifier, on_identifier, on_name):
        return on_identifier if term.lower() in (identifier or "").lower() else on_name

    # -- people ------------------------------------------------------------

    def patients(term, request, limit):
        # Merged records are excluded: a clerk searching for somebody should
        # find the live record, not the shell that points at it.
        queryset = Patient.objects.exclude(status=PatientStatus.MERGED)
        rows = _ranked(
            queryset,
            Q(mrn__iexact=term)
            | Q(phone__iexact=term)
            | Q(alternate_phone__iexact=term)
            | Q(identifiers__value__iexact=term),
            Q(mrn__icontains=term)
            | Q(first_name__icontains=term)
            | Q(middle_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(phone__icontains=term),
            limit,
        )
        return [
            _hit(
                "patient", row, row.full_name,
                " - ".join(filter(None, [
                    row.mrn,
                    f"{row.age_years}y" if row.age_years is not None else "",
                    row.phone,
                ])),
                _matched(term, row.mrn, "mrn", "name"),
                f"/api/patients/{row.uuid}/",
            )
            for row in rows
        ]

    def employees(term, request, limit):
        queryset = apply_scope_filter(
            Employee.objects.select_related("position", "facility"),
            request, "employee.read", employee_attr="self",
        )
        rows = _ranked(
            queryset,
            Q(employee_code__iexact=term) | Q(phone__iexact=term),
            Q(employee_code__icontains=term)
            | Q(first_name__icontains=term)
            | Q(middle_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(phone__icontains=term),
            limit,
        )
        return [
            _hit(
                "employee", row, row.full_name,
                " - ".join(filter(None, [
                    row.employee_code,
                    row.position.title if row.position_id else "",
                    row.facility.name if row.facility_id else "",
                ])),
                _matched(term, row.employee_code, "code", "name"),
                f"/api/hr/employees/{row.uuid}/",
            )
            for row in rows
        ]

    # -- what a hospital buys, sells and files -----------------------------

    def medicines(term, request, limit):
        rows = _ranked(
            Product.objects.all(),
            Q(code__iexact=term),
            Q(code__icontains=term)
            | Q(generic_name__icontains=term)
            | Q(brand_name__icontains=term),
            limit,
        )
        return [
            _hit(
                "medicine", row, row.brand_name or row.generic_name,
                " - ".join(filter(None, [
                    row.code, row.generic_name, row.therapeutic_class,
                ])),
                _matched(term, row.code, "code", "name"),
                f"/api/pharmacy/products/{row.uuid}/",
            )
            for row in rows
        ]

    def suppliers(term, request, limit):
        rows = _ranked(
            Supplier.objects.all(),
            Q(code__iexact=term) | Q(pan_number__iexact=term)
            | Q(phone__iexact=term),
            Q(code__icontains=term) | Q(name__icontains=term)
            | Q(legal_name__icontains=term) | Q(phone__icontains=term),
            limit,
        )
        return [
            _hit(
                "supplier", row, row.name,
                " - ".join(filter(None, [
                    row.code, row.contact_person, row.phone,
                ])),
                _matched(term, row.code, "code", "name"),
                f"/api/procurement/suppliers/{row.uuid}/",
            )
            for row in rows
        ]

    def invoices(term, request, limit):
        # Facility-filtered rather than relationship-filtered. An invoice is a
        # business record: the cashier who raised it must be able to find it,
        # and has no care relationship with anybody.
        queryset = apply_scope_filter(
            Invoice.objects.select_related("patient"), request, "invoice.read",
        )
        rows = _ranked(
            queryset,
            Q(number__iexact=term),
            Q(number__icontains=term)
            | Q(patient__first_name__icontains=term)
            | Q(patient__last_name__icontains=term)
            | Q(patient__mrn__icontains=term),
            limit,
        )
        return [
            _hit(
                "invoice", row, row.number,
                " - ".join([
                    _person(row.patient) if row.patient_id else "Counter sale",
                    f"NPR {row.total}", row.status,
                ]),
                _matched(term, row.number, "number", "patient"),
                f"/api/billing/invoices/{row.uuid}/",
            )
            for row in rows
        ]

    def documents(term, request, limit):
        # Titles and filenames only. Nothing here reads inside a file: a search
        # that indexed the contents of scanned discharge summaries would be a
        # far larger disclosure than the one this module is careful about, and
        # would need its own argument about redaction first.
        rows = _ranked(
            Document.objects.filter(archived_at__isnull=True),
            Q(original_name__iexact=term),
            Q(title__icontains=term) | Q(original_name__icontains=term),
            limit,
        )
        return [
            _hit(
                "document", row, row.title,
                f"{row.get_category_display()} - {row.original_name}",
                _matched(term, row.original_name, "filename", "title"),
                f"/api/documents/{row.uuid}/",
            )
            for row in rows
        ]

    # -- the clinical record -----------------------------------------------
    #
    # Every source below narrows to the care relationship. They are the reason
    # this module exists: a search box that reached these without narrowing
    # would undo Phase 2 in a single endpoint.

    def _by_patient(term):
        """The partial clause every clinical source shares.

        Written once because it must stay identical across them. A clinical
        search that matched on a field in one place and not another would let
        somebody establish, by difference, that a record they cannot see exists
        -- which is the leak this whole module is arranged against.
        """
        return (
            Q(reference__icontains=term)
            | Q(patient__first_name__icontains=term)
            | Q(patient__last_name__icontains=term)
            | Q(patient__mrn__icontains=term)
        )

    def appointments(term, request, limit):
        base = Appointment.objects.select_related("patient")
        rows = _ranked(
            narrow_to_relationship(base, request),
            Q(reference__iexact=term), _by_patient(term), limit, lookup_in=base,
        )
        return [
            _hit(
                "appointment", row, row.reference,
                " - ".join([
                    _person(row.patient),
                    f"{row.scheduled_for:%Y-%m-%d %H:%M}",
                    row.status,
                ]),
                _matched(term, row.reference, "reference", "patient"),
                f"/api/scheduling/appointments/{row.uuid}/",
            )
            for row in rows
        ]

    def prescriptions(term, request, limit):
        base = Prescription.objects.select_related("patient")
        rows = _ranked(
            narrow_to_relationship(base, request),
            Q(reference__iexact=term), _by_patient(term), limit, lookup_in=base,
        )
        return [
            _hit(
                "prescription", row, row.reference,
                f"{_person(row.patient)} - {row.status}",
                _matched(term, row.reference, "reference", "patient"),
                f"/api/prescriptions/{row.uuid}/",
            )
            for row in rows
        ]

    def admissions(term, request, limit):
        base = Admission.objects.select_related("patient")
        rows = _ranked(
            narrow_to_relationship(base, request),
            Q(reference__iexact=term), _by_patient(term), limit, lookup_in=base,
        )
        return [
            _hit(
                "admission", row, row.reference,
                " - ".join([
                    _person(row.patient),
                    f"admitted {row.admitted_at:%Y-%m-%d}",
                    row.status,
                ]),
                _matched(term, row.reference, "reference", "patient"),
                f"/api/inpatient/admissions/{row.uuid}/",
            )
            for row in rows
        ]

    def _orders(modalities, kind, term, request, limit):
        """Laboratory and imaging are one table split by modality.

        Two sources rather than one because they are two different questions: a
        clinician chasing a blood result and a radiographer chasing a film do
        not want each other's rows in the way, and `DiagnosticModality` already
        draws that line for the worklists.
        """
        base = DiagnosticOrder.objects.select_related("patient").filter(
            modality__in=modalities,
        )
        rows = _ranked(
            narrow_to_relationship(base, request),
            # The test *code* is not a lookup and does not bypass anything:
            # "CBC" names a kind of test, not a record somebody handed you, and
            # letting it through would turn the exemption into a browse of
            # every blood count in the hospital.
            Q(reference__iexact=term),
            _by_patient(term) | Q(test_name__icontains=term)
            | Q(test_code__iexact=term),
            limit,
            lookup_in=base,
        )
        return [
            _hit(
                kind, row, f"{row.reference} - {row.test_name}",
                f"{_person(row.patient)} - {row.status}",
                _matched(term, row.reference, "reference", "patient"),
                f"/api/diagnostics/orders/{row.uuid}/",
            )
            for row in rows
        ]

    #: Everything that is not a specimen test. Derived from the choices rather
    #: than listed, so a modality added to the catalogue appears in imaging
    #: search without anybody remembering to come back here -- the alternative
    #: is a new scanner whose orders are quietly unfindable.
    radiology_modalities = [
        value
        for value, _ in DiagnosticOrder._meta.get_field("modality").choices
        if value not in SPECIMEN_MODALITIES
    ]

    for source in [
        Source("patient", "Patients", "patient.read", patients,
               about_patients=True),
        Source("employee", "Staff", "employee.read", employees),
        Source("medicine", "Medicines", "stock.read", medicines),
        Source("supplier", "Suppliers", "purchase.read", suppliers),
        Source("invoice", "Invoices", "invoice.read", invoices,
               about_patients=True),
        Source("document", "Documents", "patient.read", documents,
               about_patients=True),
        Source("appointment", "Appointments", "encounter.read", appointments,
               is_clinical=True, about_patients=True),
        # `patient.read` rather than a prescription permission, matching the
        # prescription list itself: dispensing roles hold it, and the narrowing
        # that matters here is the care relationship, not a second permission.
        Source("prescription", "Prescriptions", "patient.read", prescriptions,
               is_clinical=True, about_patients=True),
        Source("admission", "Admissions", "encounter.read", admissions,
               is_clinical=True, about_patients=True),
        Source(
            "lab", "Laboratory", "encounter.read",
            lambda term, request, limit: _orders(
                list(SPECIMEN_MODALITIES), "lab", term, request, limit,
            ),
            is_clinical=True, about_patients=True,
        ),
        Source(
            "radiology", "Imaging", "encounter.read",
            lambda term, request, limit: _orders(
                radiology_modalities, "radiology", term, request, limit,
            ),
            is_clinical=True, about_patients=True,
        ),
    ]:
        register(source)
