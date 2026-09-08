"""Which facility a demo seed should hang its data off.

Nine seeds opened with `Facility.objects.filter(facility_type="hospital")
.first()` and then used the result without checking it. That worked on every
developer's machine and on no fresh tenant, because **the demo organization
has no hospital by design**: `seed_demo` requests one, the Professional plan
does not include the hospital module, and the request escalates to the
platform instead of proceeding. That escalation is the point of that part of
the seed -- it demonstrates the entitlement rule refusing something.

So the demo estate is a clinic, a laboratory and a pharmacy, and any seed that
assumed a hospital crashed on `None` the first time it ran against a tenant
nobody had hand-fixed. Three seeds had already learned this and grown a
`or ...filter(facility_type="clinic").first()` fallback locally. This is that
fallback, written once.
"""

from django.core.management.base import CommandError

#: Preference order. A hospital if the tenant has one -- an inpatient ward or
#: an operating theatre belongs there -- then a clinic, which is what the demo
#: organization actually has. Anything at all is better than failing: a seed
#: that runs in a pharmacy demonstrates less than one in a hospital, and far
#: more than one that raises AttributeError.
PREFERRED_TYPES = ("hospital", "clinic")


def demo_facility(exclude=None):
    """The best facility available for demo data, or a clear error.

    `exclude` takes a facility to avoid, for the seeds that need two distinct
    ones -- a referral from a clinic to a hospital is not a referral if both
    ends are the same building. When no second facility exists the caller gets
    the same one back rather than `None`, because a degenerate referral still
    exercises the code and a missing one does not.
    """
    from apps.organization.models import Facility

    queryset = Facility.objects.all()
    if exclude is not None:
        alternatives = queryset.exclude(pk=exclude.pk)
        if alternatives.exists():
            queryset = alternatives

    for facility_type in PREFERRED_TYPES:
        facility = queryset.filter(facility_type=facility_type).first()
        if facility is not None:
            return facility

    facility = queryset.first()
    if facility is None:
        raise CommandError(
            "This tenant has no facilities at all. Run `manage.py seed_demo` "
            "first, or `manage.py bootstrap` to do the whole sequence."
        )
    return facility
