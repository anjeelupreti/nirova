"""Allocating the next human-readable reference: EX-000004, SI-000012, REF-000007.

**Every one of these was `objects.count() + 1`, and that is broken twice over.**

*It collides after a deletion, deterministically.* `BaseModel` soft-deletes:
`objects` filters `deleted_at__isnull=True`, while the `unique=True` on the
reference column still sees the deleted row. Delete one expense and the count
drops by one, so the next claim is allocated a reference that already exists and
the insert fails with a `UniqueViolation` -- a 500 on a form somebody filled in.
**Any tenant that has ever deleted one of these can never create another.** Found
when a test deleted the expenses it created and the next run of the same test
died on the reference.

*And it repeats under concurrency.* Two clerks claiming at the same moment both
read the same count and both compute the same reference.

This module fixes the first completely and narrows the second. It reads the
**highest reference already issued** rather than counting rows, across
`all_objects` so that soft-deleted references are still respected. A number once
issued is never reissued, which is the property a reference has to have: it is
quoted on paper, in an email, and down a telephone.

The residual race is real and is stated rather than papered over: two callers
can still read the same maximum. The unique constraint is the backstop -- it
turns a duplicate into a failed write rather than two documents sharing a
number, which is the right way round. A gapless, contended sequence needs a
`SELECT ... FOR UPDATE` on a counter row per tenant, and that is worth building
when somebody is actually issuing these concurrently rather than before.
"""

import re

#: `EX-000004` -> 4. Anchored so that a reference from a different series, or
#: one somebody typed by hand, does not contribute a number to this series.
def _tail(value: str, prefix: str) -> int | None:
    match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", value or "")
    return int(match.group(1)) if match else None


def next_reference(model, prefix: str, *, field: str = "reference", width: int = 6) -> str:
    """The next reference in `prefix`'s series for `model`.

    Reads from `all_objects` when the model has it, so a soft-deleted document
    keeps its number reserved. Falls back to `objects` for models that do not
    soft-delete.

    Scans only the references that match this prefix: a model may carry more
    than one series (`SI-` and `CN-` on the same table), and mixing them would
    make the next credit note follow the last invoice.
    """
    manager = getattr(model, "all_objects", None) or model.objects
    highest = 0
    for value in manager.filter(
        **{f"{field}__startswith": f"{prefix}-"}
    ).values_list(field, flat=True):
        number = _tail(value, prefix)
        if number and number > highest:
            highest = number
    return f"{prefix}-{highest + 1:0{width}d}"
