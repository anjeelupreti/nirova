"""Prescription templates over HTTP.

`GET  /api/clinical/prescription-templates/`            what I may use
`POST /api/clinical/prescription-templates/`            save mine (or ours)
`POST .../<uuid>/apply/`                                the lines, counted
`DELETE .../<uuid>/`                                    retire it

Reading needs `prescription.create`: a template is a prescribing aid and
nobody else has a use for it. Sharing one, or editing a shared one, needs
`catalog.manage` — the organization's templates are its formulary, and
changing one changes what every prescriber here is offered.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from apps.common.permissions import HasPermission, get_authorization
from apps.prescriptions import templating
from apps.prescriptions.templates_models import PrescriptionTemplate
from apps.rbac.permissions import Scope


def _may_curate(request) -> bool:
    authorization = get_authorization(request)
    return bool(authorization and authorization.has("catalog.manage", Scope.FACILITY))


class PrescriptionTemplateView(APIView):
    """The list, and saving one."""

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("prescription.create", scope=Scope.OWN),
    ]

    def get(self, request):
        templates = templating.visible_to(request.user)
        if request.query_params.get("q"):
            term = request.query_params["q"].lower()
            templates = [
                row for row in templates
                if term in row.name.lower() or term in row.description.lower()
                or any(term in str(tag).lower() for tag in (row.tags or []))
            ]
        return Response({
            "may_curate": _may_curate(request),
            "results": [templating.describe(row) for row in templates],
        })

    def post(self, request):
        template = templating.save_template(
            user=request.user,
            uuid=request.data.get("uuid"),
            name=request.data.get("name", ""),
            description=request.data.get("description", ""),
            shared=bool(request.data.get("shared")),
            tags=request.data.get("tags") or [],
            patient_instructions=request.data.get("patient_instructions", ""),
            lines=request.data.get("lines") or [],
            investigations=request.data.get("investigations") or [],
            note=request.data.get("note") or {},
            may_curate=_may_curate(request),
        )
        return Response(
            templating.describe(template), status=status.HTTP_201_CREATED,
        )


class PrescriptionTemplateDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission.of("prescription.create", scope=Scope.OWN),
    ]

    def _get(self, request, uuid) -> PrescriptionTemplate:
        # Through `visible_to`, so somebody else's personal template is *not
        # found* rather than forbidden: its existence is not this prescriber's
        # business either way.
        return get_object_or_404(templating.visible_to(request.user), uuid=uuid)

    def post(self, request, uuid):
        """Apply it. Returns lines for the form; writes no prescription."""
        return Response(templating.apply(self._get(request, uuid), request.user))

    def delete(self, request, uuid):
        templating.retire(self._get(request, uuid), request.user, _may_curate(request))
        return Response(status=status.HTTP_204_NO_CONTENT)
