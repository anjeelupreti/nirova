"""The discussion about a patient, as stored. See `apps/patients/discussion.py`."""

from django.db import models

from apps.common.models import BaseModel
from apps.patients.models import Patient


class CareMessage(BaseModel):
    """One message between staff about one patient. Kept, never edited.

    A message somebody acted on at three in the morning is part of the record
    of what happened, so it is not changed afterwards: a correction is another
    message.
    """

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="care_messages")
    author_id = models.UUIDField(null=True, blank=True, db_index=True)
    author_name = models.CharField(max_length=255, blank=True)
    body = models.TextField()
    urgent = models.BooleanField(default=False)
    #: The colleagues who were notified, as `{"id", "name"}`, resolved when sent.
    mentions = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "patient_care_message"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["patient", "created_at"])]

    def __str__(self) -> str:
        return f"{self.author_name} on {self.patient_id}"
