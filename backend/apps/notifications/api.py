"""Notification endpoints. Everything here is scoped to the caller.

**There is no permission on reading an inbox, because an inbox is not shared.**
Every endpoint resolves the recipient from `request.user` and never from a
parameter. A `?user=` filter would be an authorization decision disguised as a
query string, and the first time somebody needed "the manager's view" it would
be granted by adding a parameter rather than a permission.

**Nothing here sends a notification.** Notifications are side effects of things
that happen in other modules, raised through `notify()`. An endpoint that let a
client post an arbitrary notification to arbitrary people would be a way to
make the hospital's alert system say anything, which is a strange thing to
build on purpose. The one exception is the announcement endpoint, which is
gated on `notification.broadcast` and says who sent it.

**Marking read and dismissing are separate endpoints** because they are
separate acts, and `read-all` deliberately does not dismiss: catching up on a
morning's notifications is not the same as approving what is in them.
"""

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission, get_authorization
from apps.notifications.models import (
    Notification,
    NotificationCategory,
    NotificationReceipt,
)
from apps.notifications.services import (
    dismiss,
    inbox,
    mark_all_read,
    mark_read,
    notify,
    preferences_for,
    set_preference,
    summary,
)


class NotificationSerializer(serializers.ModelSerializer):
    """The receipt is what a person has; the notification is what happened.

    Flattened into one object because the split matters to the database and
    not to the screen -- but the receipt's UUID is the one the client sends
    back, since acting on a notification is always acting on *your copy* of it.
    """

    uuid = serializers.UUIDField(read_only=True)
    category = serializers.CharField(source="notification.category", read_only=True)
    source = serializers.CharField(source="notification.source", read_only=True)
    event = serializers.CharField(source="notification.event", read_only=True)
    title = serializers.CharField(source="notification.title", read_only=True)
    body = serializers.CharField(source="notification.body", read_only=True)
    link = serializers.CharField(source="notification.link", read_only=True)
    subject_type = serializers.CharField(
        source="notification.subject_type", read_only=True,
    )
    subject_uuid = serializers.UUIDField(
        source="notification.subject_uuid", read_only=True,
    )
    facility_name = serializers.CharField(
        source="notification.facility.name", read_only=True, default="",
    )
    actor_name = serializers.CharField(
        source="notification.actor_name", read_only=True,
    )
    raised_at = serializers.DateTimeField(
        source="notification.raised_at", read_only=True,
    )
    resolved_at = serializers.DateTimeField(
        source="notification.resolved_at", read_only=True,
    )
    is_open = serializers.BooleanField(source="notification.is_open", read_only=True)
    needs_action = serializers.BooleanField(
        source="notification.is_actionable", read_only=True,
    )

    class Meta:
        model = NotificationReceipt
        fields = [
            "uuid", "category", "source", "event", "title", "body", "link",
            "subject_type", "subject_uuid", "facility_name", "actor_name",
            "raised_at", "resolved_at", "is_open", "needs_action",
            "reason", "read_at", "dismissed_at", "dismissed_note",
        ]
        read_only_fields = fields


class DismissSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class PreferenceSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=NotificationCategory.choices)
    enabled = serializers.BooleanField()


class AnnouncementSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    body = serializers.CharField(max_length=1024, allow_blank=True, required=False)
    category = serializers.ChoiceField(
        choices=[
            (NotificationCategory.INFORMATION, "Information"),
            (NotificationCategory.WARNING, "Warning"),
        ],
        default=NotificationCategory.INFORMATION,
    )
    # Deliberately not offering CRITICAL. A critical notification means a
    # clinical fact needs acting on today; it is raised by the module that
    # knows that, never typed into a broadcast box.


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """The caller's own inbox. Never anybody else's."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"

    def get_queryset(self):
        """Scoped to `request.user` in the queryset itself.

        Not in a filter, not in a permission class, and not from a parameter:
        the narrowing is the first thing that happens, so no later `filter()`
        can widen it back.
        """
        return (
            NotificationReceipt.objects.filter(recipient_id=self.request.user.uuid)
            .select_related("notification", "notification__facility")
            .order_by("-delivered_at")
        )

    def list(self, request, *args, **kwargs):
        rows = inbox(
            request.user.uuid,
            unread_only=request.query_params.get("unread") == "true",
            outstanding_only=request.query_params.get("outstanding") == "true",
            category=request.query_params.get("category", ""),
            limit=int(request.query_params.get("limit", 50)),
        )
        return Response({
            "count": len(rows),
            "results": NotificationSerializer(rows, many=True).data,
        })

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """The badge. Counted, never stored."""
        return Response(summary(request.user.uuid))

    @action(detail=True, methods=["post"], url_path="read")
    def read(self, request, uuid=None):
        receipt = self.get_object()
        return Response(NotificationSerializer(mark_read(receipt)).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        """Clears the badge. Dismisses nothing -- see the service docstring."""
        return Response({"marked_read": mark_all_read(request.user.uuid)})

    @action(detail=True, methods=["post"])
    def dismiss(self, request, uuid=None):
        receipt = self.get_object()
        serializer = DismissSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = dismiss(receipt, serializer.validated_data.get("note", ""))
        return Response(NotificationSerializer(updated).data)


class PreferenceView(APIView):
    """What the caller wants to be told about, within what they may refuse."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"preferences": preferences_for(request.user.uuid)})

    def post(self, request):
        serializer = PreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_preference(
            request.user.uuid,
            serializer.validated_data["category"],
            serializer.validated_data["enabled"],
        )
        return Response({"preferences": preferences_for(request.user.uuid)})


class AnnouncementView(APIView):
    """The one way a person may raise a notification for other people.

    Gated on `notification.broadcast`, carries the sender's name, and cannot
    be critical. Everything else in the inbox arrives because something
    happened, not because somebody typed it.
    """

    permission_classes = [
        IsAuthenticated, HasPermission.of("notification.broadcast"),
    ]

    def post(self, request):
        serializer = AnnouncementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        authorization = get_authorization(request)

        recipients = [
            {"id": member_id, "name": name, "reason": "Organization announcement"}
            for member_id, name in _organization_members(request)
        ]
        notification = notify(
            source="announcements",
            event="organization_announcement",
            title=serializer.validated_data["title"],
            body=serializer.validated_data.get("body", ""),
            category=serializer.validated_data["category"],
            recipients=recipients,
            actor_name=getattr(request.user, "full_name", "") or request.user.email,
            facility=getattr(authorization, "facility", None),
        )
        if notification is None:
            return Response(
                {"sent": 0, "detail": "Nobody was available to receive this."},
                status=status.HTTP_200_OK,
            )
        return Response(
            {"sent": notification.receipts.count(), "uuid": str(notification.uuid)},
            status=status.HTTP_201_CREATED,
        )


def _organization_members(request):
    """Everybody with an active membership of the calling organization.

    Memberships live in the control-plane database and notifications in the
    tenant's, which is why the recipient is stored as a bare UUID rather than
    a foreign key -- the router cannot serve a join across the two.
    """
    from apps.identity.models import Membership, MembershipStatus

    rows = (
        Membership.objects.filter(
            organization=request.organization, status=MembershipStatus.ACTIVE,
        )
        .select_related("user")
    )
    return [
        (m.user.uuid, getattr(m.user, "full_name", "") or m.user.email)
        for m in rows
    ]
