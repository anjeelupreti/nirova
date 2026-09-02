"""Appointments, provider schedules and the walk-in queue.

Two things share this app because they are the same problem seen from two
ends. An appointment is a claim on a provider's future time; a queue token is
a claim on their time *today*. In a Nepali clinic both arrive at once — a
booked follow-up and a walk-in who has travelled four hours — and the system
that sequences them has to see both.
"""

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Department, Facility
from apps.patients.models import Patient


class ProviderSchedule(BaseModel):
    """When a clinician is available at a facility, and how they are booked.

    The provider is identified by employee UUID rather than a foreign key,
    because employees belong to the HRMS module which does not exist yet. When
    it lands, this becomes a foreign key without changing the semantics --
    which is why the field is a UUID and not a name string.
    """

    class Weekday(models.IntegerChoices):
        # Sunday first: the Nepali working week runs Sunday to Friday.
        SUNDAY = 0, "Sunday"
        MONDAY = 1, "Monday"
        TUESDAY = 2, "Tuesday"
        WEDNESDAY = 3, "Wednesday"
        THURSDAY = 4, "Thursday"
        FRIDAY = 5, "Friday"
        SATURDAY = 6, "Saturday"

    provider_uuid = models.UUIDField(db_index=True)
    provider_name = models.CharField(
        max_length=255,
        help_text="Denormalised for display; employees live in a module that "
                  "does not exist yet.",
    )
    provider_speciality = models.CharField(max_length=128, blank=True)

    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="provider_schedules"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="provider_schedules",
    )
    room = models.CharField(max_length=64, blank=True)

    weekday = models.IntegerField(choices=Weekday.choices, db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(default=15)

    #: How many patients may hold the same slot. Above 1 this is deliberate
    #: overbooking, which is normal practice in high-volume OPD clinics where
    #: no-show rates are high -- but it is a decision, so it is explicit.
    slot_capacity = models.PositiveSmallIntegerField(default=1)
    #: Walk-in headroom kept back from online booking, so a patient who has
    #: travelled from a village is not turned away by a full online diary.
    walk_in_reserve = models.PositiveSmallIntegerField(default=0)

    #: Range over which this pattern applies. Ending a schedule closes future
    #: booking without disturbing appointments already made.
    effective_from = models.DateField(default=timezone.localdate)
    effective_to = models.DateField(null=True, blank=True)

    is_accepting_online = models.BooleanField(default=True)
    consultation_fee = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "provider_schedule"
        ordering = ["weekday", "start_time"]
        indexes = [
            models.Index(fields=["provider_uuid", "weekday"]),
            models.Index(fields=["facility", "weekday", "is_active"]),
        ]

    def __str__(self):
        return f"{self.provider_name} — {self.get_weekday_display()} {self.start_time:%H:%M}"

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError({"end_time": "The session must end after it starts."})
        if self.walk_in_reserve > self.total_slots:
            raise ValidationError(
                {"walk_in_reserve": "More slots reserved for walk-ins than exist."}
            )

    @property
    def total_slots(self) -> int:
        start = datetime.combine(timezone.localdate(), self.start_time)
        end = datetime.combine(timezone.localdate(), self.end_time)
        minutes = (end - start).total_seconds() / 60
        return int(minutes // self.slot_minutes) if self.slot_minutes else 0

    def slot_times(self, on_date) -> list:
        """Every slot start time for a given date, as aware datetimes."""
        slots = []
        cursor = datetime.combine(on_date, self.start_time)
        end = datetime.combine(on_date, self.end_time)
        step = timedelta(minutes=self.slot_minutes)
        current_tz = timezone.get_current_timezone()
        while cursor + step <= end:
            slots.append(timezone.make_aware(cursor, current_tz))
            cursor += step
        return slots

    def applies_on(self, on_date) -> bool:
        if not self.is_active or self.effective_from > on_date:
            return False
        if self.effective_to and self.effective_to < on_date:
            return False
        # Python's weekday() is Monday=0; this model is Sunday=0.
        return (on_date.weekday() + 1) % 7 == self.weekday


class ScheduleException(BaseModel):
    """A day a provider is unavailable, or available unusually.

    Kept separate from the recurring pattern so leave, public holidays and
    conferences do not require editing the underlying schedule — and so the
    schedule remains correct once the exception passes.
    """

    schedule = models.ForeignKey(
        ProviderSchedule, null=True, blank=True, on_delete=models.CASCADE,
        related_name="exceptions",
    )
    #: Set instead of `schedule` to block a provider across every schedule
    #: they hold -- which is what leave actually means.
    provider_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )

    exception_date = models.DateField(db_index=True)
    is_unavailable = models.BooleanField(default=True)
    #: For an extra session rather than a cancellation.
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "schedule_exception"
        ordering = ["-exception_date"]
        indexes = [models.Index(fields=["exception_date", "provider_uuid"])]

    def __str__(self):
        state = "unavailable" if self.is_unavailable else "extra session"
        return f"{self.exception_date} — {state}"


class AppointmentStatus(models.TextChoices):
    """The full life of an appointment, including the ways it does not happen.

    `NO_SHOW` is distinct from `CANCELLED` because they mean opposite things
    operationally: a cancellation freed the slot in time, a no-show wasted it.
    Conflating them makes provider utilisation unmeasurable.
    """

    REQUESTED = "requested", "Requested"
    SCHEDULED = "scheduled", "Scheduled"
    CONFIRMED = "confirmed", "Confirmed"
    ARRIVED = "arrived", "Patient arrived"
    IN_CONSULTATION = "in_consultation", "In consultation"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    NO_SHOW = "no_show", "Did not attend"
    RESCHEDULED = "rescheduled", "Rescheduled"


#: Statuses that still hold a slot. Used when counting availability.
OCCUPIES_SLOT = {
    AppointmentStatus.REQUESTED,
    AppointmentStatus.SCHEDULED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.ARRIVED,
    AppointmentStatus.IN_CONSULTATION,
}


class AppointmentSource(models.TextChoices):
    WALK_IN = "walk_in", "Walk-in"
    COUNTER = "counter", "Booked at counter"
    PHONE = "phone", "Telephone"
    ONLINE = "online", "Patient portal"
    MOBILE = "mobile", "Mobile app"
    REFERRAL = "referral", "Referral"
    FOLLOW_UP = "follow_up", "Follow-up"


class Appointment(BaseModel):
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="appointments"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="appointments"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="appointments",
    )
    schedule = models.ForeignKey(
        ProviderSchedule, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="appointments",
    )

    provider_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    provider_name = models.CharField(max_length=255, blank=True)

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    scheduled_for = models.DateTimeField(db_index=True)
    duration_minutes = models.PositiveSmallIntegerField(default=15)

    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.SCHEDULED,
        db_index=True,
    )
    source = models.CharField(
        max_length=16, choices=AppointmentSource.choices, default=AppointmentSource.COUNTER
    )

    reason = models.CharField(max_length=512, blank=True)
    #: Higher runs first in the queue. Emergencies and the frail elderly are
    #: not made to wait their turn.
    priority = models.PositiveSmallIntegerField(default=0)
    is_follow_up = models.BooleanField(default=False)
    previous_appointment = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="follow_ups",
    )

    # -- timestamps that make waiting time measurable --------------------
    #
    # Each is the boundary of one interval a patient actually experiences.
    # Without all four, "how long did people wait?" cannot be answered, and
    # section 21 of the specification requires exactly that.

    arrived_at = models.DateTimeField(null=True, blank=True)
    consultation_started_at = models.DateTimeField(null=True, blank=True)
    consultation_ended_at = models.DateTimeField(null=True, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    cancelled_by_id = models.UUIDField(null=True, blank=True)

    rescheduled_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="rescheduled_from",
    )

    booked_by_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "appointment"
        ordering = ["scheduled_for"]
        indexes = [
            models.Index(fields=["facility", "scheduled_for", "status"]),
            models.Index(fields=["provider_uuid", "scheduled_for"]),
            models.Index(fields=["patient", "-scheduled_for"]),
            models.Index(fields=["status", "scheduled_for"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.patient.full_name} @ {self.scheduled_for:%Y-%m-%d %H:%M}"

    @property
    def occupies_slot(self) -> bool:
        return self.status in OCCUPIES_SLOT

    @property
    def waiting_minutes(self) -> int | None:
        """How long the patient waited between arriving and being seen."""
        if not self.arrived_at or not self.consultation_started_at:
            return None
        return int(
            (self.consultation_started_at - self.arrived_at).total_seconds() / 60
        )

    @property
    def consultation_minutes(self) -> int | None:
        if not self.consultation_started_at or not self.consultation_ended_at:
            return None
        return int(
            (self.consultation_ended_at - self.consultation_started_at).total_seconds()
            / 60
        )

    @property
    def is_overdue(self) -> bool:
        """Past its time and the patient has not been seen."""
        return (
            self.status in {AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED,
                            AppointmentStatus.ARRIVED}
            and self.scheduled_for < timezone.now()
        )


class QueueStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    CALLED = "called", "Called"
    IN_SERVICE = "in_service", "In consultation"
    COMPLETED = "completed", "Completed"
    SKIPPED = "skipped", "Skipped"
    LEFT = "left", "Left without being seen"
    TRANSFERRED = "transferred", "Transferred"


class QueueToken(BaseModel):
    """A patient's place in today's queue.

    Separate from the appointment because not everyone in the queue has one --
    walk-ins are the majority in most Nepali OPDs — and because a queue is a
    live ordering that changes through the day, while an appointment is a
    booking made in advance.

    `SKIPPED` exists rather than deleting a token: a patient who missed their
    call because they stepped out for tea is re-queued, and the fact that they
    were called once is part of the record.
    """

    token_number = models.CharField(max_length=16, db_index=True)
    #: Groups tokens issued by the same counter or clinic on the same day, so
    #: numbering restarts daily per queue rather than running forever.
    queue_date = models.DateField(default=timezone.localdate, db_index=True)

    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="queue_tokens"
    )
    appointment = models.OneToOneField(
        Appointment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="queue_token",
    )

    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="queue_tokens"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="queue_tokens",
    )
    provider_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    counter = models.CharField(max_length=32, blank=True)

    status = models.CharField(
        max_length=16, choices=QueueStatus.choices, default=QueueStatus.WAITING,
        db_index=True,
    )
    #: Higher is seen sooner. Triage sets this; it is not first-come-first-served
    #: when someone is genuinely sick.
    priority = models.PositiveSmallIntegerField(default=0)
    is_emergency = models.BooleanField(default=False)

    issued_at = models.DateTimeField(default=timezone.now)
    called_at = models.DateTimeField(null=True, blank=True)
    service_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    #: Incremented each time the token is called without the patient
    #: appearing. After a threshold the queue moves on rather than stalling.
    call_count = models.PositiveSmallIntegerField(default=0)

    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "queue_token"
        ordering = ["-priority", "issued_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "queue_date", "token_number"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_token_per_facility_day",
            )
        ]
        indexes = [
            models.Index(fields=["facility", "queue_date", "status"]),
            models.Index(fields=["department", "queue_date", "status"]),
            models.Index(fields=["status", "-priority", "issued_at"]),
        ]

    def __str__(self):
        return f"{self.token_number} — {self.patient.full_name}"

    @property
    def waiting_minutes(self) -> int:
        """Minutes waited so far, or in total once seen."""
        end = self.service_started_at or timezone.now()
        return int((end - self.issued_at).total_seconds() / 60)

    @property
    def is_active(self) -> bool:
        return self.status in {
            QueueStatus.WAITING,
            QueueStatus.CALLED,
            QueueStatus.IN_SERVICE,
        }
