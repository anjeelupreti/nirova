"""`GET /api/me/workspace/` — what needs this person today.

Approvals waiting on them, unread notifications, and their own day. One request,
because the point is to replace remembering to visit three screens.

**Broken sources are named, not swallowed.** Every other list in this system
degrades acceptably to empty. This one does not: an empty approval queue is a
positive claim that there is nothing to approve, and somebody with twenty-two
requisitions waiting should not be told their afternoon is free because a
source raised. A failure comes back as a named broken source and the summary
says the total is incomplete.
"""

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import get_authorization
from apps.workspace.sources import all_sources

logger = logging.getLogger("nirova.workspace")


class MyWorkspaceView(APIView):
    """One request: approvals, notifications, and the day."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # **Platform staff have no workspace in a hospital.** They are signed
        # in against the control plane with no organization bound, and every
        # source here reads a tenant database — which raised, so the vendor's
        # own console answered 500 on every page load. Nothing waiting is the
        # true answer, not an error.
        if getattr(request, "tenant", None) is None:
            return Response({
                "waiting": [], "approvals_total": 0,
                "is_complete": True, "broken_sources": [],
                "notifications": None, "today": None,
                "note": "You are signed in to the platform, not to a hospital.",
            })

        authorization = get_authorization(request)
        waiting, broken = [], []

        for source in all_sources():
            # Permission to *act*, not to look. A work queue listing things
            # somebody can only read teaches them the queue is not theirs.
            if not (authorization
                    and authorization.has(source.permission, source.scope)):
                continue
            try:
                items = source.find(request)
            except Exception:                                  # noqa: BLE001
                # Logged loudly and reported, never dropped. See the module
                # docstring: silence here is a false "nothing to do".
                logger.exception("workspace source %s failed", source.code)
                broken.append({"type": source.code, "label": source.label})
                continue
            if items:
                waiting.append({
                    "type": source.code,
                    "label": source.label,
                    "screen": source.screen,
                    "urgency": source.urgency,
                    "count": len(items),
                    "items": items,
                })

        total = sum(group["count"] for group in waiting)
        return Response({
            "approvals": waiting,
            "approvals_total": total,
            # Said plainly rather than left to be inferred from a `broken` key
            # somebody's front end forgot to render.
            "is_complete": not broken,
            "broken_sources": broken,
            "notifications": self._notifications(request),
            "today": self._today(request),
        })

    def _notifications(self, request):
        """Unread count and the most recent few.

        Read through the notification centre rather than queried here, so this
        screen cannot disagree with the bell in the header about how many
        unread there are.
        """
        try:
            from apps.notifications.services import summary

            return summary(getattr(request.user, "uuid", None))
        except Exception:                                      # noqa: BLE001
            logger.exception("workspace could not read notifications")
            # `None`, not `0`. Zero unread is a claim; not knowing is not the
            # same claim, and a badge showing nothing because the query failed
            # is the same lie as an empty approval queue.
            return {"unread": None, "unavailable": True}

    def _today(self, request):
        """This person's own day: their clinics, their shifts.

        Deliberately thin. Every worklist that exists already has a screen that
        does it better, and a summary that tries to be those screens is a
        summary that goes stale against them.
        """
        from apps.hr.models import Employee

        employee = Employee.for_user(getattr(request.user, "uuid", None))
        if employee is None:
            # Not an error. A platform operator or an organization owner with
            # no employee record has no shift, and saying so is more useful
            # than an empty list that looks like a quiet day.
            return {"has_employee_record": False}

        return {
            "has_employee_record": True,
            "employee": employee.full_name,
            "facility": (
                employee.facility.name if employee.facility_id else None
            ),
            "department": (
                employee.department.name if employee.department_id else None
            ),
        }
