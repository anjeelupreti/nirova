"""The privacy surface: taking emergency access, and reviewing it afterwards.

Two audiences on one prefix, and they are deliberately not the same people.

**A clinician** posts to `break-glass/` when they need a record they have no
care relationship with. That endpoint gates on `patient.clinical.read` — the
ordinary clinical permission — because breaking glass is not a privilege, it is
what somebody does when the emergency does not fit the model. Requiring a
special permission to take one would mean the people most likely to need it at
three in the morning are the ones who do not have it.

**A reviewer** holds `privacy.review` and reads the queue. Everything that
looks at somebody else's override is behind that permission, including the
list, because a queue of "who opened whose record and why" is itself sensitive.

**There is no endpoint that hides a grant.** No delete, no dismiss, no bulk
sign-off. Reviewing is one grant at a time with a conclusion attached, and the
queue reports what has *not* been reviewed as prominently as what has —
otherwise the natural way to empty a queue becomes the wrong one.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission, get_authorization
from apps.patients.models import Patient
from apps.rbac.permissions import Scope
from apps.rbac.break_glass import break_glass, queue, review, revoke
from apps.rbac.models import (
    BREAK_GLASS_HOURS,
    MINIMUM_REASON_LENGTH,
    BreakGlassGrant,
    BreakGlassOutcome,
)


class GrantSerializer(serializers.ModelSerializer):
    is_live = serializers.BooleanField(read_only=True)
    is_reviewed = serializers.BooleanField(read_only=True)

    class Meta:
        model = BreakGlassGrant
        fields = [
            "uuid", "patient_uuid", "patient_label", "user_id", "user_label",
            "reason", "granted_at", "expires_at", "use_count", "last_used_at",
            "outcome", "reviewed_by_name", "reviewed_at", "review_notes",
            "is_live", "is_reviewed",
        ]
        read_only_fields = fields


class TakeSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    # Validated again in the service. Here so the client is told before the
    # round trip; there because a serializer is not where a rule lives.
    reason = serializers.CharField(min_length=MINIMUM_REASON_LENGTH, max_length=512)


class ReviewSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(
        choices=[
            (value, label) for value, label in BreakGlassOutcome.choices
            if value != BreakGlassOutcome.PENDING
        ]
    )
    notes = serializers.CharField(required=False, allow_blank=True, max_length=512)


class RevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)


class BreakGlassView(APIView):
    """Take emergency access to one record.

    Gated on the ordinary clinical permission, not on a special one. See the
    module docstring: the people most likely to need this at three in the
    morning must not be the ones who lack the permission for it.
    """

    # `Scope.OWN` as the minimum, not the default `Scope.FACILITY`. A
    # department-scoped doctor -- which is what the demo's doctor role
    # actually is -- holds clinical access more narrowly than a facility, and
    # requiring facility scope here refused them the emergency route entirely.
    # Breaking glass is not a privilege that scales with seniority; it is what
    # somebody does at three in the morning when the model does not fit, and
    # the narrowest clinician must be able to reach it.
    permission_classes = [
        IsAuthenticated,
        HasPermission.of("patient.clinical.read", scope=Scope.OWN),
    ]

    def get(self, request):
        """What the client needs to show the confirmation properly."""
        return Response({
            "hours": BREAK_GLASS_HOURS,
            "minimum_reason_characters": MINIMUM_REASON_LENGTH,
            "notice": (
                "Opening a record you are not treating is recorded against "
                "your name, and a privacy officer is told immediately. Say "
                "what the emergency is."
            ),
        })

    def post(self, request):
        serializer = TakeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient = get_object_or_404(
            Patient, uuid=serializer.validated_data["patient"]
        )
        authorization = get_authorization(request)
        grant = break_glass(
            request.user,
            patient,
            serializer.validated_data["reason"],
            facility=getattr(authorization, "facility", None),
        )
        return Response(
            GrantSerializer(grant).data, status=status.HTTP_201_CREATED,
        )


class BreakGlassReviewViewSet(viewsets.ReadOnlyModelViewSet):
    """The queue. Everything here needs `privacy.review`."""

    serializer_class = GrantSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("privacy.review")]
    lookup_field = "uuid"

    def get_queryset(self):
        queryset = BreakGlassGrant.objects.all()
        if self.request.query_params.get("pending") == "true":
            queryset = queryset.filter(outcome=BreakGlassOutcome.PENDING)
        if self.request.query_params.get("live") == "true":
            from django.utils import timezone

            queryset = queryset.filter(expires_at__gt=timezone.now())
        return queryset.order_by("-granted_at")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts, and the pending list.

        Reports pending beside the total rather than alone, because "eleven
        waiting" means one thing against twelve and another against four
        hundred.
        """
        days = int(request.query_params.get("days", 90))
        return Response(queue(days))

    @action(detail=True, methods=["post"])
    def review(self, request, uuid=None):
        grant = self.get_object()
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = review(
            grant,
            request.user,
            serializer.validated_data["outcome"],
            serializer.validated_data.get("notes", ""),
        )
        return Response(GrantSerializer(updated).data)

    @action(detail=True, methods=["post"])
    def revoke(self, request, uuid=None):
        """End a live override now, rather than waiting for it to expire."""
        grant = self.get_object()
        serializer = RevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = revoke(
            grant, request.user, serializer.validated_data["reason"],
        )
        return Response(GrantSerializer(updated).data)
