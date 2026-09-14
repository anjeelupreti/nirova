"""Clinical vocabulary: the codes a record has to be written in.

**A diagnosis nobody coded is a diagnosis nobody can count.** The ministry's
monthly return, an insurer's claim, and any question of the form "how much
typhoid did we see this year" are all counts of codes, and the product has
carried `icd10_code` as a free-text field since the first commit: optional,
unvalidated, and in practice empty.

This is the table it should have been validated against. Three decisions:

**Per tenant, not shared.** ICD-10 is the same everywhere, so a control-plane
copy would save space -- and would make a hospital's own additions
impossible. Hospitals do add: a local code for a package, a term their
consultants insist on. The table is seeded identically and then belongs to
the customer.

**Seeded with what Nepal sees, not with all of ICD-10.** The full
classification is ~70,000 codes; a clinician scrolling past 70,000 entries
codes nothing. `seed_icd10` loads the few hundred that cover most of a
Nepali outpatient and ward day, marked `is_common`, and the rest can be
imported when somebody needs them.

**Ranked by use.** Every time a code is chosen it is counted, so after a
fortnight the list a hospital is offered is the list that hospital uses.
"""

from django.db import models

from apps.common.models import BaseModel


class CodeSystem(models.TextChoices):
    ICD10 = "icd10", "ICD-10"
    #: Local codes a hospital adds for something the classification lacks.
    LOCAL = "local", "Local"


class DiagnosisCode(BaseModel):
    """One codeable clinical term."""

    system = models.CharField(max_length=16, choices=CodeSystem.choices, default=CodeSystem.ICD10)
    code = models.CharField(max_length=16, db_index=True)
    title = models.CharField(max_length=255)
    #: The ICD chapter, for grouping a list and for the ministry's return.
    chapter = models.CharField(max_length=64, blank=True)
    #: Words somebody would actually type: "sugar" for diabetes, "BP" for
    #: hypertension, "jaundice" for hepatitis. Searched alongside the title.
    keywords = models.CharField(max_length=255, blank=True)
    is_common = models.BooleanField(default=False, db_index=True)
    times_used = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "terminology_diagnosis_code"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["system", "code"], name="uniq_code_per_system"),
        ]
        indexes = [models.Index(fields=["is_common", "-times_used"])]

    def __str__(self) -> str:
        return f"{self.code} {self.title}"
