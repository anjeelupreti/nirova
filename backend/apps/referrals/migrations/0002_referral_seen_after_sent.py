"""Refuse a referral seen before it was sent, and fix the ones that are.

The constraint cannot go on without the repair: any existing row where
`seen_at` precedes `sent_at` blocks the migration, and there is no way to add
a rule to a table that already breaks it.

A referral seen before anybody sent it is a date entered wrongly, not a
transaction that happened in a strange order. The defensible repair is to pull
the sighting forward to the moment of sending — the earliest time it could
have happened — which makes the waiting time zero rather than negative. A
negative wait is not obviously wrong to anybody reading a report, which is
exactly why it survived long enough to need this.
"""

from django.db import migrations, models


def straighten_reversed_dates(apps, schema_editor):
    Referral = apps.get_model("referrals", "Referral")
    # `.using(...)` because the tenant router raises rather than guessing when
    # no tenant is bound, and a migration runs outside that context.
    alias = schema_editor.connection.alias
    rows = Referral.objects.using(alias).filter(
        seen_at__isnull=False, sent_at__isnull=False,
    )
    for referral in rows:
        if referral.seen_at < referral.sent_at:
            referral.seen_at = referral.sent_at
            # The alias has to be repeated on the save: a queryset's `.using`
            # does not travel to the instance, and without it the router
            # raises because no tenant is bound during a migration.
            referral.save(using=alias, update_fields=["seen_at"])


def leave_alone(apps, schema_editor):
    """Nothing to undo: the repaired dates are the defensible ones."""


class Migration(migrations.Migration):

    dependencies = [
        ("encounters", "0001_initial"),
        ("organization", "0002_remove_configsetting_uniq_config_per_scope_and_more"),
        ("patients", "0001_initial"),
        ("referrals", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(straighten_reversed_dates, leave_alone),
        migrations.AddConstraint(
            model_name="referral",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("seen_at__isnull", True),
                    ("sent_at__isnull", True),
                    ("seen_at__gte", models.F("sent_at")),
                    _connector="OR",
                ),
                name="seen_after_sent",
            ),
        ),
    ]
