"""Code search, for anybody who may write a clinical record."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission
from apps.rbac.permissions import Scope
from apps.terminology import services


class DiagnosisCodeView(APIView):
    """`GET /api/clinical/diagnosis-codes/?q=` -- codes, best match first.

    `patient.clinical.read` at `own`: a clinician coding their own note is
    the only caller, and the vocabulary itself is not confidential.
    """

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("patient.clinical.read", scope=Scope.OWN),
    ]

    def get(self, request):
        term = request.query_params.get("q", "")
        codes = services.search(term)
        return Response({
            "results": [services.describe(code) for code in codes],
            "vocabulary": services.vocabulary_exists(),
        })
