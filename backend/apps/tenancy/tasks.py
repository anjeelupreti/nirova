"""Background work for the tenancy layer.

The first task this project has — Celery and its beat scheduler have run in
the stack since the beginning with nothing to do.
"""

from celery import shared_task
from django.conf import settings
from django.core.management import call_command


@shared_task(name="demo.advance_day")
def advance_demo_day() -> str:
    """Bring the demonstration tenant's day up to now.

    `seed_demo_day` tops the day up and moves every open case along its own
    clock, so running it every half hour keeps the demonstration alive: the
    two o'clock nursing round is recorded at two, the afternoon discharges go
    home in the afternoon, the queue keeps moving. Without it the demo froze at
    whatever time somebody last ran a seed, and by evening every NEWS2 score on
    the ward was, correctly, marked out of date.

    Off unless `NIROVA_DEMO_DAY_SLUG` names a tenant. A generator that admits
    and discharges patients must never be one environment variable away from
    running against a customer, so the default is nothing and the schedule is
    only registered when the variable is set.
    """
    slug = getattr(settings, "NIROVA_DEMO_DAY_SLUG", "")
    if not slug:
        return "disabled"
    call_command("seed_demo_day", slug=slug)
    return f"advanced {slug}"
