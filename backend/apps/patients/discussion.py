"""Staff talking to staff about a patient, on the record.

**Where this conversation used to happen was a phone.** "BP dropping in bed 4,
can you review" went by text message or down a corridor and left nothing: no
time, no name, nothing the next shift could read, and a patient's details on a
personal handset. Here it is kept on the patient, where the context is.

**Reading it is reading the clinical record.** The same permission and care
relationship as the rest of the clinical tier (`HasClinicalAccess`), and every
read is written to the access log. A receptionist who can see who a patient is
cannot read what the team is saying about them.

**Telling somebody is explicit.** Only colleagues added to a message are
notified, and only if they are members of this organization -- any other id is
dropped, so the discussion cannot be used to reach outside it. An urgent
message is raised as a warning. Neither is one of the categories that leave
the screen by SMS or email: a patient's name and a clinical sentence do not go
to a personal phone this way.

**Live.** A new message rings `patient.<uuid>` once it is committed, so two
people with the record open see the conversation as it happens; what crosses
the socket is only that something changed.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.patients.care_models import CareMessage

MAX_BODY = 4000
MAX_MENTIONS = 10


def _members(organization, ids=None, term: str = ""):
    """Active users of this organization, optionally by id or by name."""
    from apps.identity.models import Membership, MembershipStatus

    memberships = Membership.objects.filter(
        organization=organization, status=MembershipStatus.ACTIVE, user__is_active=True,
    ).select_related("user")
    if ids is not None:
        memberships = memberships.filter(user__uuid__in=list(ids))
    if term:
        memberships = memberships.filter(
            Q(user__full_name__icontains=term) | Q(user__email__istartswith=term),
        )
    return [membership.user for membership in memberships]


def describe(message: CareMessage, viewer_id=None) -> dict:
    return {
        "uuid": str(message.uuid),
        "author_id": str(message.author_id) if message.author_id else None,
        "author_name": message.author_name,
        "body": message.body,
        "urgent": message.urgent,
        "mentions": list(message.mentions or []),
        "created_at": message.created_at.isoformat(),
        "is_mine": bool(viewer_id) and str(message.author_id) == str(viewer_id),
    }


def post_message(patient, author, body: str, urgent: bool = False, mention_ids=(), organization=None) -> CareMessage:
    """Write one message, tell the colleagues named in it, and ring the record."""
    from apps.notifications.models import NotificationCategory
    from apps.notifications.services import notify
    from apps.realtime import publish

    body = (body or "").strip()
    if not body:
        raise ValueError("A message needs something in it.")
    if len(body) > MAX_BODY:
        raise ValueError(f"A message is at most {MAX_BODY} characters.")

    author_id = getattr(author, "uuid", None)
    wanted = {str(value) for value in (mention_ids or [])} - {str(author_id)}
    people = (
        _members(organization, ids=list(wanted)[:MAX_MENTIONS])
        if organization is not None and wanted
        else []
    )

    message = CareMessage.objects.create(
        patient=patient,
        author_id=author_id,
        author_name=getattr(author, "full_name", "") or getattr(author, "email", ""),
        body=body,
        urgent=bool(urgent),
        mentions=[{"id": str(person.uuid), "name": person.full_name} for person in people],
    )
    record(
        AuditAction.CREATE,
        entity_type="patients.CareMessage",
        entity_id=message.uuid,
        entity_label=f"Discussion about {patient.full_name} ({patient.mrn})",
        metadata={"urgent": message.urgent, "notified": len(people)},
    )

    if people:
        notify(
            source="patients",
            event="care_message",
            title=f"{message.author_name} about {patient.full_name}",
            body=body[:280],
            category=NotificationCategory.WARNING if message.urgent else NotificationCategory.INFORMATION,
            recipients=[
                {"id": person.uuid, "name": person.full_name, "reason": "Added to a discussion about this patient"}
                for person in people
            ],
            link=f"/patients/{patient.uuid}?tab=discussion",
            subject_type="patients.Patient",
            subject_uuid=patient.uuid,
            actor_name=message.author_name,
        )

    publish.ring(f"patient.{patient.uuid}")
    return message


class _MessageInput(serializers.Serializer):
    body = serializers.CharField(max_length=MAX_BODY, allow_blank=True)
    urgent = serializers.BooleanField(required=False, default=False)
    mentions = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


def discussion_response(view, request):
    """`GET` the discussion, or `POST` a message. For `PatientViewSet.discussion`."""
    from apps.patients.services import record_patient_access

    patient = view.get_object()  # object permission: HasClinicalAccess

    if request.method == "POST":
        data = _MessageInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            message = post_message(
                patient,
                request.user,
                data.validated_data["body"],
                urgent=data.validated_data["urgent"],
                mention_ids=data.validated_data["mentions"],
                organization=getattr(request, "organization", None),
            )
        except ValueError as refused:
            raise serializers.ValidationError({"body": str(refused)}) from refused
        return Response(describe(message, request.user.uuid), status=status.HTTP_201_CREATED)

    record_patient_access(patient, reason="Care discussion")
    messages = CareMessage.objects.filter(patient=patient).order_by("-created_at")[:200]
    return Response({
        "results": [describe(row, request.user.uuid) for row in reversed(list(messages))],
    })


class ColleaguesView(APIView):
    """`GET /api/clinical/colleagues/?q=` -- people who can be told about a patient.

    Names only, for somebody who already has clinical access: the smallest
    answer that lets a message reach the right person, not a staff directory.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.common.permissions import get_authorization
        from apps.rbac.permissions import Scope

        authorization = get_authorization(request)
        if authorization is None or not authorization.has("patient.clinical.read", Scope.OWN):
            return Response({"detail": "Clinical access is needed to notify colleagues."}, status=403)
        term = request.query_params.get("q", "").strip()
        if len(term) < 2:
            return Response({"results": []})
        people = [
            person for person in _members(request.organization, term=term)
            if person.uuid != request.user.uuid
        ][:8]
        return Response({"results": [{"id": str(person.uuid), "name": person.full_name} for person in people]})


__all__ = ["CareMessage", "ColleaguesView", "describe", "discussion_response", "post_message"]
_ = get_object_or_404  # kept importable for callers composing their own views
