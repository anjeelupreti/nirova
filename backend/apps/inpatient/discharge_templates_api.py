"""Discharge templates over HTTP.

`GET  /api/ipd/discharge-templates/`              what I may use
`POST /api/ipd/discharge-templates/`              save mine (or ours)
`POST /api/ipd/discharge-templates/<uuid>/`       apply: the text, counted
`DELETE /api/ipd/discharge-templates/<uuid>/`     retire it

Reading needs `encounter.create`, the authority discharging itself asks for.
Sharing, or editing a shared template, needs `catalog.manage`.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission, get_authorization
from apps.inpatient import discharge_templating as templating
from apps.rbac.permissions import Scope


def _may_curate(request) -> bool:
    authorization = get_authorization(request)
    return bool(authorization and authorization.has("catalog.manage", Scope.FACILITY))


class DischargeTemplateView(APIView):
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.create", scope=Scope.OWN)]

    def get(self, request):
        templates = templating.visible_to(request.user).order_by("-times_used", "name")
        return Response({
            "may_curate": _may_curate(request),
            "results": [templating.describe(row) for row in templates],
        })

    def post(self, request):
        template = templating.save_template(
            user=request.user,
            uuid=request.data.get("uuid"),
            data=request.data,
            shared=bool(request.data.get("shared")),
            may_curate=_may_curate(request),
        )
        return Response(templating.describe(template), status=status.HTTP_201_CREATED)


class DischargeTemplateDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.create", scope=Scope.OWN)]

    def _get(self, request, uuid):
        return get_object_or_404(templating.visible_to(request.user), uuid=uuid)

    def post(self, request, uuid):
        """Apply it. Returns text for the form; discharges nobody."""
        return Response(templating.apply(self._get(request, uuid), request.user))

    def delete(self, request, uuid):
        templating.retire(self._get(request, uuid), request.user, _may_curate(request))
        return Response(status=status.HTTP_204_NO_CONTENT)
