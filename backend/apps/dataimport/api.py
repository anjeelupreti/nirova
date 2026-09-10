"""Endpoints for the import pipeline, one per step.

**Separate endpoints rather than one "import this file" call, deliberately.**
The steps are separate because the *decisions* are separate: what the columns
mean, which duplicates are really duplicates, and whether to go ahead. A single
call would have to make all three silently, and the one thing a bulk import of
somebody's patient list must not do is decide quietly.

    POST   /api/import/batches/                 upload a file -> a batch
    GET    /api/import/batches/                 what has been imported, and when
    GET    /api/import/batches/{ref}/           one batch with its counters
    GET    /api/import/kinds/                   what can be imported, and columns
    PATCH  /api/import/batches/{ref}/mapping/   correct the column mapping
    POST   /api/import/batches/{ref}/validate/  normalise, find duplicates
    GET    /api/import/batches/{ref}/preview/   what a commit would do
    GET    /api/import/batches/{ref}/rows/      the rows, filterable by outcome
    POST   /api/import/batches/{ref}/decide/    import-or-skip each duplicate
    POST   /api/import/batches/{ref}/commit/    create the records
    GET    /api/import/batches/{ref}/errors/    a CSV to correct and re-upload
"""

from django.http import HttpResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission
from apps.dataimport import services
from apps.dataimport.kinds import REGISTRY, importer_for
from apps.dataimport.models import ImportBatch, ImportRow, RowStatus
from apps.rbac.permissions import Scope

#: Largest upload accepted, in bytes.
#:
#: 50,000 rows of patient data is roughly 10 MB, so 25 MB is generous for the
#: row limit the pipeline enforces. The point of a byte limit as well as a row
#: limit is that the byte limit can be checked before the file is parsed --
#: otherwise a 400 MB upload is read into memory to discover it is too big.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ImportRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportRow
        fields = (
            "uuid", "row_number", "status", "decision", "raw", "normalised",
            "errors", "duplicate_of_uuid", "duplicate_of_label",
            "duplicate_score", "duplicate_matched_on", "duplicate_of_row",
            "created_uuid", "created_label", "failure_reason",
        )
        read_only_fields = fields


class ImportBatchSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    is_committed = serializers.BooleanField(read_only=True)

    class Meta:
        model = ImportBatch
        fields = (
            "uuid", "reference", "kind", "kind_label", "filename", "status",
            "status_label", "headers", "column_map", "total_rows",
            "valid_rows", "invalid_rows", "duplicate_rows", "imported_rows",
            "skipped_rows", "failed_rows", "error_summary",
            "uploaded_by_name", "validated_at", "imported_at",
            "imported_by_name", "is_committed", "notes", "created_at",
        )
        read_only_fields = fields


class ImportKindsView(APIView):
    """What can be imported, with every column and its accepted spellings.

    Read with `data.import` rather than openly: the alias lists are effectively
    a description of how to shape a file that this system will accept in bulk,
    and there is no reason for somebody without the permission to need it.
    """

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("data.import", scope=Scope.ORGANIZATION),
    ]

    def get(self, request):
        return Response({
            "kinds": [
                {
                    "kind": importer.kind,
                    "label": importer.label,
                    "noun": importer.noun,
                    "notes": importer.notes,
                    "columns": [
                        {
                            "field": column.field,
                            "label": column.label,
                            "required": column.required,
                            "aliases": list(column.aliases),
                            "help_text": column.help_text,
                        }
                        for column in importer.columns
                    ],
                }
                for importer in sorted(REGISTRY.values(), key=lambda i: i.label)
            ]
        })


class ImportBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """Batches, and every step that acts on one.

    `data.import` at organization scope throughout, including the reads. A list
    of past imports says who migrated what and when, and an import that created
    eight thousand patients is not information a counter assistant needs.
    """

    serializer_class = ImportBatchSerializer
    permission_classes = [
        IsAuthenticated,
        HasPermission.of("data.import", scope=Scope.ORGANIZATION),
    ]
    lookup_field = "reference"

    def get_queryset(self):
        queryset = ImportBatch.objects.all()
        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        return queryset.order_by("-created_at")

    # -- step 1: upload -----------------------------------------------------

    def create(self, request, *args, **kwargs):
        """Upload a file and get back a batch with a suggested mapping.

        Nothing is created beyond the batch and its rows. The file is read,
        stored as rows, and a mapping is guessed -- all of which is reversible
        by deleting the batch.
        """
        kind = request.data.get("kind", "")
        upload = request.FILES.get("file")
        if not upload:
            return self._bad("Attach a file as `file`.")
        if not kind:
            return self._bad(
                "Say what this file holds as `kind`: "
                + ", ".join(sorted(REGISTRY))
            )
        try:
            importer_for(kind)
        except ValueError as error:
            return self._bad(str(error))

        if upload.size and upload.size > MAX_UPLOAD_BYTES:
            return self._bad(
                f"That file is {upload.size / 1048576:.0f} MB; the limit is "
                f"{MAX_UPLOAD_BYTES // 1048576} MB. Split it."
            )

        try:
            headers, rows = services.parse_upload(upload, upload.name)
            batch = services.create_batch(
                kind=kind, filename=upload.name, headers=headers, rows=rows,
                actor=request.user,
            )
        except services.ImportError_ as error:
            return self._bad(str(error))

        return Response(
            {
                **ImportBatchSerializer(batch).data,
                "mapping_report": services.mapping_report(
                    kind, headers, rows, batch.column_map
                ),
            },
            status=status.HTTP_201_CREATED,
        )

    # -- step 2: mapping ---------------------------------------------------

    @action(detail=True, methods=["get", "patch"], url_path="mapping")
    def mapping(self, request, reference=None):
        """Read or correct `{field: column}`.

        GET returns the report as well as the mapping -- which required fields
        are unmapped, which of the file's columns will be ignored, and three
        sample values per column. A mapping screen without the samples asks
        somebody to identify a column by its name alone, which for a header
        called "Date 2" is not possible.
        """
        batch = self.get_object()
        if request.method == "PATCH":
            try:
                batch = services.set_mapping(batch, request.data.get("mapping", {}))
            except services.ImportError_ as error:
                return self._bad(str(error))

        rows = [row.raw for row in batch.rows.all()[:50]]
        return Response({
            **ImportBatchSerializer(batch).data,
            "mapping_report": services.mapping_report(
                batch.kind, batch.headers, rows, batch.column_map
            ),
        })

    # -- step 3: validate --------------------------------------------------

    @action(detail=True, methods=["post"], url_path="validate")
    def validate_rows(self, request, reference=None):
        """Normalise every row and find the duplicates. Writes no records."""
        try:
            batch = services.validate_batch(self.get_object(), actor=request.user)
        except services.ImportError_ as error:
            return self._bad(str(error))
        return Response(services.preview_batch(batch))

    # -- step 4: review ----------------------------------------------------

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, reference=None):
        return Response(services.preview_batch(self.get_object()))

    @action(detail=True, methods=["get"], url_path="rows")
    def rows(self, request, reference=None):
        """The rows themselves, filtered by outcome.

        Paginated, because a 50,000-row batch is exactly the case this screen
        exists for and returning all of it would defeat the purpose.
        """
        batch = self.get_object()
        queryset = batch.rows.all()
        wanted = request.query_params.get("status")
        if wanted:
            if wanted not in RowStatus.values:
                return self._bad(
                    f"'{wanted}' is not a row status. One of: "
                    + ", ".join(RowStatus.values)
                )
            queryset = queryset.filter(status=wanted)

        page = self.paginate_queryset(queryset.order_by("row_number"))
        if page is not None:
            return self.get_paginated_response(
                ImportRowSerializer(page, many=True).data
            )
        return Response(ImportRowSerializer(queryset, many=True).data)

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, reference=None):
        """`{"decisions": {"4": "import", "9": "skip"}}` by row number."""
        decisions = request.data.get("decisions") or {}
        if not isinstance(decisions, dict) or not decisions:
            return self._bad(
                'Send `decisions` as {"row number": "import" or "skip"}.'
            )
        try:
            batch = services.decide_rows(self.get_object(), decisions)
        except (services.ImportError_, ValueError) as error:
            return self._bad(str(error))
        return Response(services.preview_batch(batch))

    # -- step 5: commit ----------------------------------------------------

    @action(detail=True, methods=["post"], url_path="commit")
    def commit(self, request, reference=None):
        """Create the records.

        `facility` is optional and names where these records were registered.
        Worth passing for a multi-facility group: a patient list migrated from
        the Pokhara branch should say so, because "where was this patient first
        seen" is asked constantly and is unanswerable afterwards.
        """
        batch = self.get_object()
        facility = None
        facility_uuid = request.data.get("facility")
        if facility_uuid:
            from apps.organization.models import Facility

            facility = Facility.objects.filter(uuid=facility_uuid).first()
            if facility is None:
                return self._bad("No facility with that identifier.")

        try:
            batch = services.commit_batch(
                batch,
                organization=request.organization,
                actor=request.user,
                facility=facility,
            )
        except services.ImportError_ as error:
            return self._bad(str(error))

        return Response({
            **ImportBatchSerializer(batch).data,
            "created": batch.imported_rows,
            "failed": batch.failed_rows,
            "skipped": batch.skipped_rows,
        })

    # -- step 6: the error report ------------------------------------------

    @action(detail=True, methods=["get"], url_path="errors")
    def errors(self, request, reference=None):
        """A CSV of everything that did not import, shaped to be corrected.

        The original columns first, with the file's own headers, then the row
        number and the problem. A report listing only row numbers would have to
        be read beside the original file, which for four hundred rows nobody
        does.
        """
        batch = self.get_object()
        csv_text = services.error_report_csv(batch)
        response = HttpResponse(csv_text, content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="{batch.reference}-errors.csv"'
        )
        return response

    # -- helpers -----------------------------------------------------------

    def _bad(self, message: str):
        """A refusal a person can act on.

        Every failure in this pipeline is a file somebody has to change, so the
        message is the whole response: no error codes, no field maps. The
        exception handler would wrap a dict into one sentence anyway.
        """
        return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)
