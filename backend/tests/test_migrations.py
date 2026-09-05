"""The model state and the migrations must agree.

Log 156. `portal_patientcorrectionrequest` was missing two columns its model
declared, because the migration had been hand-written and the model inherits
`BaseModel`. Every write failed on the first insert -- through a model, four
service functions, an API and two user interfaces, none of which could store a
row, and nothing noticed.

`makemigrations --check` would have said so in one second.
"""

import pytest
from django.core.management import call_command


@pytest.mark.django_db(databases="__all__")
def test_no_missing_migrations():
    """Fails if any model change has not been written into a migration."""
    try:
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)
    except SystemExit as exc:
        pytest.fail(
            "models and migrations disagree -- run `manage.py makemigrations`. "
            f"(exit {exc.code})"
        )
