"""Put the facility code into every invoice-number prefix.

The sequences were always per facility; the *rendered* number was not, so the
second facility in an organization to issue an invoice on a given day collided
on `Invoice.number`, which is unique tenant-wide.

Existing numbers are left exactly as they are. An issued invoice is a
statutory document — its number is what was handed to a customer and printed
on their receipt, and no migration gets to rewrite it. Only the prefix used
for numbers issued from now on changes.
"""

from django.db import migrations


def set_prefixes(apps, schema_editor):
    # `.using(alias)` explicitly, not the router. The router deliberately
    # raises when no organization is bound, and a migration runs outside any
    # request so nothing is bound -- but the alias being migrated is right
    # here on the schema editor, which is more precise than ambient context
    # would have been anyway.
    alias = schema_editor.connection.alias
    NumberSequence = apps.get_model("billing", "NumberSequence")
    for sequence in NumberSequence.objects.using(alias).select_related("facility"):
        if sequence.prefix:
            continue
        sequence.prefix = (
            f"{sequence.document_type[:3].upper()}-{sequence.facility.code}"
        )
        sequence.save(using=alias, update_fields=["prefix"])


def clear_prefixes(apps, schema_editor):
    # Reversible only in the sense that the field goes back to blank; the
    # numbers already issued under either format stay untouched.
    alias = schema_editor.connection.alias
    NumberSequence = apps.get_model("billing", "NumberSequence")
    NumberSequence.objects.using(alias).update(prefix="")


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_alter_invoice_patient_alter_payment_patient"),
    ]
    operations = [migrations.RunPython(set_prefixes, clear_prefixes)]
