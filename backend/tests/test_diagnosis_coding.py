"""Coding a diagnosis: the search, and the refusal.

What these hold: the search puts an exact code first and finds a term by the
word somebody would type rather than the classification's wording; a code
that is not in the vocabulary is refused rather than stored, because a code
nobody can look up is counted by the monthly return as though it were real;
a coded diagnosis takes the classification's title when none was typed; and
an organization with no vocabulary yet is never prevented from recording the
clinical fact.
"""

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def vocabulary(tenant):
    from apps.terminology.models import CodeSystem, DiagnosisCode

    rows = [
        ("A01.0", "Typhoid fever", "Infections", "enteric fever widal"),
        ("E11.9", "Type 2 diabetes mellitus", "Endocrine", "diabetes sugar dm"),
        ("I10", "Essential hypertension", "Circulatory", "bp high blood pressure"),
        ("J18.9", "Pneumonia, unspecified", "Respiratory", "chest infection"),
    ]
    for code, title, chapter, keywords in rows:
        DiagnosisCode.objects.update_or_create(
            system=CodeSystem.ICD10, code=code,
            defaults={"title": title, "chapter": chapter, "keywords": keywords, "is_common": True},
        )
    return DiagnosisCode.objects.all()


def test_an_exact_code_comes_first(vocabulary):
    from apps.terminology.services import search

    assert search("I10")[0].code == "I10"


def test_a_term_is_found_by_the_word_somebody_would_type(vocabulary):
    from apps.terminology.services import search

    codes = [row.code for row in search("sugar")]
    assert "E11.9" in codes, "the word a clinician types did not find the code"

    codes = [row.code for row in search("bp")]
    assert "I10" in codes


def test_an_unknown_code_is_refused(vocabulary, tenant):
    from apps.common.exceptions import DomainError
    from apps.encounters.models import Encounter
    from apps.encounters.services import add_diagnosis

    encounter = Encounter.objects.first()
    if encounter is None:
        pytest.skip("no demo encounters")

    with pytest.raises(DomainError):
        add_diagnosis(encounter, {"name": "Something", "icd10_code": "ZZ9.9"})


def test_a_known_code_fills_the_classifications_title(vocabulary, tenant):
    from apps.encounters.models import Encounter
    from apps.encounters.services import add_diagnosis
    from apps.terminology.models import DiagnosisCode

    encounter = Encounter.objects.first()
    if encounter is None:
        pytest.skip("no demo encounters")

    before = DiagnosisCode.objects.get(code="A01.0").times_used
    diagnosis = add_diagnosis(encounter, {"name": "", "icd10_code": "a01.0"})

    assert diagnosis.icd10_code == "A01.0", "the code was not normalised"
    assert diagnosis.name == "Typhoid fever"
    assert DiagnosisCode.objects.get(code="A01.0").times_used == before + 1


def test_without_a_vocabulary_the_clinical_fact_is_still_recorded(tenant):
    """A hospital whose table has not been seeded must not be stopped from
    recording a diagnosis: the fact matters more than the code."""
    from apps.encounters.models import Encounter
    from apps.encounters.services import add_diagnosis
    from apps.terminology.models import DiagnosisCode

    DiagnosisCode.objects.all().delete()
    encounter = Encounter.objects.first()
    if encounter is None:
        pytest.skip("no demo encounters")

    diagnosis = add_diagnosis(encounter, {"name": "Chest infection", "icd10_code": "J18.9"})
    assert diagnosis.icd10_code == "J18.9"


def test_the_uncoded_report_counts_both_sides(vocabulary, tenant):
    from apps.encounters.models import Encounter
    from apps.encounters.services import add_diagnosis
    from apps.terminology.services import uncoded_diagnoses

    encounter = Encounter.objects.first()
    if encounter is None:
        pytest.skip("no demo encounters")
    add_diagnosis(encounter, {"name": "Uncoded thing"})
    add_diagnosis(encounter, {"name": "Coded thing", "icd10_code": "I10"})

    report = uncoded_diagnoses()
    assert report["uncoded"] >= 1 and report["coded"] >= 1
    assert 0 <= report["coded_percent"] <= 100
    assert any(row["diagnosis"] == "Uncoded thing" for row in report["rows"])


def test_the_search_endpoint_opens_for_a_clinician(vocabulary, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.get(email="owner@manakamana.test")
    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    response = client.get("/api/clinical/diagnosis-codes/?q=typh")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["vocabulary"] is True
    assert body["results"][0]["code"] == "A01.0"
