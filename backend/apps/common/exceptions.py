"""Domain exceptions and the API error envelope.

Every error the API returns has the same shape, so the frontend can render
one error component and act on `code` instead of parsing prose:

    {
      "error": {
        "code": "quota_exceeded",
        "message": "...",
        "detail": {...}
      }
    }
"""

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("nirova.errors")


class DomainError(Exception):
    """Base class for errors that are part of the product's contract."""

    code = "domain_error"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "The request could not be completed."

    def __init__(self, message=None, detail=None, code=None):
        self.message = message or self.message
        self.detail = detail or {}
        if code:
            self.code = code
        super().__init__(self.message)

    def as_payload(self):
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "detail": self.detail,
            }
        }


class TenantResolutionError(DomainError):
    code = "tenant_not_resolved"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "No organization context could be resolved for this request."


class TenantUnavailable(DomainError):
    code = "tenant_unavailable"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "This organization's database is not currently available."


class EntitlementError(DomainError):
    code = "not_entitled"
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    message = "The current subscription does not include this capability."


class QuotaExceeded(EntitlementError):
    code = "quota_exceeded"
    message = "This action would exceed a limit on the current plan."


class SubscriptionInactive(EntitlementError):
    code = "subscription_inactive"
    message = "The organization's subscription is not active."


class ApprovalRequired(DomainError):
    code = "approval_required"
    status_code = status.HTTP_202_ACCEPTED
    message = "This change has been submitted for approval."


class SegregationOfDutiesViolation(DomainError):
    code = "segregation_of_duties"
    status_code = status.HTTP_403_FORBIDDEN
    message = "The same user may not both raise and approve this record."


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    status_code = status.HTTP_403_FORBIDDEN
    message = "You do not have permission to perform this action."


def api_exception_handler(exc, context):
    """Render DomainError subclasses in the standard envelope.

    Anything DRF already understands keeps DRF's handling but is rewrapped so
    clients only ever parse one shape.
    """
    if isinstance(exc, DomainError):
        return Response(exc.as_payload(), status=exc.status_code)

    if isinstance(exc, DjangoValidationError):
        return Response(
            {
                "error": {
                    "code": "validation_error",
                    "message": "The submitted data is not valid.",
                    "detail": getattr(exc, "message_dict", {"errors": exc.messages}),
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, DjangoPermissionDenied):
        return Response(
            PermissionDeniedError().as_payload(), status=status.HTTP_403_FORBIDDEN
        )

    if isinstance(exc, Http404):
        return Response(
            {
                "error": {
                    "code": "not_found",
                    "message": "The requested resource does not exist.",
                    "detail": {},
                }
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled exception in %s", context.get("view"))
        return None

    detail = response.data
    code = "error"
    message = "The request could not be completed."
    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
        code = getattr(detail["detail"], "code", "error")
        detail = {}
    elif isinstance(detail, dict):
        message = "The submitted data is not valid."
        code = "validation_error"

    response.data = {"error": {"code": code, "message": message, "detail": detail}}
    return response
