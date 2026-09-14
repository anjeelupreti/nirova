"""Report templates for narrative results: imaging, and anything written.

A radiologist reports "normal chest X-ray" many times a day, and the report
that reaches the ward was whatever was typed into one text box: sometimes
findings then a conclusion, sometimes only a conclusion, and never anything
for the patient, who is handed the sheet.

A template holds the three parts a report has -- **findings**, what was seen;
**impression**, what it means; and **advice**, a plain sentence for the
patient -- and applying one fills the entry box with them under headings, for
the reporter to change. The printed report reads those headings back as
sections. Blanks the template cannot know ("opacity in the ___ zone") stay
blanks.

A template belongs to a test (`CXR`), or to a whole modality when it names no
test. Mine and ours, as with every clinical template here; sharing needs
`catalog.manage`.
"""

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.common.exceptions import DomainError
from apps.common.permissions import HasPermission, get_authorization
from apps.diagnostics.models import ReportTemplate
from apps.rbac.permissions import Scope

#: The headings a composed report is written under, and read back by.
HEADINGS = ("FINDINGS", "IMPRESSION", "ADVICE")


class TemplateError(DomainError):
    code = "template_refused"


def visible_to(user, test_code: str = "", modality: str = "") -> QuerySet:
    """Mine and ours; for a test, its own templates and its modality's general ones."""
    queryset = ReportTemplate.objects.filter(is_active=True).filter(
        Q(owner_id__isnull=True) | Q(owner_id=getattr(user, "uuid", None)),
    )
    if test_code or modality:
        queryset = queryset.filter(
            Q(test_code=test_code) | Q(test_code="", modality__in=[modality, ""]),
        )
    return queryset.order_by("-times_used", "name")


def compose(findings: str, impression: str, advice: str = "") -> str:
    """The text the entry box is filled with, under the headings."""
    parts = []
    for heading, body in zip(HEADINGS, (findings, impression, advice)):
        if body.strip():
            parts.append(f"{heading}\n{body.strip()}")
    return "\n\n".join(parts)


def describe(template: ReportTemplate) -> dict:
    return {
        "uuid": str(template.uuid),
        "name": template.name,
        "test_code": template.test_code,
        "modality": template.modality,
        "shared": template.is_shared,
        "owner_name": template.owner_name,
        "findings": template.findings,
        "impression": template.impression,
        "advice": template.advice,
        "times_used": template.times_used,
        "text": compose(template.findings, template.impression, template.advice),
    }


@transaction.atomic
def save_template(*, user, data: dict, uuid=None, shared: bool = False,
                  may_curate: bool = False) -> ReportTemplate:
    name = str(data.get("name", "")).strip()
    if not name:
        raise TemplateError("A template needs a name.")
    findings = str(data.get("findings", "")).strip()
    impression = str(data.get("impression", "")).strip()
    if not (findings or impression):
        raise TemplateError("A report template needs findings or an impression.")
    if shared and not may_curate:
        raise TemplateError(
            "Shared templates are what every reporter here is offered. Save this "
            "as your own, or ask somebody who curates the catalogue.",
            code="not_yours_to_share",
        )

    if uuid:
        template = ReportTemplate.objects.filter(uuid=uuid).first()
        if template is None:
            raise TemplateError("That template no longer exists.", code="not_found")
        _assert_may_edit(template, user, may_curate)
    else:
        template = ReportTemplate()

    template.name = name
    template.test_code = str(data.get("test_code", "")).strip()
    template.modality = str(data.get("modality", "")).strip()
    template.findings = findings
    template.impression = impression
    template.advice = str(data.get("advice", "")).strip()
    template.owner_id = None if shared else getattr(user, "uuid", None)
    template.owner_name = "" if shared else (getattr(user, "full_name", "") or "")
    template.save()
    record(
        AuditAction.UPDATE if uuid else AuditAction.CREATE,
        entity_type="diagnostics.ReportTemplate",
        entity_id=template.uuid,
        entity_label=f"{template.name} ({'shared' if template.is_shared else 'personal'})",
    )
    return template


def _assert_may_edit(template: ReportTemplate, user, may_curate: bool) -> None:
    if template.is_shared:
        if not may_curate:
            raise TemplateError(
                "This is a shared template. Changing it changes what every "
                "reporter here is offered.",
                code="not_yours_to_edit",
            )
        return
    if template.owner_id != getattr(user, "uuid", None):
        raise TemplateError("That template no longer exists.", code="not_found")


@transaction.atomic
def apply(template: ReportTemplate) -> dict:
    ReportTemplate.objects.filter(pk=template.pk).update(
        times_used=F("times_used") + 1, last_used_at=timezone.now(),
    )
    payload = describe(template)
    payload["times_used"] += 1
    return payload


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _may_curate(request) -> bool:
    authorization = get_authorization(request)
    return bool(authorization and authorization.has("catalog.manage", Scope.FACILITY))


class ReportTemplateView(APIView):
    """`GET ?test=CXR&modality=xray` and saving one. Needs `diagnostic.process`."""

    permission_classes = [IsAuthenticated, HasPermission.of("diagnostic.process", scope=Scope.OWN)]

    def get(self, request):
        templates = visible_to(
            request.user,
            test_code=request.query_params.get("test", ""),
            modality=request.query_params.get("modality", ""),
        )
        return Response({
            "may_curate": _may_curate(request),
            "results": [describe(row) for row in templates],
        })

    def post(self, request):
        template = save_template(
            user=request.user,
            uuid=request.data.get("uuid"),
            data=request.data,
            shared=bool(request.data.get("shared")),
            may_curate=_may_curate(request),
        )
        return Response(describe(template), status=status.HTTP_201_CREATED)


class ReportTemplateDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPermission.of("diagnostic.process", scope=Scope.OWN)]

    def _get(self, request, uuid):
        return get_object_or_404(visible_to(request.user), uuid=uuid)

    def post(self, request, uuid):
        """Apply it: the composed text for the entry box. Records no result."""
        return Response(apply(self._get(request, uuid)))

    def delete(self, request, uuid):
        template = self._get(request, uuid)
        _assert_may_edit(template, request.user, _may_curate(request))
        template.is_active = False
        template.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
