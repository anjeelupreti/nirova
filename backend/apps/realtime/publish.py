"""Ringing the doorbell.

Every live screen in the console polled: the queue every fifteen seconds, the
bed board every two minutes, the notification bell every minute. That is
fifteen seconds between a patient being called and the waiting-room screen
knowing, and a request per open board per interval whether or not anything
happened.

**A doorbell, not a data channel.** What travels is `{"type": "changed",
"topic": "queue.<facility>"}` and nothing else — no names, no tokens, no bed
numbers. The screen that hears it refetches through the ordinary API, which is
where authorisation, scope, care relationships and the audit trail already
live. A socket that carried the data would be a second API with its own
permission checks, and the day they drifted a ward list would leak to a
socket that should never have had it.

**After the commit.** A doorbell rung inside the transaction can reach a
browser that refetches before the row is visible, and the screen then shows
the old state confidently. `on_commit` rings it once the change is real.

**Never raises.** Redis being away is a slower screen — polling still runs as
the safety net — not a failed admission.
"""

import logging
import re

from asgiref.sync import async_to_sync
from django.db import transaction

logger = logging.getLogger("nirova.realtime")

#: What may be subscribed to. Anything else is refused at the socket.
TOPIC = re.compile(r"^(notifications|(queue|beds|ed|lab|icu)\.[0-9a-f-]{36})$")


def group_for(organization_slug: str, topic: str, user_uuid: str = "") -> str:
    """The Channels group a topic lives in, always inside one tenant.

    The organization is part of every name, so two hospitals' queues can never
    share a group however their facility identifiers compare. Channels allows
    only letters, digits, hyphens, underscores and dots in a group name — hence
    dots rather than the colons one would reach for.
    """
    if topic == "notifications":
        return f"t.{organization_slug}.user.{user_uuid}"
    return f"t.{organization_slug}.{topic}"


def ring(topic: str, *, user_uuid: str = "", organization_slug: str = "") -> None:
    """Tell anybody listening that `topic` changed, once the change commits."""
    if not organization_slug:
        from apps.tenancy.context import get_current_tenant

        organization_slug = getattr(get_current_tenant(), "organization_slug", "")
    if not organization_slug or not TOPIC.match(topic):
        return

    group = group_for(organization_slug, topic, user_uuid)

    def send():
        try:
            from channels.layers import get_channel_layer

            layer = get_channel_layer()
            if layer is None:
                return
            async_to_sync(layer.group_send)(
                group, {"type": "doorbell", "topic": topic},
            )
        except Exception:  # noqa: BLE001 — a slower screen, not a failed act
            logger.warning("could not ring %s", group, exc_info=True)

    transaction.on_commit(send)
