"""The bed board keeps the access tiers.

`GET /api/ipd/board/` puts every patient in a facility on one screen, with
their diagnosis and their NEWS2 score — which is exactly the shape of screen
that turns "may see the ward" into "may read everyone's clinical record" if
the tiers in `docs/ACCESS_DESIGN.md` are not held here. Who is in which bed is
identity; what they are in for and how sick they are is clinical.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
#: `nurse`: holds `patient.clinical.read`.
NURSE = f"nurse@{DEMO}.test"
#: `receptionist`: holds `encounter.read` — may see the ward — and not
#: `patient.clinical.read`.
RECEPTION = f"reception@{DEMO}.test"


def _client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        pytest.skip(f"no {email}; run manage.py seed_demo")
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
        raise_request_exception=False,
    )


def _board(client, facility):
    response = client.get(f"/api/ipd/board/?facility={facility.uuid}")
    assert response.status_code == 200, response.content[:300]
    return json.loads(response.content.decode())


def _occupants(board):
    return [
        bed["occupant"]
        for ward in board["wards"] for bed in ward["beds"]
        if bed["occupant"]
    ]


@pytest.fixture
def ward_facility(tenant):
    """A facility the receptionist can see that has somebody in a bed."""
    from apps.inpatient.models import BedAssignment

    assignment = (
        BedAssignment.objects.filter(vacated_at__isnull=True, ward__facility__facility_type="clinic")
        .select_related("ward__facility")
        .first()
    )
    if assignment is None:
        pytest.skip("no occupied clinic bed; run manage.py seed_nurse_demo")
    return assignment.ward.facility


def test_the_ward_clerk_sees_who_is_where_and_not_why(tenant, ward_facility):
    board = _board(_client(RECEPTION, tenant), ward_facility)
    occupants = _occupants(board)
    assert occupants, "the receptionist could not see who was in the beds"
    assert board["clinical"] is False
    for row in occupants:
        assert row["name"], "identity is the one thing a ward clerk needs"
        assert row["diagnosis"] is None, f"diagnosis leaked to a receptionist: {row['diagnosis']}"
        assert row["news2"] is None, "a NEWS2 score leaked to a receptionist"
        assert row["clinical_restricted"] is True, (
            "a withheld score must say it was withheld, not look like no observations"
        )


def test_the_nurse_sees_the_clinical_picture(tenant, ward_facility):
    board = _board(_client(NURSE, tenant), ward_facility)
    occupants = _occupants(board)
    assert occupants
    assert board["clinical"] is True
    assert all(row["clinical_restricted"] is False for row in occupants)
    assert any(row["diagnosis"] for row in occupants), "no diagnosis reached the nurse"


def test_the_counts_add_up(tenant, ward_facility):
    """Every bed is exactly one of occupied, free, being cleaned, reserved or
    out of service — or the headline numbers above the board lie."""
    board = _board(_client(NURSE, tenant), ward_facility)
    for ward in board["wards"]:
        counts = ward["counts"]
        states = (
            counts["occupied"] + counts["available"] + counts["cleaning"]
            + counts["reserved"] + counts["out_of_service"]
        )
        assert states == counts["beds"], (ward["code"], counts)
