"""Finding a code, and keeping the list honest about what gets used."""

from django.db.models import Case, IntegerField, Q, Value, When

from apps.terminology.models import DiagnosisCode


class UnknownCode(ValueError):
    """A code that is not in this organization's vocabulary."""


def search(term: str, limit: int = 12) -> list:
    """Codes matching `term`, best first.

    The order is the whole value of this function: an exact code first, then
    a code that starts with what was typed, then a title that starts with it,
    then anything containing it -- and within each band, what this hospital
    uses most. A search that returns the right answer fourth is a search
    people stop using.
    """
    term = (term or "").strip()
    if len(term) < 2:
        return list(
            DiagnosisCode.objects.filter(is_active=True, is_common=True)
            .order_by("-times_used", "code")[:limit]
        )

    upper = term.upper()
    matches = DiagnosisCode.objects.filter(is_active=True).filter(
        Q(code__istartswith=term)
        | Q(title__icontains=term)
        | Q(keywords__icontains=term),
    )
    ranked = matches.annotate(
        rank=Case(
            When(code__iexact=upper, then=Value(0)),
            When(code__istartswith=upper, then=Value(1)),
            When(title__istartswith=term, then=Value(2)),
            When(title__icontains=term, then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        ),
    )
    return list(ranked.order_by("rank", "-times_used", "code")[:limit])


def describe(code: DiagnosisCode) -> dict:
    return {
        "code": code.code,
        "title": code.title,
        "chapter": code.chapter,
        "system": code.system,
        "is_common": code.is_common,
    }


def resolve(code: str) -> DiagnosisCode | None:
    """The row for a code, or `None`. Case and spacing forgiven."""
    cleaned = (code or "").strip().upper()
    if not cleaned:
        return None
    return DiagnosisCode.objects.filter(is_active=True, code__iexact=cleaned).first()


def note_use(code: str) -> None:
    """Count a code as used, so the list reorders towards this hospital."""
    from django.db.models import F

    cleaned = (code or "").strip().upper()
    if cleaned:
        DiagnosisCode.objects.filter(code__iexact=cleaned).update(times_used=F("times_used") + 1)


def vocabulary_exists() -> bool:
    """Whether this organization has a vocabulary at all.

    Validation is conditional on it: an organization whose table has not been
    seeded must not be prevented from recording a diagnosis, because the
    clinical fact matters more than the code, and a system that refuses the
    fact for want of a code is one people work around.
    """
    return DiagnosisCode.objects.filter(is_active=True).exists()


def uncoded_diagnoses(since=None, facility=None, limit: int = 200) -> dict:
    """Diagnoses recorded without a code, newest first.

    The answer to "what will the monthly return miss?" -- and the list
    somebody can work through to fix it.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.encounters.models import Diagnosis

    since = since or (timezone.localdate() - timedelta(days=30))
    rows = Diagnosis.objects.filter(icd10_code="", created_at__date__gte=since)
    if facility is not None:
        rows = rows.filter(encounter__facility=facility)
    rows = rows.select_related("patient", "encounter").order_by("-created_at")

    total = rows.count()
    coded = Diagnosis.objects.filter(created_at__date__gte=since).exclude(icd10_code="")
    if facility is not None:
        coded = coded.filter(encounter__facility=facility)
    coded_total = coded.count()

    return {
        "since": str(since),
        "uncoded": total,
        "coded": coded_total,
        "coded_percent": round(coded_total * 100 / (coded_total + total), 1) if (coded_total + total) else None,
        "rows": [
            {
                "diagnosis": row.name,
                "patient": row.patient.full_name,
                "mrn": row.patient.mrn,
                "encounter": row.encounter.reference,
                "recorded_by": row.diagnosed_by_name,
                "recorded_at": row.created_at,
            }
            for row in rows[:limit]
        ],
    }
