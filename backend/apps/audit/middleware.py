"""Populates the audit context from the incoming request."""

import uuid

from django.utils.deprecation import MiddlewareMixin

from apps.audit.services import AuditContext, reset_audit_context, set_audit_context
from apps.common.http import client_ip


class AuditContextMiddleware(MiddlewareMixin):
    """Binds request-scoped audit facts, and returns the correlation id.

    Runs after tenant resolution so the facility scope is already known.
    """

    def process_request(self, request):
        user = getattr(request, "user", None)
        authenticated = user is not None and user.is_authenticated

        request_id = request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex
        request.request_id = request_id

        tenant = getattr(request, "tenant", None)

        context = AuditContext(
            request_id=request_id,
            actor_id=getattr(user, "uuid", None) if authenticated else None,
            actor_email=getattr(user, "email", "") if authenticated else "",
            is_platform_actor=(
                bool(getattr(user, "is_platform_staff", False)) if authenticated else False
            ),
            ip_address=client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            device_id=request.META.get("HTTP_X_DEVICE_ID", "")[:128],
            session_id=request.session.session_key or "" if hasattr(request, "session") else "",
            http_method=request.method,
            http_path=request.path,
            facility_code=str(tenant.facility_id) if tenant and tenant.facility_id else "",
        )
        request._audit_token = set_audit_context(context)
        return None

    def process_response(self, request, response):
        token = getattr(request, "_audit_token", None)
        if token is not None:
            reset_audit_context(token)
            request._audit_token = None
        request_id = getattr(request, "request_id", None)
        if request_id:
            response["X-Request-ID"] = request_id
        return response

    def process_exception(self, request, exception):
        token = getattr(request, "_audit_token", None)
        if token is not None:
            reset_audit_context(token)
            request._audit_token = None
        return None
