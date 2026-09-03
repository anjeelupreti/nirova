"""Blood bank endpoints.

`encounter.read` sees the shelf and the donor registry. Collecting, grouping,
screening and releasing need `pharmacy.dispense` — the laboratory-side
permission a blood bank technician holds. Issuing needs it too.

Three things this API deliberately does not offer.

**No endpoint issues a unit with an override.** `issue_unit` refuses and there
is no flag to make it stop. The emergency path is its own endpoint with its own
name, its own required authoriser and its own audit entry, so that no request
body can turn an ordinary issue into an uncross-matched one.

**No endpoint edits a grouping or a screening result.** Both are re-recorded by
a second person; the first result stays. A correctable result is not a check.

**No endpoint deletes a unit.** A unit that must not be used is discarded with
a reason, because wastage by reason is the number a blood bank manages.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bloodbank.models import (
    REACTION_TYPES,
    SCREENING_PANEL,
    BloodRequest,
    BloodUnit,
    ComponentType,
    CrossMatch,
    Donation,
    Donor,
    Screening,
    Transfusion,
    TransfusionReaction,
)
from apps.bloodbank.services import (
    collect_donation,
    compatible_units,
    confirmed_group,
    cross_match,
    defer_donor,
    discard_unit,
    donor_call_list,
    expire_units,
    finish_transfusion,
    haemovigilance,
    issue_blockers,
    issue_emergency,
    issue_unit,
    look_back,
    record_grouping,
    record_observation,
    record_screening,
    register_donor,
    release_blockers,
    release_units,
    report_reaction,
    request_blood,
    reserve_unit,
    release_reservation,
    return_unit,
    separate_components,
    stock,
    trace_patient,
    transfuse,
    verify_screening,
    wastage,
)
# as_date: a query parameter is always a string, and a service that does
# arithmetic on one raises rather than filtering. Parsed at the boundary.
from apps.common.dates import as_date
from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.encounters.models import Encounter
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class DonorSerializer(serializers.ModelSerializer):
    eligible_now = serializers.SerializerMethodField()
    problems = serializers.SerializerMethodField()

    class Meta:
        model = Donor
        fields = [
            "uuid", "donor_number", "full_name", "full_name_nepali",
            "date_of_birth", "gender", "blood_group", "phone",
            "alternate_phone", "email", "address", "citizenship_number",
            "donor_type", "status", "deferral_reason", "deferred_until",
            "deferred_by_name", "donation_count", "last_donated_on",
            "is_contactable", "notes", "eligible_now", "problems",
        ]
        read_only_fields = [
            "uuid", "donor_number", "status", "deferral_reason",
            "deferred_until", "deferred_by_name", "donation_count",
            "last_donated_on", "eligible_now", "problems",
        ]

    def _eligibility(self, obj):
        if not hasattr(obj, "_cached_eligibility"):
            obj._cached_eligibility = obj.eligible_on()
        return obj._cached_eligibility

    def get_eligible_now(self, obj) -> bool:
        return self._eligibility(obj)[0]

    def get_problems(self, obj) -> list:
        return self._eligibility(obj)[1]


class GroupingSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(read_only=True)
    blood_group = serializers.CharField()
    forward_result = serializers.CharField()
    reverse_result = serializers.CharField()
    is_weak_d = serializers.BooleanField()
    antibody_screen = serializers.CharField()
    performed_at = serializers.DateTimeField()
    performed_by_name = serializers.CharField()
    method = serializers.CharField()


class ScreeningSerializer(serializers.ModelSerializer):
    untested = serializers.ListField(read_only=True)
    reactive = serializers.ListField(read_only=True)
    is_complete = serializers.BooleanField(read_only=True)
    is_safe = serializers.BooleanField(read_only=True)

    class Meta:
        model = Screening
        fields = [
            "uuid", "results", "values", "performed_at", "performed_by_name",
            "verified_by_name", "verified_at", "kit_lot_number", "notes",
            "untested", "reactive", "is_complete", "is_safe",
        ]
        read_only_fields = fields


class DonationSerializer(serializers.ModelSerializer):
    donor_name = serializers.CharField(source="donor.full_name", read_only=True)
    donor_number = serializers.CharField(
        source="donor.donor_number", read_only=True,
    )
    groupings = GroupingSerializer(many=True, read_only=True)
    screening = ScreeningSerializer(read_only=True)
    group = serializers.SerializerMethodField()
    blockers = serializers.SerializerMethodField()
    units = serializers.SerializerMethodField()

    class Meta:
        model = Donation
        fields = [
            "uuid", "donation_number", "donor_name", "donor_number",
            "collected_at", "collected_by_name", "collection_site",
            "is_mobile_drive", "volume_ml", "bag_type", "haemoglobin",
            "donor_weight_kg", "had_adverse_event", "adverse_event_detail",
            "status", "discard_reason", "notes", "groupings", "screening",
            "group", "blockers", "units",
        ]
        read_only_fields = fields

    def get_group(self, obj) -> str:
        return confirmed_group(obj)[0]

    def get_blockers(self, obj) -> list:
        return release_blockers(obj)

    def get_units(self, obj) -> list:
        return [
            {
                "uuid": str(unit.uuid),
                "unit_number": unit.unit_number,
                "component": unit.component,
                "status": unit.status,
                "expires_on": unit.expires_on,
            }
            for unit in obj.units.all()
        ]


class UnitSerializer(serializers.ModelSerializer):
    donation_number = serializers.CharField(
        source="donation.donation_number", read_only=True,
    )
    reserved_for = UUIDRelatedField(read_only=True)
    reserved_for_name = serializers.CharField(
        source="reserved_for.full_name", read_only=True, default="",
    )
    days_to_expiry = serializers.IntegerField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = BloodUnit
        fields = [
            "uuid", "unit_number", "donation_number", "component",
            "blood_group", "volume_ml", "prepared_at", "expires_on",
            "days_to_expiry", "is_expired", "storage_location",
            "storage_min_c", "storage_max_c", "status", "reserved_for", "reserved_for_name",
            "reserved_until", "reserved_reason", "issued_at",
            "issued_to_name", "left_storage_at", "returned_at",
            "discard_reason", "notes",
        ]
        read_only_fields = fields


class CrossMatchSerializer(serializers.ModelSerializer):
    unit_number = serializers.CharField(source="unit.unit_number", read_only=True)
    unit_group = serializers.CharField(source="unit.blood_group", read_only=True)
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = CrossMatch
        fields = [
            "uuid", "unit_number", "unit_group", "patient_name",
            "performed_at", "performed_by_name", "valid_until", "result",
            "method", "patient_group", "antibody_screen",
            "incompatibility_detail", "notes", "is_valid",
        ]
        read_only_fields = fields


class RequestSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    units_given = serializers.SerializerMethodField()

    class Meta:
        model = BloodRequest
        fields = [
            "uuid", "reference", "patient_name", "patient_mrn",
            "requested_at", "requested_by_name", "required_by", "urgency",
            "component", "units_requested", "units_given", "indication",
            "stated_group", "haemoglobin", "status", "cancelled_reason",
            "notes",
        ]
        read_only_fields = fields

    def get_units_given(self, obj) -> int:
        return obj.transfusions.count()


class ReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransfusionReaction
        fields = [
            "uuid", "reported_at", "reported_by_name",
            "minutes_into_transfusion", "reaction_type", "severity",
            "symptoms", "transfusion_stopped", "volume_transfused_ml",
            "treatment_given", "unit_returned_to_bank",
            "repeat_grouping_done", "repeat_crossmatch_done", "culture_sent",
            "investigation_findings", "is_clerical_error",
            "reported_to_authority", "reported_to_authority_at", "notes",
        ]
        read_only_fields = fields


class TransfusionSerializer(serializers.ModelSerializer):
    unit_number = serializers.CharField(source="unit.unit_number", read_only=True)
    unit_group = serializers.CharField(source="unit.blood_group", read_only=True)
    component = serializers.CharField(source="unit.component", read_only=True)
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    reactions = ReactionSerializer(many=True, read_only=True)

    class Meta:
        model = Transfusion
        fields = [
            "uuid", "unit_number", "unit_group", "component", "patient_name",
            "started_at", "finished_at", "volume_given_ml", "outcome",
            "checked_by_first", "checked_by_second", "identity_confirmed",
            "observations", "notes", "reactions",
        ]
        read_only_fields = fields


# -- inputs -----------------------------------------------------------------


class CollectSerializer(serializers.Serializer):
    facility = serializers.UUIDField()
    volume_ml = serializers.IntegerField(required=False, default=450)
    haemoglobin = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
    )
    donor_weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True,
    )
    collection_site = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )
    is_mobile_drive = serializers.BooleanField(required=False, default=False)


class DeferSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)
    until = serializers.DateField(required=False, allow_null=True)
    permanent = serializers.BooleanField(required=False, default=False)


class GroupingInputSerializer(serializers.Serializer):
    blood_group = serializers.CharField(max_length=3)
    forward = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )
    reverse = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )
    is_weak_d = serializers.BooleanField(required=False, default=False)
    antibody_screen = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )
    method = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )


class ScreeningInputSerializer(serializers.Serializer):
    results = serializers.DictField()
    values = serializers.DictField(required=False, default=dict)
    kit_lot_number = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )


class SeparateSerializer(serializers.Serializer):
    components = serializers.ListField(
        child=serializers.DictField(),
        help_text="[{component, volume_ml}]",
    )


class RequestInputSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    facility = serializers.UUIDField()
    encounter = serializers.UUIDField(required=False, allow_null=True)
    component = serializers.CharField(max_length=16)
    units = serializers.IntegerField(min_value=1)
    indication = serializers.CharField(max_length=512)
    urgency = serializers.CharField(max_length=12, required=False, default="routine")
    stated_group = serializers.CharField(
        max_length=3, required=False, allow_blank=True, default="",
    )
    haemoglobin = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
    )


class CrossMatchInputSerializer(serializers.Serializer):
    unit = serializers.UUIDField()
    patient = serializers.UUIDField()
    patient_group = serializers.CharField(max_length=3)
    request = serializers.UUIDField(required=False, allow_null=True)
    result = serializers.CharField(max_length=16, required=False, default="compatible")
    method = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )
    antibody_screen = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default="",
    )
    incompatibility_detail = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class IssueSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    issued_to = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )


class EmergencyIssueSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    #: Both required. This is a risk the hospital accepts, not a step waived.
    authorised_by = serializers.CharField(max_length=255)
    reason = serializers.CharField(max_length=512)


class ReserveSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )
    until = serializers.DateTimeField(required=False, allow_null=True)


class TransfuseSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    checked_by_first = serializers.CharField(max_length=255)
    checked_by_second = serializers.CharField(max_length=255)
    encounter = serializers.UUIDField(required=False, allow_null=True)
    request = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, data):
        # Checked here as well as in the service and the database, so the
        # message arrives before anything is written. Three layers because
        # this is the last barrier before a fatal error.
        if data["checked_by_first"].strip() == data["checked_by_second"].strip():
            raise serializers.ValidationError(
                "The bedside check needs two different people. One person "
                "checking alone is not the check."
            )
        return data


class ReactionInputSerializer(serializers.Serializer):
    reaction_type = serializers.CharField(max_length=24)
    severity = serializers.CharField(max_length=20)
    symptoms = serializers.CharField(max_length=4000)
    minutes_in = serializers.IntegerField(required=False, allow_null=True)
    stopped = serializers.BooleanField(required=False, default=True)
    volume_ml = serializers.IntegerField(required=False, allow_null=True)
    treatment = serializers.CharField(
        max_length=4000, required=False, allow_blank=True, default="",
    )


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class DonorViewSet(viewsets.ModelViewSet):
    serializer_class = DonorSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "donor_number"
    filterset_class = uuid_filterset(
        Donor, fields=["blood_group", "status", "donor_type", "is_contactable"],
    )

    def get_queryset(self):
        return Donor.objects.order_by("full_name")

    def create(self, request, *args, **kwargs):
        get_authorization(request).require("pharmacy.dispense", Scope.FACILITY)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donor = register_donor(
            request.organization, request.user, **serializer.validated_data,
        )
        return Response(
            DonorSerializer(donor).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="defer")
    def defer(self, request, donor_number=None):
        get_authorization(request).require("pharmacy.dispense", Scope.FACILITY)
        serializer = DeferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(DonorSerializer(defer_donor(
            self.get_object(), data["reason"], actor=request.user,
            until=data.get("until"), permanent=data["permanent"],
        )).data)

    @action(detail=True, methods=["post"], url_path="collect")
    def collect(self, request, donor_number=None):
        get_authorization(request).require("pharmacy.dispense", Scope.FACILITY)
        serializer = CollectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        donation = collect_donation(
            request.organization,
            self.get_object(),
            get_object_or_404(Facility, uuid=data["facility"]),
            actor=request.user,
            volume_ml=data.get("volume_ml", 450),
            haemoglobin=data.get("haemoglobin"),
            donor_weight_kg=data.get("donor_weight_kg"),
            collection_site=data.get("collection_site", ""),
            is_mobile_drive=data.get("is_mobile_drive", False),
        )
        return Response(
            DonationSerializer(donation).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"], url_path="look-back")
    def lookback(self, request, donor_number=None):
        """Every patient who received this donor's blood."""
        return Response(look_back(self.get_object()))

    @action(detail=False, methods=["get"], url_path="call-list")
    def call_list(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility"),
        )
        return Response(donor_call_list(
            facility, request.query_params.get("group", "O-"),
            limit=int(request.query_params.get("limit", 50)),
        ))


class DonationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DonationSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "donation_number"
    filterset_class = uuid_filterset(
        Donation, relations=["donor", "facility"], fields=["status"],
    )

    def get_queryset(self):
        return (
            Donation.objects.select_related("donor", "screening")
            .prefetch_related("groupings", "units")
        )

    def _writable(self):
        get_authorization(self.request).require(
            "pharmacy.dispense", Scope.FACILITY
        )

    @action(detail=True, methods=["post"], url_path="grouping")
    def grouping(self, request, donation_number=None):
        """One person's determination. Two are needed, by two people."""
        self._writable()
        serializer = GroupingInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record_grouping(
            self.get_object(), actor=request.user, **serializer.validated_data,
        )
        return Response(DonationSerializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="screening")
    def screening(self, request, donation_number=None):
        self._writable()
        serializer = ScreeningInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        record_screening(
            self.get_object(), data["results"], actor=request.user,
            values=data.get("values"),
            kit_lot_number=data.get("kit_lot_number", ""),
        )
        return Response(DonationSerializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="verify-screening")
    def verify(self, request, donation_number=None):
        self._writable()
        donation = self.get_object()
        verify_screening(donation.screening, actor=request.user)
        return Response(DonationSerializer(donation).data)

    @action(detail=True, methods=["post"], url_path="separate")
    def separate(self, request, donation_number=None):
        self._writable()
        serializer = SeparateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        made = separate_components(
            self.get_object(),
            [
                (row["component"], int(row["volume_ml"]))
                for row in serializer.validated_data["components"]
            ],
            actor=request.user,
        )
        return Response(
            UnitSerializer(made, many=True).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request, donation_number=None):
        """The one gate between a bag of blood and a patient."""
        self._writable()
        released = release_units(self.get_object(), actor=request.user)
        return Response(UnitSerializer(released, many=True).data)

    @action(detail=False, methods=["get"], url_path="panel")
    def panel(self, request):
        """The screening panel, served rather than hard-coded in the client."""
        return Response([
            {"key": key, "label": label, "permanent_deferral": permanent}
            for key, label, permanent in SCREENING_PANEL
        ])


class UnitViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "unit_number"
    filterset_class = uuid_filterset(
        BloodUnit, relations=["facility", "donation"],
        fields=["component", "blood_group", "status"],
    )

    def get_queryset(self):
        return BloodUnit.objects.select_related("donation", "reserved_for")

    def _writable(self):
        get_authorization(self.request).require(
            "pharmacy.dispense", Scope.FACILITY
        )

    @action(detail=True, methods=["get"], url_path="blockers")
    def blockers(self, request, unit_number=None):
        patient = get_object_or_404(
            Patient, uuid=request.query_params.get("patient"),
        )
        return Response(issue_blockers(self.get_object(), patient))

    @action(detail=True, methods=["post"], url_path="reserve")
    def reserve(self, request, unit_number=None):
        self._writable()
        serializer = ReserveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(UnitSerializer(reserve_unit(
            self.get_object(),
            get_object_or_404(Patient, uuid=data["patient"]),
            actor=request.user,
            reason=data.get("reason", ""),
            until=data.get("until"),
        )).data)

    @action(detail=True, methods=["post"], url_path="unreserve")
    def unreserve(self, request, unit_number=None):
        self._writable()
        return Response(UnitSerializer(release_reservation(
            self.get_object(), actor=request.user,
            reason=request.data.get("reason", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="issue")
    def issue(self, request, unit_number=None):
        """Hand a unit over. Refuses; there is no override."""
        self._writable()
        serializer = IssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(UnitSerializer(issue_unit(
            self.get_object(),
            get_object_or_404(Patient, uuid=serializer.validated_data["patient"]),
            actor=request.user,
            issued_to=serializer.validated_data.get("issued_to", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="issue-emergency")
    def issue_uncrossmatched(self, request, unit_number=None):
        """Blood without a cross-match. Its own endpoint, on purpose.

        Separate so that no request body to the ordinary issue can turn it
        into this one.
        """
        get_authorization(request).require("pharmacy.dispense", Scope.FACILITY)
        serializer = EmergencyIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(UnitSerializer(issue_emergency(
            self.get_object(),
            get_object_or_404(Patient, uuid=data["patient"]),
            actor=request.user,
            authorised_by=data["authorised_by"],
            reason=data["reason"],
        )).data)

    @action(detail=True, methods=["post"], url_path="return")
    def take_back(self, request, unit_number=None):
        """Take an issued unit back, if the cold chain held."""
        self._writable()
        return Response(UnitSerializer(return_unit(
            self.get_object(), actor=request.user,
            reason=request.data.get("reason", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="discard")
    def discard(self, request, unit_number=None):
        self._writable()
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(UnitSerializer(discard_unit(
            self.get_object(), serializer.validated_data["reason"],
            actor=request.user,
        )).data)

    @action(detail=True, methods=["post"], url_path="transfuse")
    def start_transfusion(self, request, unit_number=None):
        self._writable()
        serializer = TransfuseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transfusion = transfuse(
            self.get_object(),
            get_object_or_404(Patient, uuid=data["patient"]),
            actor=request.user,
            checked_by_first=data["checked_by_first"],
            checked_by_second=data["checked_by_second"],
            encounter=(
                get_object_or_404(Encounter, uuid=data["encounter"])
                if data.get("encounter") else None
            ),
            request=(
                get_object_or_404(BloodRequest, uuid=data["request"])
                if data.get("request") else None
            ),
        )
        return Response(
            TransfusionSerializer(transfusion).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="compatible")
    def compatible(self, request):
        """What is on the shelf that this patient could receive."""
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility"),
        )
        return Response(UnitSerializer(compatible_units(
            facility,
            request.query_params.get("component", ComponentType.RED_CELLS),
            request.query_params.get("group", "O+"),
            on_date=as_date(request.query_params.get("on_date"), "on_date"),
        ), many=True).data)


class BloodRequestViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RequestSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        BloodRequest, relations=["patient", "facility"],
        fields=["status", "urgency", "component"],
    )

    def get_queryset(self):
        return BloodRequest.objects.select_related("patient")

    @action(detail=False, methods=["post"], url_path="create")
    def raise_request(self, request):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = RequestInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        made = request_blood(
            request.organization,
            get_object_or_404(Patient, uuid=data["patient"]),
            get_object_or_404(Facility, uuid=data["facility"]),
            component=data["component"],
            units=data["units"],
            indication=data["indication"],
            actor=request.user,
            urgency=data.get("urgency", "routine"),
            encounter=(
                get_object_or_404(Encounter, uuid=data["encounter"])
                if data.get("encounter") else None
            ),
            stated_group=data.get("stated_group", ""),
            haemoglobin=data.get("haemoglobin"),
        )
        return Response(
            RequestSerializer(made).data, status=status.HTTP_201_CREATED
        )


class CrossMatchView(APIView):
    """Test one unit against one patient."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def post(self, request):
        get_authorization(request).require("pharmacy.dispense", Scope.FACILITY)
        serializer = CrossMatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        match = cross_match(
            get_object_or_404(BloodUnit, uuid=data["unit"]),
            get_object_or_404(Patient, uuid=data["patient"]),
            patient_group=data["patient_group"],
            actor=request.user,
            request=(
                get_object_or_404(BloodRequest, uuid=data["request"])
                if data.get("request") else None
            ),
            result=data.get("result", "compatible"),
            method=data.get("method", ""),
            antibody_screen=data.get("antibody_screen", ""),
            incompatibility_detail=data.get("incompatibility_detail", ""),
        )
        return Response(
            CrossMatchSerializer(match).data, status=status.HTTP_201_CREATED
        )


class TransfusionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TransfusionSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Transfusion, relations=["patient"], fields=["outcome"],
    )

    def get_queryset(self):
        return (
            Transfusion.objects.select_related("unit", "patient")
            .prefetch_related("reactions")
        )

    @action(detail=True, methods=["post"], url_path="observation")
    def observation(self, request, uuid=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        return Response(TransfusionSerializer(record_observation(
            self.get_object(), request.user, **request.data,
        )).data)

    @action(detail=True, methods=["post"], url_path="finish")
    def finish(self, request, uuid=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        return Response(TransfusionSerializer(finish_transfusion(
            self.get_object(), actor=request.user,
            volume_ml=request.data.get("volume_ml"),
            outcome=request.data.get("outcome", "completed"),
        )).data)

    @action(detail=True, methods=["post"], url_path="reaction")
    def reaction(self, request, uuid=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = ReactionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        report_reaction(
            self.get_object(),
            data["reaction_type"], data["severity"], data["symptoms"],
            actor=request.user,
            minutes_in=data.get("minutes_in"),
            stopped=data.get("stopped", True),
            volume_ml=data.get("volume_ml"),
            treatment=data.get("treatment", ""),
        )
        return Response(TransfusionSerializer(self.get_object()).data)

    @action(detail=False, methods=["get"], url_path="reaction-types")
    def reaction_types(self, request):
        """The reportable categories, served rather than hard-coded."""
        return Response([
            {"key": key, "label": label} for key, label in REACTION_TYPES
        ])


class BloodBankReportView(APIView):
    """Stock, wastage, haemovigilance and patient traceability."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def get(self, request):
        which = request.query_params.get("report", "stock")
        facility = (
            get_object_or_404(Facility, uuid=request.query_params["facility"])
            if request.query_params.get("facility") else None
        )
        since = as_date(request.query_params.get("since"), "since")

        if which == "stock":
            if facility is None:
                return Response(
                    {"detail": "A facility is required for the stock report."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(stock(facility))
        if which == "wastage":
            return Response(wastage(facility=facility, since=since))
        if which == "haemovigilance":
            return Response(haemovigilance(facility=facility, since=since))
        if which == "patient":
            return Response(trace_patient(get_object_or_404(
                Patient, uuid=request.query_params.get("patient"),
            )))

        return Response(
            {"detail": f"Unknown report '{which}'.",
             "available": ["stock", "wastage", "haemovigilance", "patient"]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def post(self, request):
        """Run the expiry sweep. Idempotent; safe to run repeatedly."""
        get_authorization(request).require("pharmacy.dispense", Scope.FACILITY)
        facility = (
            get_object_or_404(Facility, uuid=request.data["facility"])
            if request.data.get("facility") else None
        )
        return Response(expire_units(facility=facility))
