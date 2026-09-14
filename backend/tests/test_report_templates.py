"""Report templates for narrative results.

What these hold: a test sees its own templates and its modality's general
ones but not another test's; applying composes the three headed sections the
printed report reads back; and a template with nothing to say is refused.
"""

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def reporter(tenant):
    from apps.identity.models import User

    return User.objects.get(email="owner@manakamana.test")


def _save(user, **overrides):
    from apps.diagnostics.report_templates import save_template

    data = {
        "name": "Chest, test",
        "test_code": "CXR",
        "modality": "xray",
        "findings": "Both lung fields clear.",
        "impression": "Normal chest X-ray.",
        "advice": "Nothing abnormal was seen.",
        **overrides,
    }
    return save_template(user=user, data=data)


def test_a_test_sees_its_own_and_its_modalitys_general_templates(reporter):
    from apps.diagnostics.report_templates import visible_to

    own = _save(reporter, name="CXR own")
    general = _save(reporter, name="Any X-ray", test_code="")
    other = _save(reporter, name="Ultrasound only", test_code="USG-ABD", modality="ultrasound")

    shown = set(visible_to(reporter, test_code="CXR", modality="xray").values_list("pk", flat=True))
    assert own.pk in shown and general.pk in shown
    assert other.pk not in shown, "another test's template was offered"


def test_applying_composes_the_headed_sections(reporter):
    from apps.diagnostics.report_templates import apply

    applied = apply(_save(reporter))
    assert applied["text"] == (
        "FINDINGS\nBoth lung fields clear.\n\n"
        "IMPRESSION\nNormal chest X-ray.\n\n"
        "ADVICE\nNothing abnormal was seen."
    )
    assert applied["times_used"] == 1


def test_a_template_with_nothing_to_say_is_refused(reporter):
    from apps.diagnostics.report_templates import TemplateError

    with pytest.raises(TemplateError):
        _save(reporter, findings="", impression="")
