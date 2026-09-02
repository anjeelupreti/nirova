"""Filtering helpers.

`django_filters` generates a `ModelChoiceFilter` for a foreign key, which
matches on the primary key. Since the API publishes `uuid` and never `id`
(see `apps/common/fields.py`), a client filtering by the identifier it was
given would be told its choice "is not one of the available choices" -- a
message that sounds like a permissions problem and is really a type mismatch.

`uuid_filterset` builds a FilterSet where the named foreign keys are matched
on the related object's `uuid` instead.
"""

import django_filters


def uuid_filterset(model, relations=(), fields=()):
    """Build a FilterSet matching `relations` on uuid and `fields` normally.

    Written as a factory rather than a base class because the interesting part
    differs per model and the boilerplate does not::

        filterset_class = uuid_filterset(
            Sale, relations=["facility", "session"], fields=["status"]
        )
    """
    attrs = {
        name: django_filters.UUIDFilter(field_name=f"{name}__uuid")
        for name in relations
    }
    attrs["Meta"] = type("Meta", (), {"model": model, "fields": list(fields)})
    return type(f"{model.__name__}FilterSet", (django_filters.FilterSet,), attrs)
