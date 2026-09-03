"""An answer cannot predate the visit it reports on — and repair the rows.

This constraint exists because of the previous migration. `0002` straightened
referrals seen before they were sent by pulling `seen_at` forward to
`sent_at` — which, on any row that had already been answered, pushed the
sighting past its own response and made the time-to-answer negative.

A repair to one ordering broke another. Both are now stated, and both are
repaired the same way: move the later timestamp to the earlier one's value,
which is the earliest moment the event could defensibly have happened.
"""

from django.db import migrations, models


def straighten_answers(apps, schema_editor):
    Referral = apps.get_model("referrals", "Referral")
    alias = schema_editor.connection.alias
    rows = Referral.objects.using(alias).filter(
        responded_at__isnull=False, seen_at__isnull=False,
    )
    for referral in rows:
        if referral.responded_at < referral.seen_at:
            referral.responded_at = referral.seen_at
            # The alias has to be repeated on the save: a queryset's `.using`
            # does not travel to the instance, and the router raises during a
            # migration because no tenant is bound.
            referral.save(using=alias, update_fields=["responded_at"])

    # The responses carry their own timestamps, and the same reversal.
    Response = apps.get_model("referrals", "ReferralResponse")
    for response in Response.objects.using(alias).select_related("referral"):
        seen = response.referral.seen_at
        if seen and response.responded_at < seen:
            response.responded_at = seen
            response.save(using=alias, update_fields=["responded_at"])


def leave_alone(apps, schema_editor):
    """Nothing to undo: the repaired dates are the defensible ones."""


class Migration(migrations.Migration):

    dependencies = [
        ("referrals", "0002_referral_seen_after_sent"),
    ]

    operations = [
        migrations.RunPython(straighten_answers, leave_alone),
        migrations.AddConstraint(
            model_name="referral",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("responded_at__isnull", True),
                    ("seen_at__isnull", True),
                    ("responded_at__gte", models.F("seen_at")),
                    _connector="OR",
                ),
                name="answer_after_seen",
            ),
        ),
    ]
