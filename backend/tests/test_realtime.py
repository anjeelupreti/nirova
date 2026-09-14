"""The doorbell: who may hear it, and what it says.

Every live screen polled — the queue every fifteen seconds, the bed board every
two minutes — and the socket that replaces the wait is only safe on two
conditions, which are what these check. **It lets nobody listen who could not
read the screen's API**: a socket that has not authenticated is closed, a token
for one hospital cannot listen to another's, and only topics from a fixed list
may be subscribed. And **it says nothing**: what crosses it is "this changed",
never a name, a bed or a token, so the screen refetches through the API where
authorisation already lives.
"""

import pytest
from asgiref.sync import async_to_sync
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

FACILITY = "0f3c5a1e-8d2b-4c6f-9a7e-1b2c3d4e5f60"


@pytest.fixture(autouse=True)
def memory_layer(settings):
    """An in-process channel layer, so the tests need no Redis."""
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    from channels.layers import channel_layers

    channel_layers.backends.clear()
    yield
    channel_layers.backends.clear()


def _token(email: str) -> str:
    from apps.identity.models import User

    return str(RefreshToken.for_user(User.objects.get(email=email)).access_token)


def _run(scenario):
    """Drive one socket conversation from a synchronous test."""
    from channels.testing import WebsocketCommunicator

    from apps.realtime.consumers import LiveConsumer

    async def go():
        communicator = WebsocketCommunicator(LiveConsumer.as_asgi(), "/ws/")
        connected, _ = await communicator.connect()
        assert connected
        try:
            return await scenario(communicator)
        finally:
            await communicator.disconnect()

    return async_to_sync(go)()


def test_a_socket_that_never_authenticates_is_closed(tenant, monkeypatch):
    from apps.realtime import consumers

    monkeypatch.setattr(consumers, "AUTH_TIMEOUT_SECONDS", 0.1)

    async def scenario(socket):
        message = await socket.receive_output(timeout=2)
        return message

    closed = _run(scenario)
    assert closed["type"] == "websocket.close"
    assert closed["code"] == 4001


def test_a_token_for_this_hospital_is_let_in(tenant):
    token = _token("owner@manakamana.test")

    async def scenario(socket):
        await socket.send_json_to({"type": "auth", "token": token, "organization": tenant.slug})
        return await socket.receive_json_from(timeout=2)

    assert _run(scenario) == {"type": "ready"}


def test_a_token_cannot_listen_to_another_hospital(tenant):
    """Tenant isolation, at the socket: a real account, a real token, and an
    organization it has no membership of."""
    token = _token("owner@manakamana.test")

    async def scenario(socket):
        await socket.send_json_to({
            "type": "auth", "token": token, "organization": "some-other-hospital",
        })
        return await socket.receive_json_from(timeout=2)

    assert _run(scenario) == {"type": "refused"}


def test_a_forged_token_is_refused(tenant):
    async def scenario(socket):
        await socket.send_json_to({
            "type": "auth", "token": "not.a.token", "organization": tenant.slug,
        })
        return await socket.receive_json_from(timeout=2)

    assert _run(scenario) == {"type": "refused"}


def test_only_topics_from_the_list_may_be_subscribed(tenant):
    token = _token("owner@manakamana.test")

    async def scenario(socket):
        await socket.send_json_to({"type": "auth", "token": token, "organization": tenant.slug})
        await socket.receive_json_from(timeout=2)
        await socket.send_json_to({"type": "subscribe", "topic": "patients.everything"})
        return await socket.receive_json_from(timeout=2)

    refused = _run(scenario)
    assert refused["type"] == "refused"


def test_the_doorbell_says_that_something_changed_and_nothing_else(tenant):
    """The message a subscriber receives is the topic and nothing more: no
    names, no beds, no identifiers beyond the facility it was asked about."""
    from channels.layers import get_channel_layer

    from apps.realtime.publish import group_for

    token = _token("owner@manakamana.test")
    topic = f"queue.{FACILITY}"

    async def scenario(socket):
        await socket.send_json_to({"type": "auth", "token": token, "organization": tenant.slug})
        await socket.receive_json_from(timeout=2)
        await socket.send_json_to({"type": "subscribe", "topic": topic})
        # Give the subscription a moment to register before ringing.
        await socket.receive_nothing(timeout=0.1)
        await get_channel_layer().group_send(
            group_for(tenant.slug, topic),
            {"type": "doorbell", "topic": topic, "patient": "must not be forwarded"},
        )
        return await socket.receive_json_from(timeout=2)

    message = _run(scenario)
    assert message == {"type": "changed", "topic": topic}, (
        "the socket forwarded more than that something changed"
    )


def test_a_ring_waits_for_the_commit(tenant, django_capture_on_commit_callbacks):
    """Rung inside the transaction, a browser could refetch before the row is
    visible and show the old state with confidence."""
    from apps.realtime.publish import ring

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        ring(f"queue.{FACILITY}")
    assert len(callbacks) == 1, "the doorbell rang before the change committed"


def test_an_unlisted_topic_is_never_rung(tenant, django_capture_on_commit_callbacks):
    from apps.realtime.publish import ring

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        ring("everything")
    assert callbacks == []


def test_a_new_notification_rings_every_recipients_bell(tenant, monkeypatch):
    """Receipts are written with bulk_create, which sends no post_save; a bell
    that relied on the signal alone stayed silent until its minute poll."""
    from apps.identity.models import User
    from apps.notifications.models import NotificationCategory
    from apps.notifications.services import notify
    from apps.realtime import publish

    rung = []
    monkeypatch.setattr(publish, "ring", lambda topic, **kw: rung.append((topic, kw.get("user_uuid"))))

    owner = User.objects.get(email="owner@manakamana.test")
    notify(
        source="test", event="doorbell", title="Rota published", body="",
        category=NotificationCategory.INFORMATION,
        recipients=[{"id": owner.uuid, "name": owner.full_name, "reason": "test"}],
    )
    assert ("notifications", str(owner.uuid)) in rung


@pytest.mark.parametrize("topic", [
    f"ed.{FACILITY}", f"lab.{FACILITY}", f"icu.{FACILITY}",
])
def test_the_clinical_boards_are_listed_topics(topic):
    from apps.realtime.publish import TOPIC

    assert TOPIC.match(topic)


def test_a_lab_order_rings_its_facilitys_bench(tenant, django_capture_on_commit_callbacks):
    """Changing an order reaches the lab board of the facility it belongs to."""
    from apps.diagnostics.models import DiagnosticOrder

    order = DiagnosticOrder.objects.select_related("facility").first()
    if order is None:
        pytest.skip("no demo diagnostic orders")
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        order.save(update_fields=["updated_at"])
    assert callbacks, "saving a lab order rang nothing"


def test_an_icu_stay_rings_its_unit(tenant, django_capture_on_commit_callbacks):
    from apps.icu.models import IcuStay

    stay = IcuStay.objects.first()
    if stay is None:
        pytest.skip("no demo ICU stays")
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        stay.save(update_fields=["updated_at"])
    assert callbacks, "saving an ICU stay rang nothing"


def test_an_ed_arrival_rings_its_department(tenant, django_capture_on_commit_callbacks):
    from apps.emergency.models import Arrival

    arrival = Arrival.objects.first()
    if arrival is None:
        pytest.skip("no demo arrivals")
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        arrival.save(update_fields=["updated_at"])
    assert callbacks, "saving an ED arrival rang nothing"
