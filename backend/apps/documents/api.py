"""Document endpoints.

**A document inherits the access of the thing it is attached to.** That is the
entire authorization model here, and it is deliberate: a file about a patient
is exactly as sensitive as that patient's record, so it is governed by the same
care relationship rather than by a second permission model that would drift out
of step with the first within a month.

In practice that means every request names a subject, the subject is resolved,
and the ordinary check for that kind of subject runs. A document endpoint that
invented its own rules would be a way around Phase 2 rather than a use of it.

**Downloads are logged, not just listings.** Opening a scan is the sensitive
act; knowing one exists is much less so, and conflating them produces an audit
log too noisy to read.
"""

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import (
    FormParser,
    JSONParser,
    MultiPartParser,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.permissions import (
    HasClinicalAccess,
    HasPermission,
    get_authorization,
    relationship_required,
)
from apps.documents.models import Document, DocumentCategory
from apps.documents.services import archive, documents_for, store
from apps.patients.models import Patient
from apps.patients.services import record_patient_access
from apps.rbac.permissions import Scope


class DocumentSerializer(serializers.ModelSerializer):
    is_archived = serializers.BooleanField(read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "uuid", "category", "title", "description",
            "subject_type", "subject_uuid",
            "original_name", "content_type", "size_bytes", "checksum",
            "uploaded_by_name", "uploaded_at",
            "archived_at", "archived_reason", "is_archived",
            "download_url",
        ]
        read_only_fields = fields

    def get_download_url(self, obj) -> str:
        # A route, not a storage path. The file lives under a checksum and the
        # client has no business knowing where; going through the endpoint is
        # what makes the download loggable and the access checkable.
        return f"/api/documents/{obj.uuid}/download/"


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    category = serializers.ChoiceField(choices=DocumentCategory.choices)
    title = serializers.CharField(max_length=255)
    subject_type = serializers.CharField(max_length=48)
    subject_uuid = serializers.UUIDField()
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=512,
    )


class ArchiveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class DocumentViewSet(viewsets.ReadOnlyModelViewSet):
    """Documents, listed and downloaded by subject."""

    serializer_class = DocumentSerializer
    permission_classes = [
        IsAuthenticated,
        HasPermission.of("patient.read", scope=Scope.OWN),
    ]
    lookup_field = "uuid"
    # JSON as well as multipart. Upload needs multipart; archive takes a JSON
    # body, and listing only multipart parsers refused it with a 415 -- an
    # error about content types on an endpoint that has nothing to do with
    # them, which is the kind of thing somebody spends an afternoon on.
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        queryset = Document.objects.all()
        params = self.request.query_params
        if params.get("subject_type") and params.get("subject"):
            queryset = queryset.filter(
                subject_type=params["subject_type"],
                subject_uuid=params["subject"],
            )
        if params.get("include_archived") != "true":
            queryset = queryset.filter(archived_at__isnull=True)
        return queryset.order_by("-uploaded_at")

    def _check_subject_access(self, request, document_or_pair):
        """Run the subject's own access check.

        The one rule this module has. For a patient document that is the care
        relationship from Phase 2; for anything else the permission already
        checked above is the whole answer, and saying so explicitly is better
        than leaving a reader to infer it from an absent branch.
        """
        if isinstance(document_or_pair, Document):
            subject_type = document_or_pair.subject_type
            subject_uuid = document_or_pair.subject_uuid
        else:
            subject_type, subject_uuid = document_or_pair

        if subject_type != "patients.Patient":
            return None

        patient = get_object_or_404(Patient, uuid=subject_uuid)
        if relationship_required(getattr(request, "facility", None)):
            checker = HasClinicalAccess()
            if not checker.has_object_permission(request, self, patient):
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied(checker.message)
        return patient

    def list(self, request, *args, **kwargs):
        params = request.query_params
        if params.get("subject_type") and params.get("subject"):
            self._check_subject_access(
                request, (params["subject_type"], params["subject"]),
            )
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        document = self.get_object()
        self._check_subject_access(request, document)
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["get"])
    def download(self, request, uuid=None):
        """The bytes, and the only place a read is logged.

        Listing a document tells you one exists; opening it is the sensitive
        act. Logging both would produce an audit trail too noisy to read, and
        the noisy one is the one that gets ignored.
        """
        document = self.get_object()
        patient = self._check_subject_access(request, document)
        if patient is not None:
            record_patient_access(
                patient, reason=f"Document: {document.title}",
            )
        return FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=document.original_name,
            content_type=document.content_type or "application/octet-stream",
        )

    def create(self, request, *args, **kwargs):
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        self._check_subject_access(
            request, (data["subject_type"], data["subject_uuid"]),
        )
        authorization = get_authorization(request)
        document = store(
            data["file"],
            category=data["category"],
            title=data["title"],
            subject_type=data["subject_type"],
            subject_uuid=data["subject_uuid"],
            description=data.get("description", ""),
            actor=request.user,
            facility=getattr(authorization, "facility", None),
        )
        return Response(
            DocumentSerializer(document).data, status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def archive(self, request, uuid=None):
        document = self.get_object()
        self._check_subject_access(request, document)
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            DocumentSerializer(
                archive(document, request.user,
                        serializer.validated_data["reason"])
            ).data
        )
