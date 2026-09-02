"""Serializer fields shared across the API.

The rule they exist to keep: **an internal primary key never leaves the API.**

Every model here inherits `BaseModel`, which carries both an auto-incrementing
`id` (fast joins, small indexes) and a `uuid` (stable, non-guessable, safe to
put in a URL). DRF's default for a `ForeignKey` is the primary key, so a
serializer that lists `"facility"` in its fields quietly publishes the integer.

That is a problem in three ways, in increasing order of how much it costs:

1. Clients receive a `uuid` from one endpoint and an `id` from another for the
   same object, so a filter built from what they were given returns 400.
2. Sequential integers disclose how many patients, invoices or organizations
   exist -- and let anyone enumerate them.
3. Per-tenant databases mean `id` 42 is a different facility in every tenant.
   Anything that caches or logs a bare integer is ambiguous across tenants;
   a UUID never is.
"""

from rest_framework import serializers


class UUIDRelatedField(serializers.SlugRelatedField):
    """A foreign key represented by the related object's `uuid`.

    Read and write both: the client sends the same identifier it was given,
    which is the only way a round trip works without the client keeping a
    private mapping.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("slug_field", "uuid")
        super().__init__(**kwargs)

    def to_representation(self, obj):
        # str() rather than the raw UUID object, so the value is identical
        # whether it arrived through this field or through `uuid` on the
        # object's own serializer.
        return str(super().to_representation(obj))
