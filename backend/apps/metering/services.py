"""Counting what a customer used, exactly once.

`UsageEvent.idempotency_key` was declared when metering was written, with a
partial unique constraint over `(organization, meter_key, idempotency_key)`
already in place -- **and no caller ever supplied a key**, so the constraint
guarded nothing and a retried registration billed the customer twice.

Both call sites had grown their own private `_meter` helper with the same body
and the same omission. One helper, and three things it gets right.

**The key describes the thing, not the moment.** `patient:<uuid>` is the same
key whether the request is the first attempt or the fourth, which is the only
property that makes a retry safe. A timestamp would be unique every time and
therefore useless.

**A duplicate is a success, not a failure.** "This was already counted" is
exactly what the constraint exists to say, so it is caught by name and returns
quietly. Logging it as an exception would fill the platform log with reports of
the mechanism working.

**The insert sits in a savepoint** -- and this is the part that would have
turned a harmless double-count into an outage. PostgreSQL aborts the entire
transaction on a constraint violation, so `except Exception: log and carry on`
does not carry on; every later query fails with "you can't execute queries
until the end of the atomic block". The existing helpers were safe only
*because* they never supplied a key and so never collided. **Adding the key
without the savepoint would have made patient registration fail** the second
time anybody retried one. Log 162, met for the fourth time.
"""

import logging

from django.db import IntegrityError, transaction

from apps.tenancy.context import CONTROL_PLANE_ALIAS

logger = logging.getLogger("nirova.metering")


def meter(organization, meter_key: str, key: str = "", quantity: int = 1,
          facility_uuid=None, actor_id=None, metadata: dict = None) -> bool:
    """Count one unit of usage. Returns whether it was newly counted.

    Never raises. A metering problem is a billing problem for the platform to
    fix, not a reason a patient cannot be registered -- that judgement was in
    both of the helpers this replaces and it is right.
    """
    from apps.metering.models import UsageEvent

    try:
        # On the control plane, because that is where UsageEvent lives; naming
        # the alias rather than relying on the ambient one keeps this correct
        # when it is called from inside a tenant transaction, which is always.
        with transaction.atomic(using=CONTROL_PLANE_ALIAS):
            UsageEvent.objects.create(
                organization=organization,
                meter_key=meter_key,
                quantity=quantity,
                idempotency_key=key,
                facility_uuid=facility_uuid,
                actor_id=actor_id,
                metadata=metadata or {},
            )
        return True
    except IntegrityError:
        # Already counted. The constraint doing its job is not an incident.
        logger.debug(
            "usage event %s/%s already counted for %s",
            meter_key, key, getattr(organization, "slug", organization),
        )
        return False
    except Exception:                                          # noqa: BLE001
        logger.exception(
            "failed to meter %s for %s",
            meter_key, getattr(organization, "slug", organization),
        )
        return False
