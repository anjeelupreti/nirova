"""The patient API."""

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.permissions import HasPermission, get_authorization
from apps.organization.models import Facility
from apps.patients.models import Patient, PatientStatus
from apps.patients.serializers import (
    PatientDetailSerializer,
    PatientListSerializer,
    PatientMergeSerializer,
    PatientRegistrationSerializer,
)
from apps.patients.services import (
    find_duplicate_candidates,
    merge_patients,
    record_patient_access,
    register_patient,
)
from apps.rbac.permissions import Scope


class PatientViewSet(viewsets.ModelViewSet):
    """Register, search and maintain patient records."""

    permission_classes = [IsAuthenticated, HasPermission.of("patient.read", scope=Scope.OWN)]
    lookup_field = "uuid"
    filterset_fields = ["gender", "category", "status", "district", "blood_group"]
    ordering_fields = ["registered_on", "last_name", "mrn"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action == "list":
            return PatientListSerializer
        return PatientDetailSerializer

    def get_queryset(self):
        queryset = Patient.objects.select_related("merged_into")

        # Merged records are hidden by default. They still exist and are still
        # reachable by UUID, but a clerk searching for a patient should find
        # the live record, not the shell that points at it.
        if self.action == "list" and not self.request.query_params.get(
            "include_merged"
        ):
            queryset = queryset.exclude(status=PatientStatus.MERGED)

        if self.action in {"retrieve", "update", "partial_update"}:
            queryset = queryset.prefetch_related(
                "identifiers", "allergies", "conditions"
            )
        return queryset.order_by("-registered_on")

    def retrieve(self, request, *args, **kwargs):
        """Open one patient's record, logging the access.

        Reads are logged, not only writes. "Who looked at this record?" is the
        question asked after a privacy complaint, and it cannot be answered
        retrospectively unless reads were recorded at the time.
        """
        patient = self.get_object()
        record_patient_access(patient, reason=request.query_params.get("reason", ""))
        return Response(self.get_serializer(patient).data)

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        """Find a patient by MRN, name, phone or document number.

        One box rather than a form. At a busy counter the clerk has whatever
        the patient can give them — a card, a phone number, a name — and
        should not have to decide which field it belongs in.
        """
        term = (request.query_params.get("q") or "").strip()
        if len(term) < 2:
            return Response(
                {
                    "error": {
                        "code": "search_term_too_short",
                        "message": "Enter at least two characters.",
                        "detail": {},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        matches = (
            Patient.objects.exclude(status=PatientStatus.MERGED)
            .filter(
                Q(mrn__icontains=term)
                | Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(middle_name__icontains=term)
                | Q(phone__icontains=term)
                | Q(alternate_phone__icontains=term)
                | Q(identifiers__value__iexact=term)
            )
            .distinct()
            .order_by("-registered_on")[:25]
        )
        return Response(
            {"count": len(matches), "results": PatientListSerializer(matches, many=True).data}
        )

    @action(detail=False, methods=["post"], url_path="check-duplicates")
    def check_duplicates(self, request):
        """Look for existing records before registering. Changes nothing."""
        candidates = find_duplicate_candidates(
            first_name=request.data.get("first_name", ""),
            last_name=request.data.get("last_name", ""),
            phone=request.data.get("phone", ""),
            date_of_birth=request.data.get("date_of_birth") or None,
            identifiers=request.data.get("identifiers") or [],
        )
        return Response(
            {
                "count": len(candidates),
                "candidates": [
                    {
                        "uuid": str(entry["patient"].uuid),
                        "mrn": entry["patient"].mrn,
                        "name": entry["patient"].full_name,
                        "phone": entry["patient"].phone,
                        "age": entry["patient"].age_years,
                        "district": entry["patient"].district,
                        "score": entry["score"],
                        "matched_on": entry["matched_on"],
                    }
                    for entry in candidates
                ],
            }
        )

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("patient.create", Scope.FACILITY)

        serializer = PatientRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        identifiers = data.pop("identifiers", [])
        force = data.pop("force", False)
        facility_uuid = data.pop("facility_uuid", None)

        facility = (
            Facility.objects.filter(uuid=facility_uuid).first()
            if facility_uuid
            else None
        )

        # DuplicatePatientWarning carries a 409 and the candidate list, and is
        # rendered by the standard exception handler -- the client shows the
        # matches and can retry with force=true.
        patient = register_patient(
            organization=request.organization,
            data=data,
            actor=request.user,
            facility=facility,
            identifiers=identifiers,
            force=force,
        )
        return Response(
            PatientDetailSerializer(patient).data, status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("patient.update", Scope.FACILITY)
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="merge")
    def merge(self, request, uuid=None):
        """Merge a duplicate record into this one.

        This record survives; the one named in the body is retired. The
        direction is fixed by the URL so it cannot be got backwards by a
        mistaken payload.
        """
        authorization = get_authorization(request)
        authorization.require("patient.merge", Scope.ORGANIZATION)

        surviving = self.get_object()
        serializer = PatientMergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        duplicate = Patient.objects.filter(
            uuid=serializer.validated_data["duplicate_uuid"]
        ).first()
        if duplicate is None:
            return Response(
                {
                    "error": {
                        "code": "not_found",
                        "message": "No patient matches that identifier.",
                        "detail": {},
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        merged = merge_patients(
            surviving=surviving,
            duplicate=duplicate,
            actor=request.user,
            reason=serializer.validated_data["reason"],
            matched_on=serializer.validated_data.get("matched_on"),
        )
        merged = self.get_queryset().get(pk=merged.pk)
        return Response(PatientDetailSerializer(merged).data)
