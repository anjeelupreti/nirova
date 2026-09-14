"""The one socket a console opens.

**Authenticated by message, not by URL.** A token in the query string is
written into every access log between the browser and here. The browser
connects, then sends `{"type": "auth", "token", "organization"}`; a socket that
has not authenticated within ten seconds is closed. The token is checked the
way the HTTP authenticator checks it — signature, expiry, an active account,
and not issued before the password last changed — and the organization is
checked against the account's live memberships, so a token for one hospital
cannot listen to another's queue.

**Subscriptions are topics from a fixed list** (`publish.TOPIC`). What arrives
is only ever "this changed", so subscribing to a facility's queue discloses
that its queue moves and nothing about who is in it; the organization check is
what keeps even that inside the tenant.
"""

import asyncio
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.realtime.publish import TOPIC, group_for

logger = logging.getLogger("nirova.realtime")

AUTH_TIMEOUT_SECONDS = 10
MAX_TOPICS = 20


@database_sync_to_async
def _authenticate(token: str, organization_slug: str):
    """The user and organization slug, or `None`. Never raises."""
    try:
        from rest_framework_simplejwt.tokens import AccessToken

        from apps.identity.authentication import issued_before_password_change
        from apps.identity.models import Membership, MembershipStatus, User

        access = AccessToken(token)
        user = User.objects.filter(id=access.get("user_id"), is_active=True).first()
        if user is None or issued_before_password_change(user, access):
            return None
        member = Membership.objects.filter(
            user=user,
            organization__slug=organization_slug,
            status=MembershipStatus.ACTIVE,
        ).exists()
        if not member:
            return None
        return user
    except Exception:  # noqa: BLE001 — a bad token is a closed socket, not a trace
        return None


class LiveConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = None
        self.slug = ""
        self.groups_joined: set[str] = set()
        await self.accept()
        self._deadline = asyncio.create_task(self._close_if_silent())

    async def _close_if_silent(self):
        await asyncio.sleep(AUTH_TIMEOUT_SECONDS)
        if self.user is None:
            await self.close(code=4001)

    async def disconnect(self, code):
        deadline = getattr(self, "_deadline", None)
        if deadline is not None:
            deadline.cancel()
        for group in list(getattr(self, "groups_joined", ())):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type")

        if kind == "auth":
            user = await _authenticate(
                str(content.get("token", "")), str(content.get("organization", "")),
            )
            if user is None:
                await self.send_json({"type": "refused"})
                await self.close(code=4003)
                return
            self.user = user
            self.slug = str(content.get("organization", ""))
            await self._join("notifications")
            await self.send_json({"type": "ready"})
            return

        if self.user is None:
            await self.close(code=4001)
            return

        if kind == "subscribe":
            topic = str(content.get("topic", ""))
            if not TOPIC.match(topic) or len(self.groups_joined) >= MAX_TOPICS:
                await self.send_json({"type": "refused", "topic": topic})
                return
            await self._join(topic)

    async def _join(self, topic: str):
        group = group_for(self.slug, topic, str(self.user.uuid))
        if group in self.groups_joined:
            return
        await self.channel_layer.group_add(group, self.channel_name)
        self.groups_joined.add(group)

    async def doorbell(self, event):
        await self.send_json({"type": "changed", "topic": event.get("topic", "")})
