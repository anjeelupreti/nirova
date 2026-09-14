"""The monthly return: counted from the records, honest about what is missing.

What these hold: attendance is banded by age **at the visit** and split into
new and repeat by whether the patient had been here before; the sections the
system cannot honestly fill are named rather than filed as zero; and the
return is registered as a report so it is reachable, permissioned and
exportable like every other.
"""

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


def test_the_bands_are_age_at_the_visit():
    from apps.organization.hmis import _band

    born = date(2020, 6, 1)
    assert _band(born, date(2021, 5, 31)) == "<1", "a child was banded by age today"
    assert _band(born, date(2021, 6, 1)) == "1-4"
    assert _band(born, date(2026, 6, 1)) == "5-14"
    assert _band(None, date(2026, 6, 1)) == "unknown"


def test_the_return_counts_visits_and_splits_new_from_repeat(tenant):
    from apps.organization.hmis import monthly_return

    body = monthly_return(since=date.today() - timedelta(days=60))

    assert body["total_visits"] == sum(row["total"] for row in body["attendance"])
    assert body["new_patients"] == sum(row["new"] for row in body["attendance"])
    assert body["new_patients"] <= body["total_visits"]
    for row in body["attendance"]:
        assert row["total"] == row["new"] + row["repeat"]


def test_a_patient_is_new_once_however_often_they_attend(tenant):
    """The first version counted every visit of a first-time patient as new,
    which turned 197 demo visits into 197 new patients."""
    from django.db.models import Count

    from apps.encounters.models import Encounter
    from apps.organization.hmis import monthly_return

    body = monthly_return(since=date.today() - timedelta(days=365))
    seen_more_than_once = (
        Encounter.objects.values("patient_id").annotate(n=Count("id")).filter(n__gt=1).count()
    )
    distinct_patients = Encounter.objects.values("patient_id").distinct().count()

    assert body["new_patients"] <= distinct_patients, (
        "more new patients than patients: a repeat attendance was counted as new"
    )
    if seen_more_than_once:
        assert body["new_patients"] < body["total_visits"], (
            "somebody attended twice and both visits were counted as new"
        )


def test_what_cannot_be_counted_is_named_not_zeroed(tenant):
    from apps.organization.hmis import monthly_return

    sections = {row["section"] for row in monthly_return()["not_collected"]}
    assert {"Immunisation", "Family planning"} <= sections, (
        "a section the system does not record was filed as a figure"
    )
    for row in monthly_return()["not_collected"]:
        assert row["why"], "a missing section gave no reason"


def test_morbidity_is_coded_and_the_uncoded_are_counted(tenant):
    from apps.organization.hmis import monthly_return

    body = monthly_return(since=date.today() - timedelta(days=60))
    for row in body["morbidity"]:
        assert row["code"], "an uncoded diagnosis reached the morbidity table"
    assert body["uncoded_diagnoses"] >= 0
    if body["morbidity"] or body["uncoded_diagnoses"]:
        assert body["coded_percent"] is not None


def test_it_is_registered_as_a_report(tenant):
    from apps.reporting.registry import get_report

    report = get_report("hmis.monthly")
    assert report is not None, "the return is not in the report library"
    assert report.permission == "report.read"
    assert "facility" in report.parameters and "since" in report.parameters


def test_the_report_runs_over_http(tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.get(email="owner@manakamana.test")
    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    response = client.get("/api/reports/hmis.monthly/")
    assert response.status_code == 200, response.content
    assert "attendance" in response.json().get("result", response.json())
