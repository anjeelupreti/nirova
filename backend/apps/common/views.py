"""Health and readiness endpoints."""

from django.db import connections
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenancy.models import TenantDatabase, TenantDatabaseStatus


class HealthView(APIView):
    """Liveness. Answers "is the process up?" and nothing more.

    Deliberately does not touch the database: a liveness probe that fails on
    a slow query gets the container killed during exactly the load spike it
    should be riding out.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok", "time": timezone.now().isoformat()})


class ReadinessView(APIView):
    """Readiness. Answers "can this process serve traffic?".

    Checks the control plane, and reports how many tenant databases are in a
    failed state -- which is a platform-operations signal, not a reason to
    take this instance out of the load balancer.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {}
        healthy = True

        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["control_plane_database"] = "ok"
        except Exception as exc:
            checks["control_plane_database"] = f"error: {exc}"
            healthy = False

        try:
            counts = {
                choice: TenantDatabase.objects.filter(status=choice).count()
                for choice, _ in TenantDatabaseStatus.choices
            }
            checks["tenant_databases"] = counts
            if counts.get(TenantDatabaseStatus.FAILED):
                checks["tenant_databases_warning"] = (
                    f"{counts[TenantDatabaseStatus.FAILED]} tenant database(s) "
                    "in a failed state."
                )
        except Exception as exc:
            checks["tenant_databases"] = f"error: {exc}"
            healthy = False

        return Response(
            {
                "status": "ready" if healthy else "degraded",
                "time": timezone.now().isoformat(),
                "checks": checks,
            },
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
