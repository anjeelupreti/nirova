"""Resolving a configuration value through the hierarchy.

`ConfigSetting` has stored the hierarchy since the organization module was
built -- platform default, organization, facility, department, most specific
winning -- and **nothing has ever read it**. The table had no reader at all,
while §14 of the checklist recorded the resolution as done. The rows were
right; the sentence describing what happened to them was not.

Written now because Phase 2 needs a per-organization switch, and the honest
place for one is the mechanism that already exists for exactly that.

Three decisions.

**Most specific wins, and absence is not a value.** A facility row of `false`
overrides an organization row of `true`; a *missing* facility row does not.
That is the distinction the whole table exists for, and it is easy to lose by
reaching for `.first()` on an unordered queryset.

**A locked value cannot be overridden by anything narrower.** Statutory tax
rates, controlled-drug rules, approval thresholds. The lock is checked on the
way down rather than trusted to whoever writes the narrower row, because a
constraint enforced only at write time is one that a data import walks past.

**Effective dating is applied, not merely stored.** A row whose window has
closed is not a value. Storing `effective_to` and then ignoring it would mean
a rate change scheduled for July silently applies in March.
"""

from django.db.models import Q
from django.utils import timezone

from apps.organization.models import ConfigScope, ConfigSetting

#: Sentinel so that `None` can be a legitimate stored value distinct from
#: "nothing is configured".
_MISSING = object()


def config_value(
    namespace: str,
    key: str,
    default=_MISSING,
    facility=None,
    department=None,
):
    """The value in force for this namespace and key, at this level.

    Resolution runs narrowest first and stops at the first row that applies,
    unless a broader row is locked -- a lock beats specificity, which is the
    point of locking.
    """
    now = timezone.now()
    rows = list(
        ConfigSetting.objects.filter(namespace=namespace, key=key)
        .filter(effective_from__lte=now)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
    )
    if not rows:
        if default is _MISSING:
            raise KeyError(f"No configuration for {namespace}.{key}")
        return default

    # A locked row anywhere above wins outright, however specific the row
    # below it is. Checked here rather than refused at write time, because a
    # constraint enforced only on the way in is one a data import walks past.
    for row in rows:
        if row.is_locked and row.scope == ConfigScope.ORGANIZATION:
            return row.value

    department_id = getattr(department, "id", department)
    facility_id = getattr(facility, "id", facility)

    def match(scope, **predicates):
        for row in rows:
            if row.scope != scope:
                continue
            if all(getattr(row, name) == value
                   for name, value in predicates.items()):
                return row
        return None

    if department_id is not None:
        found = match(ConfigScope.DEPARTMENT, department_id=department_id)
        if found is not None:
            return found.value
    if facility_id is not None:
        found = match(ConfigScope.FACILITY, facility_id=facility_id)
        if found is not None:
            return found.value

    found = match(ConfigScope.ORGANIZATION)
    if found is not None:
        return found.value

    if default is _MISSING:
        raise KeyError(f"No configuration for {namespace}.{key}")
    return default


def set_config_value(
    namespace: str,
    key: str,
    value,
    scope: str = ConfigScope.ORGANIZATION,
    facility=None,
    department=None,
    description: str = "",
    is_locked: bool = False,
) -> ConfigSetting:
    """Write one value at one level. Refuses to override a locked one."""
    if scope != ConfigScope.ORGANIZATION:
        locked = ConfigSetting.objects.filter(
            namespace=namespace, key=key,
            scope=ConfigScope.ORGANIZATION, is_locked=True,
        ).exists()
        if locked:
            from apps.common.exceptions import DomainError

            raise DomainError(
                f"{namespace}.{key} is fixed for the whole organization and "
                "cannot be changed for one facility or department."
            )

    setting, _ = ConfigSetting.objects.update_or_create(
        namespace=namespace, key=key, scope=scope,
        facility=facility, department=department,
        defaults={
            "value": value,
            "description": description,
            "is_locked": is_locked,
        },
    )
    return setting
