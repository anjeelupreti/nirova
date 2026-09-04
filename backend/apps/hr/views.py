"""People endpoints.

Two access rules run through everything here.

**Salary is behind its own permission.** `employee.read` gets you the
directory; `salary.read` gets you what somebody earns. They are different
questions and a great many people need the first and none of the second.

**Everyone can see their own record.** `/api/hr/employees/me/` resolves the
caller's own employee row without `employee.read`, because a nurse checking
their own joining date should not need permission to view the whole
workforce.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.filters import uuid_filterset
from apps.common.permissions import (
    HasPermission,
    apply_scope_filter,
    get_authorization,
)
from apps.hr.models import (
    Credential,
    Employee,
    EmployeeDocument,
    EmploymentContract,
    Experience,
    Position,
    Skill,
)
from apps.hr.serializers import (
    CredentialSerializer,
    EmployeeDetailSerializer,
    EmployeeDocumentSerializer,
    EmployeeListSerializer,
    EmploymentContractSerializer,
    EmploymentEventSerializer,
    ExperienceSerializer,
    HireSerializer,
    IssueContractSerializer,
    PositionSerializer,
    SeparateSerializer,
    SkillSerializer,
    SuspendSerializer,
    TransferSerializer,
    VerifyCredentialSerializer,
)
from apps.hr.services import (
    confirm,
    current_contract,
    expiring_contracts,
    expiring_credentials,
    headcount,
    hire,
    issue_contract,
    practice_blockers,
    reinstate,
    separate,
    separations,
    suspend,
    team_of,
    transfer,
    verify_credential,
)
from apps.organization.models import Department, Facility
from apps.rbac.permissions import Scope


class PositionViewSet(viewsets.ModelViewSet):
    """The org chart's jobs, whether or not anyone holds them."""

    serializer_class = PositionSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("employee.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Position, relations=["facility", "department"],
        fields=["is_active", "is_clinical", "is_provider"],
    )
    search_fields = ["code", "title", "grade"]
    ordering_fields = ["title", "code"]

    def get_queryset(self):
        queryset = Position.objects.select_related("facility", "department")
        if self.request.query_params.get("vacant") == "true":
            # `vacancies` counts employees per position, so the decision is
            # made in Python -- the set is small, tens of positions rather
            # than thousands. The result is narrowed back to a queryset
            # because DRF's filter backend and paginator both reach for
            # `.model` on whatever this returns.
            vacant = [
                position.pk for position in queryset if position.vacancies > 0
            ]
            return queryset.filter(pk__in=vacant).order_by("title")
        return queryset.order_by("title")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "position.manage", Scope.ORGANIZATION
        )
        serializer.save(created_by_id=self.request.user.uuid)

    def perform_update(self, serializer):
        get_authorization(self.request).require(
            "position.manage", Scope.ORGANIZATION
        )
        serializer.save()


class EmployeeViewSet(viewsets.ModelViewSet):
    """The workforce."""

    permission_classes = [IsAuthenticated, HasPermission.of("employee.read", Scope.OWN)]
    lookup_field = "employee_code"
    filterset_class = uuid_filterset(
        Employee, relations=["facility", "department", "position"],
        fields=["status", "employment_type"],
    )
    search_fields = [
        "employee_code", "first_name", "last_name", "phone", "work_email",
    ]
    ordering_fields = ["joined_on", "last_name", "employee_code"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action in {"list"}:
            return EmployeeListSerializer
        return EmployeeDetailSerializer

    def get_queryset(self):
        queryset = Employee.objects.select_related(
            "facility", "department", "position", "reports_to"
        )
        if self.action != "list":
            queryset = queryset.prefetch_related(
                "credentials", "experience", "skills", "documents"
            )
        # Directory default: people who work here. Leavers are still in the
        # record -- everything they did points at them -- but a colleague
        # looking someone up means a current colleague.
        if self.request.query_params.get("include_separated") != "true":
            queryset = queryset.exclude(status="separated")

        # Scope filter: callers with only Scope.OWN see only their own row.
        queryset = apply_scope_filter(
            queryset, self.request, "employee.read", employee_attr="self"
        )
        return queryset.order_by("first_name", "last_name")

    # -- self ---------------------------------------------------------------

    @action(
        detail=False, methods=["get"], url_path="me",
        permission_classes=[IsAuthenticated],
    )
    def me(self, request):
        """The caller's own record.

        Outside `employee.read` on purpose: checking your own joining date
        should not require permission to view the whole workforce. Returns
        204 when the caller has no employee record — a platform administrator
        legitimately has none, and that is not an error.
        """
        employee = Employee.for_user(request.user.uuid)
        if employee is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(EmployeeDetailSerializer(employee).data)

    # -- lifecycle ----------------------------------------------------------

    def create(self, request, *args, **kwargs):
        get_authorization(request).require("employee.hire", Scope.FACILITY)

        serializer = HireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        employee = hire(
            facility=get_object_or_404(Facility, uuid=data["facility"]),
            first_name=data["first_name"],
            last_name=data["last_name"],
            actor=request.user,
            position=(
                get_object_or_404(Position, uuid=data["position"])
                if data.get("position") else None
            ),
            department=(
                get_object_or_404(Department, uuid=data["department"])
                if data.get("department") else None
            ),
            reports_to=(
                get_object_or_404(Employee, uuid=data["reports_to"])
                if data.get("reports_to") else None
            ),
            employment_type=data.get("employment_type") or None,
            joined_on=data.get("joined_on"),
            probation_days=data.get("probation_days", 0),
            employee_code=data.get("employee_code") or None,
            user_id=data.get("user_id"),
            middle_name=data.get("middle_name", ""),
            phone=data.get("phone", ""),
            personal_email=data.get("personal_email", ""),
            work_email=data.get("work_email", ""),
            date_of_birth=data.get("date_of_birth"),
            gender=data.get("gender", ""),
            citizenship_number=data.get("citizenship_number", ""),
        )
        return Response(
            EmployeeDetailSerializer(employee).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_update(self, serializer):
        """Edit the record's details — not its posting.

        Posting changes go through `transfer`, which writes history. A PATCH
        that moved somebody's department would leave no trace of where they
        came from, so those fields are simply not writable here.
        """
        get_authorization(self.request).require(
            "employee.manage", Scope.FACILITY
        )
        for field in ("facility", "department", "position", "reports_to",
                      "status", "employment_type"):
            serializer.validated_data.pop(field, None)
        serializer.save()

    @action(detail=True, methods=["post"], url_path="transfer")
    def transfer(self, request, employee_code=None):
        get_authorization(request).require("employee.transfer", Scope.FACILITY)

        serializer = TransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        employee = transfer(
            self.get_object(),
            actor=request.user,
            reason=data["reason"],
            facility=(
                get_object_or_404(Facility, uuid=data["facility"])
                if data.get("facility") else None
            ),
            department=(
                get_object_or_404(Department, uuid=data["department"])
                if data.get("department") else None
            ),
            position=(
                get_object_or_404(Position, uuid=data["position"])
                if data.get("position") else None
            ),
            reports_to=(
                get_object_or_404(Employee, uuid=data["reports_to"])
                if data.get("reports_to") else None
            ),
            effective_on=data.get("effective_on"),
            event_type=data.get("event_type") or None,
        )
        return Response(EmployeeDetailSerializer(employee).data)

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, employee_code=None):
        get_authorization(request).require("employee.manage", Scope.FACILITY)
        employee = confirm(
            self.get_object(),
            actor=request.user,
            notes=request.data.get("notes", ""),
        )
        return Response(EmployeeDetailSerializer(employee).data)

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, employee_code=None):
        get_authorization(request).require("employee.separate", Scope.FACILITY)
        serializer = SuspendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        employee = suspend(
            self.get_object(),
            actor=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(EmployeeDetailSerializer(employee).data)

    @action(detail=True, methods=["post"], url_path="reinstate")
    def reinstate(self, request, employee_code=None):
        get_authorization(request).require("employee.separate", Scope.FACILITY)
        employee = reinstate(
            self.get_object(),
            actor=request.user,
            reason=request.data.get("reason", ""),
        )
        return Response(EmployeeDetailSerializer(employee).data)

    @action(detail=True, methods=["post"], url_path="separate")
    def separate(self, request, employee_code=None):
        get_authorization(request).require("employee.separate", Scope.FACILITY)
        serializer = SeparateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        employee = separate(
            self.get_object(),
            actor=request.user,
            reason=data["reason"],
            event_type=data["event_type"],
            last_working_day=data.get("last_working_day"),
            notes=data.get("notes", ""),
        )
        return Response(EmployeeDetailSerializer(employee).data)

    # -- attached records ---------------------------------------------------

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, employee_code=None):
        """The whole employment timeline, newest first."""
        events = self.get_object().events.all()
        return Response(EmploymentEventSerializer(events, many=True).data)

    @action(detail=True, methods=["get"], url_path="team")
    def team(self, request, employee_code=None):
        """Everyone below this person, at any depth."""
        return Response(
            EmployeeListSerializer(team_of(self.get_object()), many=True).data
        )

    @action(detail=True, methods=["get"], url_path="practice-status")
    def practice_status(self, request, employee_code=None):
        """Whether this person may treat patients, and why not.

        A list of blockers rather than a boolean: a manager needs to know
        which thing to fix, and there is often more than one.
        """
        employee = self.get_object()
        blockers = practice_blockers(employee)
        return Response(
            {
                "employee": employee.employee_code,
                "may_practise": not blockers,
                "is_provider": employee.is_provider,
                "blockers": blockers,
            }
        )

    @action(detail=True, methods=["get", "post"], url_path="credentials")
    def credentials(self, request, employee_code=None):
        employee = self.get_object()
        if request.method == "GET":
            get_authorization(request).require("credential.read", Scope.FACILITY)
            return Response(
                CredentialSerializer(
                    employee.credentials.all(), many=True
                ).data
            )

        get_authorization(request).require("employee.manage", Scope.FACILITY)
        serializer = CredentialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential = serializer.save(
            employee=employee, created_by_id=request.user.uuid
        )
        return Response(
            CredentialSerializer(credential).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="experience")
    def experience(self, request, employee_code=None):
        employee = self.get_object()
        if request.method == "GET":
            return Response(
                ExperienceSerializer(employee.experience.all(), many=True).data
            )

        get_authorization(request).require("employee.manage", Scope.FACILITY)
        serializer = ExperienceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = serializer.save(
            employee=employee, created_by_id=request.user.uuid
        )
        return Response(
            ExperienceSerializer(row).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get", "post"], url_path="skills")
    def skills(self, request, employee_code=None):
        employee = self.get_object()
        if request.method == "GET":
            return Response(
                SkillSerializer(employee.skills.all(), many=True).data
            )

        get_authorization(request).require("employee.manage", Scope.FACILITY)
        serializer = SkillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = serializer.save(
            employee=employee,
            assessed_by_id=request.user.uuid,
            assessed_by_name=getattr(request.user, "full_name", ""),
            created_by_id=request.user.uuid,
        )
        return Response(
            SkillSerializer(row).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request, employee_code=None):
        employee = self.get_object()
        if request.method == "GET":
            return Response(
                EmployeeDocumentSerializer(
                    employee.documents.all(), many=True
                ).data
            )

        get_authorization(request).require("employee.manage", Scope.FACILITY)
        serializer = EmployeeDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = serializer.save(
            employee=employee,
            uploaded_by_id=request.user.uuid,
            created_by_id=request.user.uuid,
        )
        return Response(
            EmployeeDocumentSerializer(row).data,
            status=status.HTTP_201_CREATED,
        )

    # -- pay ----------------------------------------------------------------

    @action(
        detail=True, methods=["get", "post"], url_path="contracts",
        permission_classes=[IsAuthenticated, HasPermission.of("salary.read")],
    )
    def contracts(self, request, employee_code=None):
        """Terms of employment, including pay.

        Behind `salary.read` rather than `employee.read`: the directory and
        the payroll are different questions, and most people who need the
        first need none of the second.
        """
        employee = self.get_object()
        if request.method == "GET":
            return Response(
                {
                    "current": (
                        EmploymentContractSerializer(
                            current_contract(employee)
                        ).data
                        if current_contract(employee) else None
                    ),
                    "history": EmploymentContractSerializer(
                        employee.contracts.all(), many=True
                    ).data,
                }
            )

        get_authorization(request).require("employee.manage", Scope.FACILITY)
        serializer = IssueContractSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        contract = issue_contract(
            employee=employee,
            starts_on=data["starts_on"],
            basic_salary=data["basic_salary"],
            actor=request.user,
            employment_type=data.get("employment_type") or None,
            ends_on=data.get("ends_on"),
            allowances=data.get("allowances") or {},
            rate_basis=data.get("rate_basis", "monthly"),
            notice_period_days=data.get("notice_period_days", 30),
            working_hours_per_week=data.get("working_hours_per_week", 48),
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
        )
        return Response(
            EmploymentContractSerializer(contract).data,
            status=status.HTTP_201_CREATED,
        )


class CredentialViewSet(viewsets.ReadOnlyModelViewSet):
    """Credentials across the workforce, and their verification."""

    serializer_class = CredentialSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("credential.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Credential, relations=["employee"],
        fields=["credential_type", "verification_status"],
    )

    def get_queryset(self):
        queryset = Credential.objects.select_related("employee")
        if self.request.query_params.get("unverified") == "true":
            queryset = queryset.filter(verification_status="unverified")
        return queryset.order_by("expires_on")

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, uuid=None):
        """Record that somebody checked this against the issuing register.

        Refused for the credential's own holder — self-verification is how a
        forged registration survives in a hospital.
        """
        get_authorization(request).require("credential.verify", Scope.ORGANIZATION)
        serializer = VerifyCredentialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential = verify_credential(
            self.get_object(),
            actor=request.user,
            passed=serializer.validated_data["passed"],
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(CredentialSerializer(credential).data)


class HrDashboardView(APIView):
    """Headcount, vacancies, and what is about to lapse."""

    permission_classes = [IsAuthenticated, HasPermission.of("employee.read")]

    def get(self, request):
        facility = None
        if request.query_params.get("facility"):
            facility = get_object_or_404(
                Facility, uuid=request.query_params["facility"]
            )
        return Response(
            {
                "headcount": headcount(facility),
                "expiring_credentials": expiring_credentials(facility),
                "expiring_contracts": (
                    expiring_contracts(facility)
                    if get_authorization(request).has("salary.read")
                    else []
                ),
                "separations": separations(facility),
            }
        )
