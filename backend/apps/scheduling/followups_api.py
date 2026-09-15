"""The follow-up register over HTTP.

`GET  /api/clinical/follow-ups/?facility=&ahead=&behind=`  who is due, overdue,
                                                           booked or seen
`POST /api/clinical/follow-ups/recall/`                    ask one to come back

Reading is `encounter.read`: the front desk works this list all day. Sending a
recall is a write -- it puts a message on a patient's record and on their
phone -- so it takes `visit.schedule`, the authority that books them in.
"""

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission
from apps.organization.models import Facility
from apps.rbac.permissions import Scope
from apps.scheduling import followups


class FollowUpView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission.of("encounter.read", scope=Scope.OWN, write="visit.schedule"),
    ]

    def get(self, request):
        facility = None
        if request.query_params.get("facility"):
            facility = get_object_or_404(Facility, uuid=request.query_params["facility"])

        def number(name, fallback):
            try:
                return max(0, min(365, int(request.query_params.get(name, fallback))))
            except (TypeError, ValueError):
                return fallback

        return Response(followups.register(
            facility=facility,
            ahead=number("ahead", followups.AHEAD_DAYS),
            behind=number("behind", followups.BEHIND_DAYS),
        ))

    def post(self, request):
        """Recall one patient. Once per follow-up, whatever the caller does."""
        from apps.patients.models import Patient

        patient = get_object_or_404(Patient, uuid=request.data.get("patient"))
        message = followups.recall(
            patient,
            request.data.get("due_on"),
            str(request.data.get("reference", "")),
            overdue=bool(request.data.get("overdue")),
        )
        if message is None:
            return Response({"status": "already", "detail": "This patient has already been asked."})
        return Response({
            "status": message.status,
            "channel": message.channel,
            "detail": message.detail,
        })
