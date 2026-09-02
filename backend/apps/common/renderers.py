"""JSON rendering that does not turn money into a float.

DRF's serializers can be told to render `DecimalField` as a string, but that
setting only covers serializer fields. A view that returns a plain dict --
which most of the reporting and dashboard endpoints do, because their shape is
computed rather than modelled -- goes straight to the JSON encoder, and the
encoder's default for `Decimal` is `float`.

That is exactly the conversion the whole billing module exists to avoid. A
total of `1234.55` becomes `1234.5499999999999` on the way out, a client
formats it, and a customer is shown a figure that disagrees with their
invoice. The precision was correct all the way to the last step.

So: `Decimal` renders as a string, everywhere, without each view having to
remember. Clients parse it with `Number()` where they need arithmetic and
print it verbatim where they do not.
"""

import decimal

from rest_framework.renderers import JSONRenderer
from rest_framework.utils import encoders


class NirovaJSONEncoder(encoders.JSONEncoder):
    """DRF's encoder, with `Decimal` kept exact."""

    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return str(obj)
        return super().default(obj)


class NirovaJSONRenderer(JSONRenderer):
    encoder_class = NirovaJSONEncoder
